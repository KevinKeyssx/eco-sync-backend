"""
Client for communicating with the Reddit API using PRAW.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import praw
    from praw.exceptions import PRAWException
except ImportError:
    praw = None
    logger.warning("PRAW is not installed. Reddit functionality will be disabled.")

class RedditClientError(Exception):
    """Custom exception for Reddit API errors."""
    pass


class RedditClient:
    """Wrapper to interact with Reddit and perform digital footprint cleanup."""

    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        username: str | None,
        password: str | None,
        user_agent: str = "github-inactive-repos-detector:v1.0 (by /u/YOUR_USERNAME)",
    ) -> None:
        if not praw:
            raise RedditClientError("PRAW module is required for Reddit integration.")
            
        if not all([client_id, client_secret, username, password]):
            raise ValueError(
                "Reddit credentials (client_id, secret, username, password) are "
                "required to initialize the Reddit client."
            )

        try:
            self._reddit = praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                username=username,
                password=password,
                user_agent=user_agent,
            )
            # Verify credentials by fetching the authenticated user
            self.user = self._reddit.user.me()
        except Exception as e:
            raise RedditClientError(f"Failed to authenticate with Reddit: {e}")

    def get_old_comments(self, limit: int = 100) -> list[Any]:
        """Fetch the user's latest comments (up to 1000)."""
        try:
            return list(self.user.comments.new(limit=limit))
        except Exception as e:
            raise RedditClientError(f"Failed to fetch comments: {e}")

    def overwrite_and_delete_comment(self, comment: Any, replacement_text: str = "[DELETED BY SCRIPT]") -> bool:
        """Overwrite the comment body before deleting it.
        
        This thwarts third-party Reddit archival services that capture edit history.
        """
        try:
            comment.edit(replacement_text)
            comment.delete()
            return True
        except Exception as e:
            logger.error("Failed to delete comment %s: %s", comment.id, e)
            return False
