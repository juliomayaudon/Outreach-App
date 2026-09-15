from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import SESSION_COOKIE, admin_user, current_user
from ..models import User
from ..schemas import LoginIn, UserCreate, UserOut, UserUpdate
from ..security import create_session_token, hash_password, verify_password

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/login", response_model=UserOut)
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled")

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
    return user


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
