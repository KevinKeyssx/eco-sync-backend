"""
Client for the HaveIBeenPwned API to detect data leaks.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

HIBP_API_BASE = "https://haveibeenpwned.com/api/v3"

class HIBPClientError(Exception):
    """Custom exception for HaveIBeenPwned API errors."""
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"HIBP API error {status_code}: {message}")


class HIBPClient:
    """Wrapper around the HaveIBeenPwned REST API."""

    def __init__(self, api_key: str | None = None) -> None:
        # Note: The HIBP API requires an API key for email searches now.
        # If not provided, the API will likely return a 401.
        self._session = requests.Session()
        headers = {
            "User-Agent": "github-inactive-repos-detector/1.0",
        }
        if api_key:
            headers["hibp-api-key"] = api_key
        self._session.headers.update(headers)

    def _request(self, method: str, url: str) -> requests.Response:
        """Execute an HTTP request with error handling for HIBP."""
        response = self._session.request(method, url)

        if response.status_code == 401:
            raise HIBPClientError(401, "Unauthorized — a valid HIBP API key is required.")
        if response.status_code == 403:
            raise HIBPClientError(403, "Forbidden — check your request or User-Agent.")
        if response.status_code == 404:
             # 404 means the account was NOT found in any breaches (this is good!)
            return response
        if response.status_code == 429:
             raise HIBPClientError(429, "Rate limit exceeded. Wait before trying again.")
        if not response.ok:
            raise HIBPClientError(response.status_code, response.text[:300])

        return response

    def get_breaches_for_account(self, account: str) -> list[dict[str, Any]]:
        """Return a list of data breaches the account was found in.
        
        Returns an empty list if the account is clean (HTTP 404).
        """
        url = f"{HIBP_API_BASE}/breachedaccount/{account}?truncateResponse=false"
        response = self._request("GET", url)
        
        if response.status_code == 404:
            return []
            
        return response.json()
