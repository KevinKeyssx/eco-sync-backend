"""
FastAPI application entry-point.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import auth_router
from app.config import settings
from app.routes import router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="EcoSync",
    description=(
        "Analyzes a GitHub account and detects repositories that have been "
        "inactive (no commits) for a configurable number of months.\n\n"
        "Also scans for forgotten accounts on other platforms and checks for compromised credentials.\n\n"
        "And analyzes Google Drive for waste files.\n\n"
        "And analyzes local files for waste files."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — permitir origenes locales para OAuth y Vite
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Integración Segura de Sesiones para almacenar el Token OAuth
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    session_cookie="github_audit_session",
    max_age=86400 * 7,  # 7 days
    same_site="lax",
    https_only=False,  # Set to True on production (HTTPS)
)

app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(router)

# Serve the frontend dashboard
app.mount("/dashboard", StaticFiles(directory="frontend", html=True), name="frontend")


from fastapi.responses import RedirectResponse

@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Redirect to the dashboard."""
    return RedirectResponse(url="/dashboard/")
