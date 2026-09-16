"""Background drip worker.

Runs in a thread inside the API container (or as its own Railway service with
`python -m app.worker`). Every tick it gives each active LinkedIn account at
most one invitation, which is what keeps the pacing human and the daily and
weekly caps honest.
"""
from __future__ import annotations

import logging
import random
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import engine, session_scope
from .linkedin import LinkedInClient, SendResult
from .models import Campaign, Invitation, LinkedInAccount, as_utc, utcnow
from .scheduling import next_day_start, send_decision
from .security import decrypt_json

logger = logging.getLogger("worker")

MAX_ATTEMPTS = 5
COOLDOWN_MINUTES = 20
ADVISORY_LOCK_KEY = 815273


def build_client(account: LinkedInAccount) -> LinkedInClient:
    tokens = decrypt_json(account.cookies_encrypted)
    return LinkedInClient(tokens=tokens, user_agent=account.user_agent)


def result_text(invitation: Invitation) -> str:
    """What gets written back into the Google Sheet."""
    when = as_utc(invitation.sent_at) or utcnow()
    stamp = when.strftime("%Y-%m-%d %H:%M UTC")
    if invitation.status == "sent":
        return f"Connection request sent! ({stamp})"
    label = "Skipped" if invitation.status == "skipped" else "Not sent"
    parts = [label]
    if invitation.http_status:
        parts.append(f"({invitation.http_status})")
    detail = invitation.error_code or ""
    if invitation.error_message:
        detail = f"{detail} - {invitation.error_message}" if detail else invitation.error_message
    if detail:
        parts.append("-")
        parts.append(detail)
    return " ".join(parts)[:400]


