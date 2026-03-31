import logging
from typing import Any

import requests
from urllib.parse import urlencode
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import settings

logger = logging.getLogger(__name__)
auth_router = APIRouter()

# Scopes needed for our application
GITHUB_SCOPES = "repo,delete_repo"

@auth_router.get("/login", summary="Initiate GitHub OAuth flow")
def login() -> RedirectResponse:
    """Redirect the user to GitHub to authorize the application."""
    if not settings.github_client_id:
        raise HTTPException(
            status_code=500, detail="GITHUB_CLIENT_ID is not configured."
        )
    url = f"https://github.com/login/oauth/authorize?client_id={settings.github_client_id}&scope={GITHUB_SCOPES}"
    return RedirectResponse(url)


@auth_router.get("/callback", summary="GitHub OAuth callback")
def callback(code: str, request: Request) -> RedirectResponse:
    """
    Exchange the temporary code for an access token.
    The access token is then stored encrypted in the user's secure cookie session.
    """
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(
            status_code=500, detail="OAuth credentials are not configured in .env."
        )

    # Exchange code for access token
    response = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
        },
    )

    if not response.ok:
        logger.error("Failed to exchange OAuth code. Response: %s", response.text)
        raise HTTPException(status_code=400, detail="Failed to exchange OAuth code.")

    data = response.json()
    access_token = data.get("access_token")

    if not access_token:
        error_description = data.get("error_description", "Unknown error")
        logger.error("OAuth error from GitHub: %s", error_description)
        raise HTTPException(status_code=400, detail=f"OAuth login failed: {error_description}")

    # Store token in encrypted session
    request.session["access_token"] = access_token
    logger.info("User successfully authenticated via OAuth.")

    # Redirect to the Svelte frontend (scan/github page)
    return RedirectResponse(url="http://localhost:5173/scan/github?authenticated=true")

@auth_router.get("/logout", summary="Log out the user")
def logout(request: Request) -> RedirectResponse:
    """Clear the session to log out."""
    request.session.clear()
    return RedirectResponse(url="/dashboard")


# ---------------------------------------------------------------------------
# Google OAuth2
# ---------------------------------------------------------------------------
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file"


@auth_router.get("/google/login", summary="Initiate Google OAuth flow")
def google_login() -> RedirectResponse:
    if not settings.google_client_id:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID is not configured.")

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": "http://localhost:8000/auth/google/callback",
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url)


@auth_router.get("/google/callback", summary="Google OAuth callback")
def google_callback(code: str, request: Request) -> RedirectResponse:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth credentials not configured.")

    response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": "http://localhost:8000/auth/google/callback",
        },
    )

    if not response.ok:
        logger.error("Failed to exchange Google OAuth code: %s", response.text)
        raise HTTPException(status_code=400, detail="Failed to exchange Google OAuth code.")

    data = response.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")

    if not access_token:
        raise HTTPException(status_code=400, detail=f"Google OAuth failed: {data.get('error_description', 'Unknown')}")

    request.session["google_access_token"] = access_token
    if refresh_token:
        request.session["google_refresh_token"] = refresh_token
    logger.info("User successfully authenticated via Google OAuth.")

    return RedirectResponse(url="http://localhost:5173/scan/drive?authenticated=true")
