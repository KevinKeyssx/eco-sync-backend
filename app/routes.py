"""
FastAPI route definitions.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from app.audit_logger import log_deletion
from app.config import settings
from app.github_client import GitHubAPIError, GitHubClient
from app.google_client import GoogleDriveClient
from app.local_scanner import delete_local_files, get_directory_sizes, scan_local_paths
from app.osint_scanner import scan_username
from app.pwned_client import HIBPClientError
from app.reddit_client import RedditClient, RedditClientError
from app.schemas import (
    ActionResponse,
    BulkDeleteRequest,
    BulkDeleteResponse,
    BulkDeleteResult,
    CommitSummary,
    DataLeakResponse,
    DeadForksResponse,
    InactiveReposResponse,
    RedditCleanupResponse,
    RepoActionRequest,
    RepoDetail,
    ReposOverviewResponse,
    SecurityAuditResponse,
    SecretScanResponse,
    UserProfile,
)
from app.services.repos import get_dead_forks, get_inactive_repos, scan_repositories_for_secrets
from app.services.security import check_email_for_leaks, generate_security_audit
from app.services.social import clean_reddit_history

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/inactive-repos",
    response_model=InactiveReposResponse,
    summary="List inactive GitHub repositories",
    description=(
        "Analyzes all repositories of the authenticated GitHub user and "
        "returns those with no commits in the last N months."
    ),
)
def list_inactive_repos(
    request: Request,
    months: Annotated[
        int | None,
        Query(
            ge=1,
            le=120,
            description="Override the inactivity threshold (months). Defaults to env INACTIVITY_MONTHS.",
        ),
    ] = None,
    language: Annotated[
        str | None,
        Query(description="Filter by primary language (e.g. Python, JavaScript)."),
    ] = None,
    visibility: Annotated[
        str | None,
        Query(
            pattern="^(public|private)$",
            description="Filter by visibility: 'public' or 'private'.",
        ),
    ] = None,
) -> InactiveReposResponse:
    """Return a list of inactive repositories."""
    token = request.session.get("access_token")
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized. Please login via /auth/login first.",
        )

    threshold = months if months is not None else settings.inactivity_months

    try:
        client = GitHubClient(token)
        result = get_inactive_repos(
            client,
            inactivity_months=threshold,
            language=language,
            visibility=visibility,
        )
    except GitHubAPIError as exc:
        logger.error("GitHub API error: %s", exc)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error while fetching repos.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return result


@router.get(
    "/scan-secrets",
    response_model=SecretScanResponse,
    summary="Scan repositories for secrets",
    description=(
        "Analyzes a specific repository or all owned repositories to find "
        "sensitive information like API keys, tokens, and secrets."
    ),
)
def list_secrets(
    request: Request,
    repo_name: Annotated[
        str | None,
        Query(description="Name of the repository to scan. If omitted, all owned repos are scanned."),
    ] = None,
) -> SecretScanResponse:
    """Return a list of sensitive information findings."""
    token = request.session.get("access_token")
    if not token:
        raise HTTPException(
            status_code=401, detail="Unauthorized. Please login via /auth/login first."
        )

    try:
        client = GitHubClient(token)
        result = scan_repositories_for_secrets(client, repo_name=repo_name)
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error while scanning for secrets.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return result


@router.post(
    "/manage-repo",
    response_model=ActionResponse,
    summary="Archive or delete a repository",
)
def manage_repo(
    request_data: RepoActionRequest,
    action: Annotated[str, Query(pattern="^(archive|delete)$")],
    request: Request,
) -> ActionResponse:
    token = request.session.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized.")

    try:
        client = GitHubClient(token)
        # Check if repo belongs to user first by fetching it (simplification)
        user = client._get("https://api.github.com/user")
        owner = user.get("login")

        if action == "archive":
            client.archive_repo(owner, request_data.repo_name)
            return ActionResponse(
                status="success",
                message="Repository archived successfully.",
                repo_name=request_data.repo_name,
            )
        elif action == "delete":
            if not request_data.confirm:
                raise HTTPException(
                    status_code=400,
                    detail="Delete action requires 'confirm=True' in the payload."
                )
            client.delete_repo(owner, request_data.repo_name)
            
            # Loggea este borrado con el logger de auditoría
            log_deletion(owner, request_data.repo_name)

            return ActionResponse(
                status="success",
                message="Repository deleted successfully.",
                repo_name=request_data.repo_name,
            )

    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post(
    "/bulk-delete",
    response_model=BulkDeleteResponse,
    summary="Bulk delete repositories (manual or automatic)",
    description=(
        "Two modes:\n"
        "- **Manual**: provide a list of repo_names to delete.\n"
        "- **Automático**: set delete_all_candidates=True to delete all "
        "inactive forks automatically.\n\n"
        "⚠️ BOTH modes require confirm=True as the big safety gate."
    ),
)
def bulk_delete(
    payload: BulkDeleteRequest,
    request: Request,
) -> BulkDeleteResponse:
    # --- Auth check ---
    token = request.session.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized.")

    # --- Confirmation gate (the "big alert") ---
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "⚠️ ATENCIÓN: Esta acción es IRREVERSIBLE. "
                "Debes enviar confirm=true para ejecutar el borrado."
            ),
        )

    try:
        client = GitHubClient(token)
        user_data = client._get("https://api.github.com/user")
        owner = user_data.get("login")

        # Decide which repos to target
        if payload.delete_all_candidates:
            # Automatic mode: find all dead forks
            mode = "automatic"
            dead_forks_resp = get_dead_forks(
                client, inactivity_months=settings.inactivity_months
            )
            target_names = [f.name for f in dead_forks_resp.forks]
        else:
            # Manual mode: use the explicit list
            mode = "manual"
            target_names = payload.repo_names

        if not target_names:
            return BulkDeleteResponse(
                mode=mode,
                total_requested=0,
                deleted_count=0,
                failed_count=0,
                results=[],
            )

        results: list[BulkDeleteResult] = []
        deleted = 0
        failed = 0

        for repo_name in target_names:
            try:
                client.delete_repo(owner, repo_name)
                log_deletion(owner, repo_name, status="SUCCESS")
                results.append(BulkDeleteResult(
                    repo_name=repo_name, status="deleted"
                ))
                deleted += 1
            except Exception as exc:
                log_deletion(owner, repo_name, status=f"FAILED: {exc}")
                results.append(BulkDeleteResult(
                    repo_name=repo_name, status="failed", detail=str(exc)
                ))
                failed += 1

        return BulkDeleteResponse(
            mode=mode,
            total_requested=len(target_names),
            deleted_count=deleted,
            failed_count=failed,
            results=results,
        )

    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during bulk delete.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/account-audit",
    response_model=SecurityAuditResponse,
    summary="Security footprint audit (SSH keys, Gists, OAuth Apps)",
)
def account_audit(request: Request) -> SecurityAuditResponse:
    token = request.session.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized.")

    try:
        client = GitHubClient(token)
        result = generate_security_audit(client)
        return result
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get(
    "/dead-forks",
    response_model=DeadForksResponse,
    summary="List inactive forks",
    description="Analyzes repositories that are forks and checks if they have been updated recently.",
)
def list_dead_forks(
    request: Request,
    months: Annotated[
        int | None,
        Query(description="Override the inactivity threshold (months)."),
    ] = None,
) -> DeadForksResponse:
    token = request.session.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized.")

    threshold = months if months is not None else settings.inactivity_months

    try:
        client = GitHubClient(token)
        result = get_dead_forks(client, inactivity_months=threshold)
        return result
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error while fetching dead forks.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/check-leaks",
    response_model=DataLeakResponse,
    summary="Check if an email was involved in known data breaches",
)
def check_leaks(
    email: Annotated[
        str,
        Query(description="The email address to check against HaveIBeenPwned API"),
    ],
) -> DataLeakResponse:
    # HIBP API Key is theoretically optional for testing mock scenarios,
    # but required by the actual API.
    try:
        result = check_email_for_leaks(email=email, api_key=settings.hibp_api_key)
        return result
    except HIBPClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error while checking for data leaks.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/clean-reddit",
    response_model=RedditCleanupResponse,
    summary="Scrape and overwrite old Reddit comments",
    description="Finds comments older than X days, overwrites them with random text, and then deletes them permanently.",
)
def clean_reddit(
    older_than_days: Annotated[
        int,
        Query(ge=1, description="Delete comments older than this many days"),
    ] = 30,
) -> RedditCleanupResponse:
    if not all([
        settings.reddit_client_id,
        settings.reddit_client_secret,
        settings.reddit_username,
        settings.reddit_password
    ]):
        raise HTTPException(status_code=500, detail="Reddit credentials are not configured in .env")

    try:
        client = RedditClient(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            username=settings.reddit_username,
            password=settings.reddit_password,
        )
        return clean_reddit_history(client, older_than_days=older_than_days)
    except RedditClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during Reddit cleanup.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/repos",
    response_model=ReposOverviewResponse,
    summary="Enriched repo list for the dashboard",
    description="Returns all repositories with description, branches, recent commits, stars, and user profile.",
)
def repos_overview(request: Request) -> ReposOverviewResponse:
    """Return enriched repository data for the dashboard."""
    token = request.session.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized. Please login via /auth/login.")

    try:
        client = GitHubClient(token)
        from datetime import datetime, timezone

        # 1. User profile
        profile_data = client.get_user_profile()
        user = UserProfile(
            login=profile_data["login"],
            name=profile_data.get("name"),
            avatar_url=profile_data["avatar_url"],
            html_url=profile_data["html_url"],
            public_repos=profile_data.get("public_repos", 0),
            followers=profile_data.get("followers", 0),
            following=profile_data.get("following", 0),
            bio=profile_data.get("bio"),
        )

        # 2. All repos
        all_repos = client.get_repos()
        now = datetime.now(timezone.utc)
        enriched: list[RepoDetail] = []

        for repo in all_repos:
            owner = repo["owner"]["login"]
            name = repo["name"]
            is_private = repo.get("private", False)

            # Branches count
            branches = client.get_branches(owner, name)

            # Recent commits
            raw_commits = client.get_recent_commits_details(owner, name, count=5)
            commits = [
                CommitSummary(
                    sha=c["sha"],
                    message=c["message"],
                    author=c["author"],
                    date=datetime.fromisoformat(c["date"].replace("Z", "+00:00")) if c.get("date") else None,
                )
                for c in raw_commits
            ]

            # Last commit date & days inactive
            last_commit_dt = commits[0].date if commits else None
            pushed_at_str = repo.get("pushed_at")
            pushed_at_dt = datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00")) if pushed_at_str else None
            effective_date = last_commit_dt or pushed_at_dt
            days_inactive = (now - effective_date).days if effective_date else 0

            created_str = repo.get("created_at")
            created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00")) if created_str else None

            enriched.append(
                RepoDetail(
                    name=name,
                    url=repo.get("html_url", ""),
                    description=repo.get("description"),
                    language=repo.get("language"),
                    visibility="private" if is_private else "public",
                    is_fork=repo.get("fork", False),
                    is_archived=repo.get("archived", False),
                    stars=repo.get("stargazers_count", 0),
                    forks_count=repo.get("forks_count", 0),
                    open_issues=repo.get("open_issues_count", 0),
                    size_kb=repo.get("size", 0),
                    default_branch=repo.get("default_branch", "main"),
                    topics=repo.get("topics", []),
                    created_at=created_dt,
                    pushed_at=pushed_at_dt,
                    last_commit_date=last_commit_dt,
                    days_inactive=days_inactive,
                    branches_count=len(branches),
                    recent_commits=commits,
                )
            )

        return ReposOverviewResponse(
            user=user,
            total_repos=len(enriched),
            repos=enriched,
        )

    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error building repos overview.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Google Drive endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/drive/scan",
    summary="Scan Google Drive for waste files",
    description="Analyzes user's Google Drive for duplicates, large files, old files, and temp files.",
)
def drive_scan(request: Request) -> dict:
    token = request.session.get("google_access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated with Google. Use /auth/google/login.")

    try:
        client = GoogleDriveClient(token)
        result = client.scan_for_waste()
        return result
    except Exception as exc:
        logger.exception("Error scanning Google Drive.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/drive/delete",
    summary="Delete (trash) selected Drive files",
)
def drive_delete(request: Request, file_ids: list[str]) -> dict:
    token = request.session.get("google_access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated with Google.")

    client = GoogleDriveClient(token)
    deleted = 0
    failed = 0
    for fid in file_ids:
        try:
            client.delete_file(fid)
            deleted += 1
        except Exception as exc:
            logger.warning("Failed to trash file %s: %s", fid, exc)
            failed += 1

    return {"deleted": deleted, "failed": failed, "total": len(file_ids)}


# ---------------------------------------------------------------------------
# Local Storage endpoints
# ---------------------------------------------------------------------------
from pydantic import BaseModel

class LocalScanRequest(BaseModel):
    paths: list[str] = []
    full_scan: bool = False
    min_size_mb: int = 100
    min_months_old: int = 12
    include_installers: bool = True
    include_temps: bool = True
    include_cache: bool = True

class LocalDeleteRequest(BaseModel):
    files: list[str]
    permanent: bool = False

@router.get(
    "/local/directories",
    summary="Preview major local directories",
    description="Returns sizes of key local directories to help user select what to scan.",
)
def local_directories() -> dict:
    try:
        results = get_directory_sizes()
        return {"directories": results}
    except Exception as exc:
        logger.exception("Error checking local directories")
        raise HTTPException(status_code=500, detail=str(exc))

@router.post(
    "/local/scan",
    summary="Deep scan local storage",
    description="Scans the provided paths for waste files. If full_scan is True, scans system defaults + user home.",
)
def local_scan(req: LocalScanRequest) -> dict:
    from app.local_scanner import get_default_directories
    paths_to_scan = req.paths
    if req.full_scan or not paths_to_scan:
        paths_to_scan = list(get_default_directories().values())
        
    try:
        results = scan_local_paths(paths_to_scan, config=req)
        return results
    except Exception as exc:
        logger.exception("Error scanning local storage")
        raise HTTPException(status_code=500, detail=str(exc))

@router.post(
    "/local/delete",
    summary="Delete local files",
    description="Deletes local files either permanently or moves them to recycle bin.",
)
def local_delete(req: LocalDeleteRequest) -> dict:
    if not req.files:
        raise HTTPException(status_code=400, detail="No files provided to delete.")
        
    try:
        result = delete_local_files(req.files, permanent=req.permanent)
        return result
    except Exception as exc:
        logger.exception("Error deleting local files")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# OSINT Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/osint/scan",
    summary="Scan internet for phantom accounts",
    description="Uses async OSINT enumeration to find forgotten accounts across platforms.",
)
async def osint_scan(username: str) -> dict:
    if not username or len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters long.")
        
    try:
        results = await scan_username(username)
        return results
    except Exception as exc:
        logger.exception("Error executing OSINT scan")
        raise HTTPException(status_code=500, detail=str(exc))