class DripWorker:
    def __init__(self, poll_seconds: int | None = None, client_factory=build_client) -> None:
        settings = get_settings()
        self.poll_seconds = poll_seconds or settings.worker_poll_seconds
        self.client_factory = client_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock_connection = None
        self._has_lock = False

    # -- lifecycle ---------------------------------------------------------
    def _acquire_singleton_lock(self) -> bool:
        """Only one worker may run against a database, even with replicas.

        Attempted on every tick rather than once at startup. During a deploy
        the outgoing container still holds the lock while the new one boots,
        so a worker that gave up at that moment stayed stopped until somebody
        restarted the service by hand -- with the API still up and the queue
        quietly going nowhere.
        """
        if self._has_lock:
            return True
        if not engine.url.get_backend_name().startswith("postgresql"):
            self._has_lock = True
            return True
        try:
            connection = engine.raw_connection()
            cursor = connection.cursor()
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
            acquired = bool(cursor.fetchone()[0])
            cursor.close()
            if acquired:
                self._lock_connection = connection  # held for the process lifetime
                self._has_lock = True
            else:
                connection.close()
            return acquired
        except Exception:  # pragma: no cover - never block boot on this
            logger.exception("Could not take the worker lock, running anyway")
            self._has_lock = True
            return True

    def start(self) -> bool:
        self._thread = threading.Thread(target=self._loop, name="drip-worker", daemon=True)
        self._thread.start()
        logger.info("Drip worker started (poll every %ss)", self.poll_seconds)
        return True

    def is_running(self) -> bool:
        """Whether the thread is actually alive, for the healthcheck to report."""
        return bool(self._thread and self._thread.is_alive())

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._lock_connection is not None:
            try:
                self._lock_connection.close()  # releases the advisory lock
            except Exception:  # pragma: no cover
                pass
            self._lock_connection = None
        self._has_lock = False

    def _loop(self) -> None:
        standing_by = False
        while not self._stop.wait(self.poll_seconds):
            if not self._acquire_singleton_lock():
                if not standing_by:
                    logger.warning(
                        "Another worker holds the lock; standing by, retrying every %ss.",
                        self.poll_seconds,
                    )
                    standing_by = True
                continue
            if standing_by:
                logger.info("Took over the worker lock; resuming sends.")
                standing_by = False
            try:
                self.tick()
            except Exception:  # pragma: no cover - the loop must never die
                logger.exception("Worker tick failed")

    # -- one pass ----------------------------------------------------------
    def tick(self, now: datetime | None = None) -> dict:
        now = now or utcnow()
        summary = {"sent": 0, "failed": 0, "skipped": 0, "accounts": 0}
        with session_scope() as db:
            account_ids = list(
                db.scalars(
                    select(LinkedInAccount.id).where(
                        LinkedInAccount.status.in_(["active", "cooldown"])
                    )
                )
            )
        for account_id in account_ids:
            try:
                with session_scope() as db:
                    outcome = self.process_account(db, account_id, now)
                if outcome:
                    summary["accounts"] += 1
                    if outcome in summary:
                        summary[outcome] += 1
            except Exception:
                logger.exception("Account %s failed this tick", account_id)
        try:
            with session_scope() as db:
                self.flush_sheet_writebacks(db)
        except Exception:
            logger.exception("Sheet write-back failed")
        return summary

    def process_account(self, db: Session, account_id: int, now: datetime) -> str | None:
        account = db.get(LinkedInAccount, account_id)
        if account is None:
            return None

        if account.status == "cooldown":
            scheduled = as_utc(account.next_send_at)
            if scheduled and scheduled > now:
                return None
            account.status = "active"
            account.status_detail = ""

        decision = send_decision(db, account, now)
        if not decision["send"]:
            if decision.get("retry_at"):
                account.next_send_at = decision["retry_at"]
            return None

        invitation = self._next_invitation(db, account)
        if invitation is None:
            return None

        client = self.client_factory(account)
        try:
            result = client.send_invitation(invitation.profile_id, invitation.message)
        except Exception as error:  # a bug in the client must not lose the row
            logger.exception("send_invitation crashed")
            result = SendResult(
                status="failed", code="INTERNAL", message=str(error)[:300], retry=True
            )

        self._apply_result(db, account, invitation, result, now)
        self._maybe_complete_campaign(db, invitation.campaign_id)

        # Pace the next one for this account.
        delay = random.randint(
            max(account.min_delay_seconds, 5), max(account.max_delay_seconds, account.min_delay_seconds, 10)
        )
        account.next_send_at = now + timedelta(seconds=delay)
        self._apply_account_action(account, result, now)
        return result.status

    def _next_invitation(self, db: Session, account: LinkedInAccount) -> Invitation | None:
        statement = (
            select(Invitation)
            .join(Campaign, Campaign.id == Invitation.campaign_id)
            .where(
                Invitation.account_id == account.id,
                Invitation.status == "pending",
                Campaign.status == "running",
            )
            .order_by(Invitation.id)
            .limit(1)
        )
        if engine.url.get_backend_name().startswith("postgresql"):
            statement = statement.with_for_update(skip_locked=True, of=Invitation)
        return db.scalars(statement).first()

    def _apply_result(
        self,
        db: Session,
        account: LinkedInAccount,
        invitation: Invitation,
        result: SendResult,
        now: datetime,
    ) -> None:
        invitation.attempts += 1
        invitation.http_status = result.http_status
        invitation.error_code = result.code if result.status != "sent" else ""
        invitation.error_message = result.message if result.status != "sent" else ""
        invitation.updated_at = now

        if result.status == "sent":
            invitation.status = "sent"
            invitation.sent_at = now
        elif result.retry and invitation.attempts < MAX_ATTEMPTS:
            invitation.status = "pending"  # try again on a later tick
        else:
            invitation.status = result.status  # failed | skipped

        if invitation.status != "pending":
            campaign = db.get(Campaign, invitation.campaign_id)
            if campaign and campaign.write_back and invitation.sheet_row:
                invitation.sheet_synced = False

    def _apply_account_action(
        self, account: LinkedInAccount, result: SendResult, now: datetime
    ) -> None:
        if result.account_action == "needs_reauth":
            account.status = "needs_reauth"
            account.status_detail = result.message
        elif result.account_action == "cooldown":
            account.status = "cooldown"
            account.status_detail = result.message
            account.next_send_at = now + timedelta(minutes=COOLDOWN_MINUTES)
        elif result.account_action == "stop_today":
            account.status_detail = result.message
            account.next_send_at = next_day_start(account, now)

    def _maybe_complete_campaign(self, db: Session, campaign_id: int) -> None:
        campaign = db.get(Campaign, campaign_id)
        if campaign is None or campaign.status != "running":
            return
        # The session is autoflush=False, so the row just updated is still
        # "pending" in the database unless we push it first.
        db.flush()
        remaining = db.scalar(
            select(Invitation.id)
            .where(Invitation.campaign_id == campaign_id, Invitation.status == "pending")
            .limit(1)
        )
        if remaining is None:
            campaign.status = "completed"
            campaign.completed_at = utcnow()

    # -- google sheets -----------------------------------------------------
    def flush_sheet_writebacks(self, db: Session) -> int:
        from . import sheets

        if not sheets.sheets_enabled():
            return 0
        pending = list(
            db.scalars(
                select(Invitation)
                .where(Invitation.sheet_synced.is_(False), Invitation.sheet_row.isnot(None))
                .order_by(Invitation.campaign_id)
                .limit(500)
            )
        )
        if not pending:
            return 0

        by_campaign: dict[int, list[Invitation]] = {}
        for invitation in pending:
            by_campaign.setdefault(invitation.campaign_id, []).append(invitation)

        written = 0
        for campaign_id, invitations in by_campaign.items():
            campaign = db.get(Campaign, campaign_id)
            if not campaign or not campaign.write_back or campaign.source_type != "sheet":
                for invitation in invitations:
                    invitation.sheet_synced = True
                continue
            updates = [(inv.sheet_row, result_text(inv)) for inv in invitations if inv.sheet_row]
            try:
                written += sheets.write_results(
                    campaign.sheet_url, campaign.sheet_tab, campaign.result_column, updates
                )
            except Exception as error:
                logger.warning("Sheet write-back failed for campaign %s: %s", campaign_id, error)
                continue
            for invitation in invitations:
                invitation.sheet_synced = True
        return written


_worker: DripWorker | None = None


def start_worker() -> DripWorker | None:
    global _worker
    if _worker is not None:
        return _worker
    worker = DripWorker()
    worker.start()
    _worker = worker
    return worker


def worker_is_running() -> bool:
    """For /api/health, which used to echo the setting rather than the fact."""
    return _worker is not None and _worker.is_running()


def stop_worker() -> None:
    global _worker
    if _worker is not None:
        _worker.stop()
        _worker = None


if __name__ == "__main__":  # run as a standalone Railway service
    logging.basicConfig(level=logging.INFO)
    from .models import Base

    Base.metadata.create_all(engine)
    standalone = DripWorker()
    standalone.start()
    try:
        while True:
            threading.Event().wait(60)
    except KeyboardInterrupt:
        standalone.stop()
