"""FastAPI application: API + the built React SPA in one container."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal, engine
from .models import Base, User
from .routers import accounts, auth, campaigns, stats
from .security import hash_password
from .worker import start_worker, stop_worker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def bootstrap_admin() -> None:
    """Creates the first admin from ADMIN_EMAIL / ADMIN_PASSWORD."""
    if not settings.admin_password:
        return
    with SessionLocal() as db:
        if db.scalar(select(User).limit(1)):
            return
        db.add(
            User(
                email=settings.admin_email.strip().lower(),
                name="Admin",
                password_hash=hash_password(settings.admin_password),
                role="admin",
                timezone=settings.default_timezone,
            )
        )
        db.commit()
        logger.info("Created the first admin user: %s", settings.admin_email)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    bootstrap_admin()
    if settings.run_worker:
        start_worker()
    yield
    stop_worker()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(campaigns.router)
app.include_router(campaigns.sources_router)
app.include_router(stats.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "worker": settings.run_worker}


@app.exception_handler(404)
async def spa_fallback(request, exc):
    """Anything that is not /api and not a file falls through to the SPA."""
    if request.url.path.startswith("/api") or not (STATIC_DIR / "index.html").exists():
        return JSONResponse({"detail": getattr(exc, "detail", "Not found")}, status_code=404)
    return FileResponse(STATIC_DIR / "index.html")


if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def index():
    if (STATIC_DIR / "index.html").exists():
        return FileResponse(STATIC_DIR / "index.html")
    raise HTTPException(status_code=404, detail="Frontend not built")
