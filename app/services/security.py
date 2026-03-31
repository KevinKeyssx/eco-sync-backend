"""
Security audit module — scans SSH keys, GPG keys, and Gists for digital footprint auditing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.github_client import GitHubClient
from app.pwned_client import HIBPClient, HIBPClientError
from app.schemas import DataLeakBreach, DataLeakResponse, InstalledApp, SecurityAuditResponse, SSHKey

logger = logging.getLogger(__name__)


def _parse_datetime(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def generate_security_audit(
    client: GitHubClient,
    unused_months_threshold: int = 6,
) -> SecurityAuditResponse:
    """Analyze the user's account for security footprint items."""
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=unused_months_threshold * 30)

    # 1. Check SSH Keys
    logger.info("Auditing SSH keys...")
    # Using generic get to fetch keys (requires appropriate scopes)
    try:
        keys_data = client._get("https://api.github.com/user/keys")
    except Exception as e:
        logger.warning("Could not fetch SSH keys. Ensure your token has 'read:public_key' or 'admin:public_key' scope. %s", e)
        keys_data = []

    old_keys: list[SSHKey] = []
    
    for key in keys_data:
        # We need to query each key individually to get its 'last_used' attribute
        try:
            key_details = client._get(f"https://api.github.com/user/keys/{key['id']}")
            created_at = _parse_datetime(key_details.get("created_at"))
            # 'last_used' may be None or omitted
            last_used = _parse_datetime(key_details.get("last_used"))

            # Consider old if: 
            # - used but a long time ago
            # - never used, but created a long time ago
            is_old = False
            if last_used and last_used <= threshold:
                is_old = True
            elif not last_used and created_at and created_at <= threshold:
                is_old = True

            if is_old:
                old_keys.append(
                    SSHKey(
                        id=key_details["id"],
                        title=key_details["title"],
                        created_at=created_at,
                        last_used=last_used,
                    )
                )
        except Exception as e:
            logger.error("Error fetching details for SSH key %s: %s", key["id"], e)

    # 2. Check Public Gists
    logger.info("Auditing Gists...")
    try:
        gists_data = client._get_paginated("https://api.github.com/gists")
        public_gists = [g for g in gists_data if g.get("public") is True]
    except Exception as e:
        logger.warning("Could not fetch gists. %s", e)
        public_gists = []

    # 3. Check App Installations
    logger.info("Auditing Installed Apps...")
    try:
        installations_data = client.get_user_installations()
        installed_apps = []
        for app in installations_data:
            installed_apps.append(
                InstalledApp(
                    id=app["id"],
                    app_slug=app.get("app_slug", "unknown"),
                    repository_selection=app.get("repository_selection", "unknown"),
                    permissions=app.get("permissions", {})
                )
            )
    except Exception as e:
        logger.warning("Could not fetch app installations: %s", e)
        installed_apps = []

    return SecurityAuditResponse(
        old_ssh_keys=old_keys,
        public_gists_count=len(public_gists),
        installed_apps=installed_apps,
    )

def check_email_for_leaks(
    email: str,
    api_key: str | None = None,
) -> DataLeakResponse:
    """Check HaveIBeenPwned for an email and return a list of breaches."""
    client = HIBPClient(api_key=api_key)
    
    breaches_data = client.get_breaches_for_account(email)
    
    parsed_breaches = []
    for breach in breaches_data:
        parsed_breaches.append(
            DataLeakBreach(
                name=breach.get("Name", "Unknown"),
                title=breach.get("Title", "Unknown Breach"),
                domain=breach.get("Domain", "unknown.com"),
                breach_date=breach.get("BreachDate", "Unknown"),
                description=breach.get("Description", "No description provided.")
            )
        )
        
    return DataLeakResponse(
        account=email,
        is_pwned=len(parsed_breaches) > 0,
        breaches=parsed_breaches
    )
