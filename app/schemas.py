"""
Pydantic schemas for API request validation and response serialization.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class InactiveRepo(BaseModel):
    """Represents a single inactive repository."""

    name: str = Field(..., description="Repository name")
    url: str = Field(..., description="Repository URL on GitHub")
    last_commit_date: datetime | None = Field(
        None, description="Date/time of the last commit (UTC)"
    )
    days_inactive: int = Field(
        ..., description="Number of days since the last commit"
    )
    language: str | None = Field(None, description="Primary language of the repo")
    visibility: str = Field(
        ..., description="Visibility of the repo (public / private)"
    )
    is_archived: bool = Field(False, description="Whether the repository is archived")

    model_config = {"json_schema_extra": {
        "example": {
            "name": "old-project",
            "url": "https://github.com/user/old-project",
            "last_commit_date": "2024-03-15T10:30:00Z",
            "days_inactive": 371,
            "language": "JavaScript",
            "visibility": "public",
        }
    }}


class InactiveReposResponse(BaseModel):
    """Aggregated response containing all inactive repositories."""

    total_repos: int = Field(..., description="Total repositories analyzed")
    inactive_count: int = Field(..., description="Number of inactive repositories")
    inactivity_threshold_months: int = Field(
        ..., description="Inactivity threshold used (in months)"
    )
    repos: list[InactiveRepo] = Field(
        default_factory=list, description="List of inactive repositories"
    )

    model_config = {"json_schema_extra": {
        "example": {
            "total_repos": 42,
            "inactive_count": 2,
            "inactivity_threshold_months": 6,
            "repos": [
                {
                    "name": "old-project",
                    "url": "https://github.com/user/old-project",
                    "last_commit_date": "2024-03-15T10:30:00Z",
                    "days_inactive": 371,
                    "language": "JavaScript",
                    "visibility": "public",
                }
            ],
        }
    }}


class SecretFinding(BaseModel):
    """A sensitive information finding in a file."""

    file_path: str = Field(..., description="Path to the file relative to repo root")
    secret_type: str = Field(..., description="Type of secret found (e.g. AWS Key)")
    line_number: int = Field(..., description="Line number where the secret was found")


class RepoScanResult(BaseModel):
    """Scan result for a single repository."""

    repo_name: str = Field(..., description="Name of the repository")
    findings: list[SecretFinding] = Field(default_factory=list)


class SecretScanResponse(BaseModel):
    """Aggregated response for secret scanning across multiple repos."""

    total_repos_scanned: int = Field(..., description="Number of repositories scanned")
    findings_count: int = Field(..., description="Total number of secrets found")
    repos: list[RepoScanResult] = Field(default_factory=list)

    model_config = {"json_schema_extra": {
        "example": {
            "total_repos_scanned": 1,
            "findings_count": 1,
            "repos": [
                {
                    "repo_name": "my-cool-app",
                    "findings": [
                        {
                            "file_path": ".env",
                            "secret_type": "GitHub Personal Access Token",
                            "line_number": 5
                        }
                    ]
                }
            ]
        }
    }}

class RepoActionRequest(BaseModel):
    """Request payload for repository management actions."""
    repo_name: str = Field(..., description="Name of the repository to act upon")
    confirm: bool = Field(False, description="Must be true to confirm deletion")

class ActionResponse(BaseModel):
    """Generic response for an action."""
    status: str
    message: str
    repo_name: str


class BulkDeleteRequest(BaseModel):
    """Request payload for bulk repository deletion.

    Supports two modes:
    - Manual: provide a list of 'repo_names' to delete specific repos.
    - Automatic: set 'delete_all_candidates=True' to delete ALL inactive/fork
      candidates (the backend decides which repos qualify).

    In both cases 'confirm' MUST be True — this is the "big alert" confirmation.
    """
    repo_names: list[str] = Field(
        default_factory=list,
        description="Explicit list of repository names to delete (manual mode).",
    )
    delete_all_candidates: bool = Field(
        False,
        description="If True, ignore repo_names and delete every candidate repo automatically.",
    )
    confirm: bool = Field(
        False,
        description="Must be True to execute. Acts as the 'big alert' confirmation gate.",
    )


class BulkDeleteResult(BaseModel):
    """Result for a single repo in a bulk operation."""
    repo_name: str
    status: str  # "deleted" | "failed"
    detail: str | None = None


class BulkDeleteResponse(BaseModel):
    """Response for a bulk delete operation."""
    mode: str  # "manual" | "automatic"
    total_requested: int
    deleted_count: int
    failed_count: int
    results: list[BulkDeleteResult] = Field(default_factory=list)


class SSHKey(BaseModel):
    """Represents a GitHub SSH key."""
    id: int
    title: str
    created_at: datetime | None = None
    last_used: datetime | None = None

class InstalledApp(BaseModel):
    """Represents an installed GitHub App."""
    id: int
    app_slug: str
    repository_selection: str
    permissions: dict[str, str] = Field(default_factory=dict)

class SecurityAuditResponse(BaseModel):
    """Response containing security audit information."""
    old_ssh_keys: list[SSHKey] = Field(
        default_factory=list, 
        description="SSH keys that haven't been used recently or at all."
    )
    public_gists_count: int = Field(0, description="Number of public gists the user has.")
    installed_apps: list[InstalledApp] = Field(default_factory=list, description="GitHub Apps installed on the user account")

class DataLeakBreach(BaseModel):
    """Information about a specific data breach."""
    name: str = Field(..., description="Name of the breach")
    title: str = Field(..., description="Title of the breach")
    domain: str = Field(..., description="Domain of the breached service")
    breach_date: str = Field(..., description="Date the breach occurred")
    description: str = Field(..., description="Description of the breach (HTML)")

class DataLeakResponse(BaseModel):
    """Response containing data leak findings for an account."""
    account: str = Field(..., description="The account (email) that was checked")
    is_pwned: bool = Field(..., description="True if the account was found in any breaches")
    breaches: list[DataLeakBreach] = Field(default_factory=list, description="List of breaches the account was found in")

class DeadFork(BaseModel):
    """Represents a fork that hasn't been updated recently."""
    name: str = Field(..., description="Repository name")
    url: str = Field(..., description="Repository URL on GitHub")
    parent_name: str = Field(..., description="Name of the parent repository")
    parent_url: str = Field(..., description="URL of the parent repository")
    last_commit_date: datetime | None = Field(None, description="Date/time of the last commit (UTC)")

