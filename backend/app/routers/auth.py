from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import oauth
from ..config import get_settings
from ..db import get_db
from ..deps import SESSION_COOKIE, admin_user, current_user
from ..models import User
from ..schemas import LoginIn, UserCreate, UserOut, UserUpdate
from ..security import create_session_token, hash_password, verify_password

router = APIRouter(prefix="/api", tags=["auth"])

OAUTH_STATE_COOKIE = "outreach_oauth_state"


def _start_session(response: Response, user: User) -> None:
    settings = get_settings()
    max_age = settings.session_days * 24 * 3600
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user.id, max_age),
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


@router.post("/auth/login", response_model=UserOut)
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled")
    _start_session(response, user)
    return user


# --------------------------------------------------------------------------
# google sign-in
# --------------------------------------------------------------------------
@router.get("/auth/config")
def auth_config():
    """What the login screen needs to know before anyone types anything."""
    settings = get_settings()
    return {
        "google_enabled": oauth.enabled(),
        "google_domain": settings.google_allowed_domain,
    }


@router.get("/auth/google/start")
def google_start(request: Request):
    if not oauth.enabled():
        raise HTTPException(status_code=404, detail="Google sign-in is not configured")
    state = oauth.new_state()
    response = RedirectResponse(
        oauth.authorize_url(state, oauth.redirect_uri(str(request.base_url))),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    # Signed-in-ness is decided by comparing this back on the callback, so the
    # code cannot be replayed from a page the person did not start.
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        path="/",
    )
    return response


def _failed(message: str) -> RedirectResponse:
    response = RedirectResponse(f"/?auth_error={quote(message)}", status_code=303)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    return response


@router.get("/auth/google/callback", name="google_callback")
def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    if not oauth.enabled():
        raise HTTPException(status_code=404, detail="Google sign-in is not configured")
    if error:
        return _failed("Google sign-in was cancelled.")
    expected = request.cookies.get(OAUTH_STATE_COOKIE, "")
    if not code or not state or not expected or state != expected:
        return _failed("That sign-in link expired. Try again.")

    try:
        identity = oauth.verified_identity(
            oauth.exchange_code(code, oauth.redirect_uri(str(request.base_url)))
        )
    except oauth.OAuthError as problem:
        return _failed(str(problem))

    user = db.scalar(select(User).where(User.email == identity["email"]))
    if user is None:
        user = User(
            email=identity["email"],
            name=identity["name"] or identity["email"].split("@")[0],
            password_hash="",  # signs in with Google; no password will match
            role="member",
            timezone=get_settings().default_timezone,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.is_active:
        return _failed("This account is disabled.")
    elif identity["name"] and not user.name:
        user.name = identity["name"]
        db.commit()

    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    _start_session(response, user)
    return response


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(User).order_by(User.id)))


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate, _: User = Depends(admin_user), db: Session = Depends(get_db)
):
    email = payload.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="That email already exists")
    user = User(
        email=email,
        name=payload.name.strip(),
        password_hash=hash_password(payload.password),
        role="admin" if payload.role == "admin" else "member",
        timezone=get_settings().default_timezone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    actor: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not actor.is_admin and actor.id != user_id:
        raise HTTPException(status_code=403, detail="Admins only")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.name is not None:
        user.name = payload.name.strip()
    if payload.timezone is not None:
        user.timezone = payload.timezone
    if payload.password:
        user.password_hash = hash_password(payload.password)
    if actor.is_admin:
        if payload.role in ("admin", "member"):
            user.role = payload.role
        if payload.is_active is not None:
            if not payload.is_active and user.id == actor.id:
                raise HTTPException(status_code=400, detail="You cannot disable yourself")
            user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    return user
