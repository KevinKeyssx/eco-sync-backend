"""
GitHub API client — handles authentication, pagination, and rate-limit management.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"


class GitHubAPIError(Exception):
    """Custom exception for GitHub API errors."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"GitHub API error {status_code}: {message}")


class GitHubClient:
    """Lightweight wrapper around the GitHub REST API v3."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError(
                "A GitHub personal access token is required. "
                "Set the GITHUB_TOKEN environment variable."
            )
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "github-inactive-repos-detector/1.0",
            }
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_rate_limit(self, response: requests.Response) -> None:
        """Sleep if we are close to hitting the rate limit."""
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset_ts = response.headers.get("X-RateLimit-Reset")

        if remaining is not None and int(remaining) <= 5 and reset_ts:
            wait_seconds = max(int(reset_ts) - int(time.time()), 0) + 1
            logger.warning(
                "Rate limit almost exhausted (%s remaining). "
                "Sleeping %s seconds until reset…",
                remaining,
                wait_seconds,
            )
            time.sleep(wait_seconds)

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Execute an HTTP request with error handling."""
        response = self._session.request(method, url, **kwargs)

        self._handle_rate_limit(response)

        if response.status_code == 401:
            raise GitHubAPIError(401, "Bad credentials — check your GITHUB_TOKEN.")
        if response.status_code == 403:
            # Could be rate limit or scope issue
            msg = response.json().get("message", "Forbidden")
            raise GitHubAPIError(403, msg)
        if response.status_code == 404:
            raise GitHubAPIError(404, "Resource not found.")
        if not response.ok:
            raise GitHubAPIError(
                response.status_code,
                response.text[:300],
            )

        return response

    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET request, return parsed JSON."""
        return self._request("GET", url, params=params).json()

    def _get_paginated(
        self, url: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Follow ``Link: rel=next`` headers to collect all pages."""
        params = dict(params or {})
        params.setdefault("per_page", 100)
        results: list[dict[str, Any]] = []

        next_url: str | None = url
        while next_url:
            resp = self._request("GET", next_url, params=params)
            data = resp.json()
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)

            # Only pass params on the first request — subsequent URLs from
            # the Link header already contain query parameters.
            params = {}

            next_url = resp.links.get("next", {}).get("url")

        return results

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_repos(self) -> list[dict[str, Any]]:
        """Return **all** repositories for the authenticated user (incl. private)."""
        url = f"{API_BASE}/user/repos"
        repos = self._get_paginated(
            url,
            params={"affiliation": "owner", "sort": "pushed", "direction": "desc"},
        )
        logger.info("Fetched %d repositories from GitHub.", len(repos))
        return repos

    def get_last_commit_date(self, owner: str, repo: str) -> datetime | None:
        """Return the date of the most recent commit on the default branch.

        Returns ``None`` if the repo has no commits (empty repo).
        """
        url = f"{API_BASE}/repos/{owner}/{repo}/commits"
        try:
            data = self._get(url, params={"per_page": 1})
        except GitHubAPIError as exc:
            if exc.status_code == 409:
                # 409 Conflict → empty repository
                return None
            raise

        if not data:
            return None

        date_str: str = data[0]["commit"]["committer"]["date"]
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))

    def get_recent_commits_count(
        self, owner: str, repo: str, since: datetime
    ) -> int:
        """Return the number of commits since *since* on the default branch."""
        url = f"{API_BASE}/repos/{owner}/{repo}/commits"
        try:
            commits = self._get_paginated(
                url,
                params={"since": since.isoformat(), "per_page": 100},
            )
        except GitHubAPIError as exc:
            if exc.status_code == 409:
                return 0
            raise
        return len(commits)

    def get_repo_contents(self, owner: str, repo: str, path: str = "") -> list[dict[str, Any]]:
        """List the contents of a repository path."""
        url = f"{API_BASE}/repos/{owner}/{repo}/contents/{path}"
        try:
            return self._get(url)
        except GitHubAPIError as exc:
            if exc.status_code == 404:
                return []
            raise

    def get_file_content_from_url(self, download_url: str) -> str:
        """Download raw file content from a GitHub download URL."""
        response = self._request("GET", download_url)
        return response.text

    # ------------------------------------------------------------------
    # Repository Management (Action Module)
    # ------------------------------------------------------------------

    def archive_repo(self, owner: str, repo: str) -> dict[str, Any]:
        """Archive a repository."""
        url = f"{API_BASE}/repos/{owner}/{repo}"
        response = self._request("PATCH", url, json={"archived": True})
        return response.json()

    def delete_repo(self, owner: str, repo: str) -> None:
        """Delete a repository. Requires admin:org or delete_repo scope."""
        url = f"{API_BASE}/repos/{owner}/{repo}"
        self._request("DELETE", url)

    # ------------------------------------------------------------------
    # Security/Audit (Action Module)
    # ------------------------------------------------------------------

    def get_user_installations(self) -> list[dict[str, Any]]:
        """List GitHub App installations accessible to the user."""
        url = f"{API_BASE}/user/installations"
        try:
            # We must use a specific Accept header for some Apps APIs
            headers = {"Accept": "application/vnd.github.v3+json"}
            data = self._get_paginated(url)
            # /user/installations returns an object: {"total_count": X, "installations": [...]}
            # Wait, pagination for this endpoint might return the dict on each page.
            # So _get_paginated might not work cleanly if it returns dicts rather than lists.
            # Let's use _get instead since it's usually a small list.
            response = self._get(url)
            return response.get("installations", [])
        except GitHubAPIError as exc:
            logger.warning("Could not fetch user app installations: %s", exc)
            return []

    def get_repo_details(self, owner: str, repo: str) -> dict[str, Any]:
        """Fetch full repository details (including parent fork info)."""
        url = f"{API_BASE}/repos/{owner}/{repo}"
        return self._get(url)

    # ------------------------------------------------------------------
    # Dashboard helpers
    # ------------------------------------------------------------------

    def get_user_profile(self) -> dict[str, Any]:
        """Return the authenticated user's profile."""
        return self._get(f"{API_BASE}/user")

    def get_branches(self, owner: str, repo: str) -> list[dict[str, Any]]:
        """Return the list of branches for a repository."""
        url = f"{API_BASE}/repos/{owner}/{repo}/branches"
        try:
            return self._get_paginated(url)
        except GitHubAPIError as exc:
            if exc.status_code in (404, 409):
                return []
            raise

    def get_recent_commits_details(
        self, owner: str, repo: str, count: int = 5
    ) -> list[dict[str, Any]]:
        """Return the last *count* commits with sha, message, author, and date."""
        url = f"{API_BASE}/repos/{owner}/{repo}/commits"
        try:
            data = self._get(url, params={"per_page": count})
        except GitHubAPIError as exc:
            if exc.status_code in (404, 409):
                return []
            raise
        if not isinstance(data, list):
            return []
        results = []
        for c in data:
            commit_data = c.get("commit", {})
            results.append({
                "sha": c.get("sha", "")[:7],
                "message": commit_data.get("message", "").split("\n")[0][:80],
                "author": commit_data.get("author", {}).get("name", "Unknown"),
                "date": commit_data.get("author", {}).get("date"),
            })
        return results
