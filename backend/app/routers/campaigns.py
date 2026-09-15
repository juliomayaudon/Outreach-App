from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import sheets
from ..db import get_db
from ..deps import current_user
from ..importers import ImportError_, TableData, parse_csv, prepare_rows, suggest_mapping
from ..models import Campaign, Invitation, LinkedInAccount, User, utcnow
from ..schemas import (
    CampaignCreateResult,
    CampaignOut,
    CampaignSheetCreate,
    ColumnMapping,
    InvitationOut,
    PreviewOut,
    SheetPreviewIn,
)
from .accounts import get_account_or_404

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])
sources_router = APIRouter(prefix="/api/sources", tags=["sources"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SAMPLE_SIZE = 5


# --------------------------------------------------------------------------
# previews
# --------------------------------------------------------------------------
@sources_router.post("/csv/preview", response_model=PreviewOut)
def preview_csv(file: UploadFile = File(...), _: User = Depends(current_user)):
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 10 MB.")
    try:
        table = parse_csv(data)
    except ImportError_ as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return PreviewOut(
        headers=table.headers,
        sample=table.rows[:SAMPLE_SIZE],
        total_rows=len(table.rows),
        suggested_mapping=suggest_mapping(table.headers),
    )


@sources_router.post("/sheet/preview", response_model=PreviewOut)
def preview_sheet(payload: SheetPreviewIn, _: User = Depends(current_user)):
    try:
        tabs = sheets.list_tabs(payload.url)
        data = sheets.read_rows(payload.url, payload.tab or (tabs[0] if tabs else ""))
    except sheets.SheetError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return PreviewOut(
        headers=data.headers,
        sample=data.rows[:SAMPLE_SIZE],
        total_rows=len(data.rows),
        suggested_mapping=suggest_mapping(data.headers),
        tabs=tabs,
    )


@sources_router.get("/sheet/config")
def sheet_config(_: User = Depends(current_user)):
    return {
        "enabled": sheets.sheets_enabled(),
        "service_account_email": sheets.service_account_email(),
    }


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def counts_for(db: Session, campaign_ids: list[int]) -> dict[int, dict]:
    if not campaign_ids:
        return {}
    rows = db.execute(
        select(Invitation.campaign_id, Invitation.status, func.count(Invitation.id))
        .where(Invitation.campaign_id.in_(campaign_ids))
        .group_by(Invitation.campaign_id, Invitation.status)
    ).all()
    result: dict[int, dict] = {
        cid: {"total": 0, "pending": 0, "sent": 0, "failed": 0, "skipped": 0}
        for cid in campaign_ids
    }
    for campaign_id, status, count in rows:
        bucket = result[campaign_id]
        bucket["total"] += count
        if status in bucket:
            bucket[status] += count
    return result


def serialize_campaign(db: Session, campaign: Campaign, counts: dict | None = None) -> CampaignOut:
    counts = counts or counts_for(db, [campaign.id])[campaign.id]
    account = db.get(LinkedInAccount, campaign.account_id)
    owner = db.get(User, campaign.owner_id)
    return CampaignOut(
        id=campaign.id,
        name=campaign.name,
        status=campaign.status,
        account_id=campaign.account_id,
        account_label=account.label if account else "",
        owner_id=campaign.owner_id,
        owner_name=(owner.name or owner.email) if owner else "",
        source_type=campaign.source_type,
        source_name=campaign.source_name,
        created_at=campaign.created_at,
        completed_at=campaign.completed_at,
        **counts,
    )


def get_campaign_or_404(db: Session, user: User, campaign_id: int) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or (not user.is_admin and campaign.owner_id != user.id):
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


def known_profile_ids(db: Session, account_id: int) -> set[str]:
    return set(
        db.scalars(
            select(Invitation.profile_id).where(
                Invitation.account_id == account_id,
                Invitation.status.in_(["pending", "sent"]),
            )
        )
    )


def create_campaign_from_table(
    db: Session,
    user: User,
    account: LinkedInAccount,
    table: TableData,
    mapping: ColumnMapping,
    *,
    name: str,
    source_type: str,
    source_name: str,
    note_template: str,
    sheet_url: str = "",
    sheet_tab: str = "",
    result_column: str = "Result",
    write_back: bool = False,
    start_now: bool = True,
) -> CampaignCreateResult:
    try:
        batch = prepare_rows(
            table,
            mapping.model_dump(),
            note_template=note_template,
            known_profile_ids=known_profile_ids(db, account.id),
        )
    except ImportError_ as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    if not batch.rows:
        raise HTTPException(status_code=400, detail="No usable rows found.")

    campaign = Campaign(
        owner_id=user.id,
        account_id=account.id,
        name=name.strip(),
        status="running" if start_now else "paused",
        source_type=source_type,
        source_name=source_name,
        sheet_url=sheet_url,
        sheet_tab=sheet_tab,
        result_column=result_column or "Result",
        write_back=write_back and source_type == "sheet",
    )
    db.add(campaign)
    db.flush()

    for row in batch.rows:
        db.add(
            Invitation(
                campaign_id=campaign.id,
                account_id=account.id,
                owner_id=user.id,
                profile_id=row.profile_id,
                raw_value=row.raw_value,
                full_name=row.full_name,
                company=row.company,
                title=row.title,
                message=row.message,
                status=row.status,
                error_code=row.error_code,
                error_message=row.error_message,
                sheet_row=row.sheet_row,
                sheet_synced=not (campaign.write_back and row.status == "skipped"),
                updated_at=utcnow() if row.status == "skipped" else None,
            )
        )
    db.commit()
    db.refresh(campaign)

    examples = [
        {"value": row.raw_value, "reason": row.error_message}
        for row in batch.rows
        if row.status == "skipped"
    ][:10]
    return CampaignCreateResult(
        campaign=serialize_campaign(db, campaign),
        queued=batch.queued,
        skipped=batch.skipped,
        skipped_examples=examples,
    )


# --------------------------------------------------------------------------
# create
# --------------------------------------------------------------------------
@router.post("/csv", response_model=CampaignCreateResult, status_code=201)
def create_campaign_from_csv(
    file: UploadFile = File(...),
    name: str = Form(...),
    account_id: int = Form(...),
    mapping: str = Form(...),
    note_template: str = Form(""),
    start_now: bool = Form(True),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    account = get_account_or_404(db, user, account_id)
    try:
        column_mapping = ColumnMapping(**json.loads(mapping))
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"Invalid column mapping: {error}") from error

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 10 MB.")
    try:
        table = parse_csv(data)
    except ImportError_ as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return create_campaign_from_table(
        db,
        user,
        account,
        table,
        column_mapping,
        name=name,
        source_type="csv",
        source_name=file.filename or "upload.csv",
        note_template=note_template,
        start_now=start_now,
    )


@router.post("/sheet", response_model=CampaignCreateResult, status_code=201)
def create_campaign_from_sheet(
    payload: CampaignSheetCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    account = get_account_or_404(db, user, payload.account_id)
    try:
        data = sheets.read_rows(payload.url, payload.tab)
    except sheets.SheetError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    table = TableData(headers=data.headers, rows=data.rows, row_numbers=data.row_numbers)
    return create_campaign_from_table(
        db,
        user,
        account,
        table,
        payload.mapping,
        name=payload.name,
        source_type="sheet",
        source_name=f"{payload.url} ({payload.tab})" if payload.tab else payload.url,
        note_template=payload.note_template,
        sheet_url=payload.url,
        sheet_tab=payload.tab,
        result_column=payload.result_column,
        write_back=payload.write_back,
        start_now=payload.start_now,
    )


# --------------------------------------------------------------------------
# read / control
# --------------------------------------------------------------------------
@router.get("", response_model=list[CampaignOut])
def list_campaigns(
    scope: str = Query("me", pattern="^(me|team)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    statement = select(Campaign).order_by(Campaign.id.desc())
    if scope == "me" or not user.is_admin:
        statement = statement.where(Campaign.owner_id == user.id)
    campaigns = list(db.scalars(statement))
    counts = counts_for(db, [c.id for c in campaigns])
    return [serialize_campaign(db, c, counts.get(c.id)) for c in campaigns]


@router.get("/{campaign_id}", response_model=CampaignOut)
def get_campaign(
    campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return serialize_campaign(db, get_campaign_or_404(db, user, campaign_id))


@router.get("/{campaign_id}/rows", response_model=list[InvitationOut])
def campaign_rows(
    campaign_id: int,
    status: str = Query("", pattern="^(|pending|sent|failed|skipped)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    get_campaign_or_404(db, user, campaign_id)
    statement = select(Invitation).where(Invitation.campaign_id == campaign_id)
    if status:
        statement = statement.where(Invitation.status == status)
    statement = statement.order_by(Invitation.id).offset(offset).limit(limit)
    return list(db.scalars(statement))


@router.post("/{campaign_id}/status", response_model=CampaignOut)
def set_campaign_status(
    campaign_id: int,
    action: str = Query(..., pattern="^(pause|resume|cancel)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    campaign = get_campaign_or_404(db, user, campaign_id)
    if action == "pause":
        campaign.status = "paused"
    elif action == "resume":
        if campaign.status == "completed":
            raise HTTPException(status_code=400, detail="This campaign already finished.")
        campaign.status = "running"
    else:
        campaign.status = "cancelled"
    db.commit()
    db.refresh(campaign)
    return serialize_campaign(db, campaign)


@router.post("/{campaign_id}/retry-failed", response_model=CampaignOut)
def retry_failed(
    campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    campaign = get_campaign_or_404(db, user, campaign_id)
    rows = list(
        db.scalars(
            select(Invitation).where(
                Invitation.campaign_id == campaign_id, Invitation.status == "failed"
            )
        )
    )
    for invitation in rows:
        invitation.status = "pending"
        invitation.attempts = 0
        invitation.error_code = ""
        invitation.error_message = ""
        invitation.http_status = None
    if rows and campaign.status == "completed":
        campaign.status = "running"
        campaign.completed_at = None
    db.commit()
    db.refresh(campaign)
    return serialize_campaign(db, campaign)


@router.get("/{campaign_id}/export")
def export_campaign(
    campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    campaign = get_campaign_or_404(db, user, campaign_id)
    rows = list(
        db.scalars(select(Invitation).where(Invitation.campaign_id == campaign_id).order_by(Invitation.id))
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["vmid", "full_name", "company", "title", "message", "status", "error_code",
         "error_message", "http_status", "attempts", "sent_at", "sheet_row"]
    )
    for row in rows:
        writer.writerow(
            [row.profile_id, row.full_name, row.company, row.title, row.message, row.status,
             row.error_code, row.error_message, row.http_status or "", row.attempts,
             row.sent_at.isoformat() if row.sent_at else "", row.sheet_row or ""]
        )
    buffer.seek(0)
    filename = f"campaign-{campaign.id}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(
    campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    campaign = get_campaign_or_404(db, user, campaign_id)
    db.query(Invitation).filter(Invitation.campaign_id == campaign_id).delete()
    db.delete(campaign)
    db.commit()
