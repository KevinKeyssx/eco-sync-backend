"""
Business logic — determines which repositories are inactive.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.github_client import GitHubClient
from app.scanner import scan_content
from app.schemas import (
    DeadFork,
    DeadForksResponse,
    InactiveRepo,
    InactiveReposResponse,
    RepoScanResult,
    SecretFinding,
    SecretScanResponse,
)

logger = logging.getLogger(__name__)


def _parse_datetime(date_str: str | None) -> datetime | None:
    """Parse an ISO-8601 string into an aware ``datetime``."""
    if not date_str:
        return None
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def _matches_filters(
    repo: dict[str, Any],
    language: str | None,
    visibility: str | None,
) -> bool:
    """Return ``True`` if *repo* passes the optional filters."""
    if language and (repo.get("language") or "").lower() != language.lower():
        return False
    if visibility:
        is_private = repo.get("private", False)
        repo_vis = "private" if is_private else "public"
        if visibility.lower() != repo_vis:
            return False
    return True


def get_inactive_repos(
    client: GitHubClient,
    inactivity_months: int = 6,
    language: str | None = None,
    visibility: str | None = None,
) -> InactiveReposResponse:
    """Analyze all repos and return those deemed inactive.

    **Optimisation**: ``pushed_at`` (available in the repo list payload) is
    checked first.  If it is recent enough we skip the per-repo commits
    request entirely, saving API calls.
    """
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=inactivity_months * 30)

    all_repos = client.get_repos()
    inactive: list[InactiveRepo] = []
    filtered_count = 0

    for repo in all_repos:
        # --- optional filters ---------------------------------------------------
        if not _matches_filters(repo, language, visibility):
            continue
        filtered_count += 1

        owner: str = repo["owner"]["login"]
        name: str = repo["name"]
        is_private: bool = repo.get("private", False)

        # --- fast path: use pushed_at from the list payload ---------------------
        pushed_at = _parse_datetime(repo.get("pushed_at"))
        if pushed_at and pushed_at >= threshold:
            logger.debug("Skipping %s/%s — pushed_at is recent.", owner, name)
            continue

        # --- slow path: query actual last commit date ---------------------------
        last_commit = client.get_last_commit_date(owner, name)

        if last_commit and last_commit >= threshold:
            # pushed_at was stale but the real commit is recent
            continue

        if last_commit:
            days_inactive = (now - last_commit).days
        elif pushed_at:
            days_inactive = (now - pushed_at).days
            last_commit = pushed_at
        else:
            # Repo with no commits and no pushed_at — treat as inactive since creation
            created_at = _parse_datetime(repo.get("created_at"))
            days_inactive = (now - created_at).days if created_at else 0
            last_commit = created_at

        inactive.append(
            InactiveRepo(
                name=name,
                url=repo.get("html_url", f"https://github.com/{owner}/{name}"),
                last_commit_date=last_commit,
                days_inactive=days_inactive,
                language=repo.get("language"),
                visibility="private" if is_private else "public",
            )
        )

    # Sort by most inactive first
    inactive.sort(key=lambda r: r.days_inactive, reverse=True)

    logger.info(
        "Analysis complete: %d/%d repos inactive (threshold: %d months).",
        len(inactive),
        filtered_count,
        inactivity_months,
    )

    return InactiveReposResponse(
        total_repos=filtered_count,
        inactive_count=len(inactive),
        inactivity_threshold_months=inactivity_months,
        repos=inactive,
    )


def scan_repositories_for_secrets(
    client: GitHubClient,
    repo_name: str | None = None,
) -> SecretScanResponse:
    """Scan either a specific repo or all owned repos for secrets.

    **Note**: To avoid excessive API calls, this iterates through the file tree
    and only inspects common text files.
    """
    if repo_name:
        # Get specific repo (only if it belongs to user)
        all_user_repos = client.get_repos()
        repos_to_scan = [r for r in all_user_repos if r["name"].lower() == repo_name.lower()]
        if not repos_to_scan:
            return SecretScanResponse(total_repos_scanned=0, findings_count=0, repos=[])
    else:
        repos_to_scan = client.get_repos()

    scan_results: list[RepoScanResult] = []
    total_findings = 0

    # Extensions we are willing to scan
    TEXT_EXTENSIONS = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".env", ".json", ".yml", ".yaml",
        ".txt", ".md", ".sh", ".bash", ".conf", ".ini", ".cfg", ".xml"
    }

    for repo_data in repos_to_scan:
        owner = repo_data["owner"]["login"]
        r_name = repo_data["name"]
        logger.info("Scanning repo %s/%s for secrets...", owner, r_name)

        repo_findings: list[SecretFinding] = []

        # Simple recursive scan (level 1 & 2 for depth to avoid deep vendor dirs)
        try:
            # We use a BFS to explore files, limiting depth to 2 for performance
            queue: list[tuple[str, int]] = [("", 0)]  # (path, depth)
            
            while queue:
                curr_path, depth = queue.pop(0)
                if depth > 2: continue

                items = client.get_repo_contents(owner, r_name, curr_path)
                if not isinstance(items, list): continue

                for item in items:
                    if item["type"] == "dir":
                        # Skip common large directories
                        if item["name"] in (".git", "node_modules", "venv", "__pycache__"):
                            continue
                        queue.append((item["path"], depth + 1))
                    
                    elif item["type"] == "file":
                        # Check extension
                        ext = "." + item["name"].split(".")[-1].lower() if "." in item["name"] else ""
                        if ext in TEXT_EXTENSIONS or item["name"].startswith(".env"):
                            download_url = item.get("download_url")
                            if not download_url: continue

                            content = client.get_file_content_from_url(download_url)
                            findings = scan_content(content)
                            
                            for f in findings:
                                repo_findings.append(
                                    SecretFinding(
                                        file_path=item["path"],
                                        secret_type=f.secret_type,
                                        line_number=f.line_number
                                    )
                                )

            if repo_findings:
                scan_results.append(RepoScanResult(repo_name=r_name, findings=repo_findings))
                total_findings += len(repo_findings)

        except Exception as e:
            logger.error("Error scanning repo %s: %s", r_name, e)

    return SecretScanResponse(
        total_repos_scanned=len(repos_to_scan),
        findings_count=total_findings,
        repos=scan_results
    )


def get_dead_forks(client: GitHubClient, inactivity_months: int = 6) -> DeadForksResponse:
    """Find repositories that are forks and haven't been updated recently."""
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=inactivity_months * 30)

    all_repos = client.get_repos()
    forks = [r for r in all_repos if r.get("fork")]
    
    dead_forks: list[DeadFork] = []

    for repo in forks:
        owner = repo["owner"]["login"]
        name = repo["name"]

        # Fast path
        pushed_at = _parse_datetime(repo.get("pushed_at"))
        if pushed_at and pushed_at >= threshold:
            continue

        # Slow path
        last_commit = client.get_last_commit_date(owner, name)
        if last_commit and last_commit >= threshold:
            continue
            
        # Get parent info
        repo_details = client.get_repo_details(owner, name)
        parent = repo_details.get("parent", {})
        
        dead_forks.append(
            DeadFork(
                name=name,
                url=repo.get("html_url", f"https://github.com/{owner}/{name}"),
                parent_name=parent.get("full_name", "Unknown Parent"),
                parent_url=parent.get("html_url", ""),
                last_commit_date=last_commit or pushed_at
            )
        )

    return DeadForksResponse(
        total_forks=len(forks),
        dead_forks_count=len(dead_forks),
        forks=dead_forks
    )