class DeadForksResponse(BaseModel):
    """Response containing dead forks."""
    total_forks: int = Field(..., description="Total number of forks found")
    dead_forks_count: int = Field(..., description="Number of dead forks")
    forks: list[DeadFork] = Field(default_factory=list, description="List of dead forks")

class RedditItem(BaseModel):
    """Information about a deleted Reddit comment."""
    id: str = Field(..., description="The ID of the comment")
    subreddit: str = Field(..., description="The subreddit where the comment was posted")
    created_at: datetime = Field(..., description="The date the comment was posted")
    snippet: str = Field(..., description="A snippet of the text that was deleted")

class RedditCleanupResponse(BaseModel):
    """Response containing Reddit cleanup results."""
    total_scanned: int = Field(..., description="Total number of comments scanned")
    deleted_count: int = Field(..., description="Number of comments successfully deleted")
    failed_count: int = Field(..., description="Number of comments that failed to delete")    
    items: list[RedditItem] = Field(default_factory=list, description="List of deleted items")


# ---------------------------------------------------------------------------
# Dashboard schemas
# ---------------------------------------------------------------------------

class CommitSummary(BaseModel):
    """Short summary of a single commit."""
    sha: str
    message: str
    author: str
    date: datetime | None = None

class RepoDetail(BaseModel):
    """Enriched repository detail for the dashboard."""
    name: str
    url: str
    description: str | None = None
    language: str | None = None
    visibility: str
    is_fork: bool = False
    is_archived: bool = False
    stars: int = 0
    forks_count: int = 0
    open_issues: int = 0
    size_kb: int = 0
    default_branch: str = "main"
    topics: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    pushed_at: datetime | None = None
    last_commit_date: datetime | None = None
    days_inactive: int = 0
    branches_count: int = 0
    recent_commits: list[CommitSummary] = Field(default_factory=list)

class UserProfile(BaseModel):
    """Authenticated GitHub user profile."""
    login: str
    name: str | None = None
    avatar_url: str
    html_url: str
    public_repos: int = 0
    followers: int = 0
    following: int = 0
    bio: str | None = None

class ReposOverviewResponse(BaseModel):
    """Dashboard overview with user profile and all repos."""
    user: UserProfile
    total_repos: int
    repos: list[RepoDetail] = Field(default_factory=list)
