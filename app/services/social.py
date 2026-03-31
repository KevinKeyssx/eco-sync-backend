"""
Social media digital footprint business logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.reddit_client import RedditClient
from app.schemas import RedditCleanupResponse, RedditItem

logger = logging.getLogger(__name__)


def clean_reddit_history(
    client: RedditClient,
    older_than_days: int = 30,
    limit: int = 100,
) -> RedditCleanupResponse:
    """Find and delete comments older than a certain threshold."""
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=older_than_days)
    
    deleted_items: list[RedditItem] = []
    failed_items: list[str] = []

    logger.info("Scanning up to %d Reddit comments...", limit)
    comments = client.get_old_comments(limit=limit)
    
    for comment in comments:
        created_utc = datetime.fromtimestamp(comment.created_utc, tz=timezone.utc)
        
        # Only delete comments older than the threshold
        if created_utc < threshold:
            subreddit = comment.subreddit.display_name
            text_snippet = comment.body[:30] + "..." if len(comment.body) > 30 else comment.body
            
            logger.debug("Deleting comment on r/%s: %s", subreddit, text_snippet)
            
            success = client.overwrite_and_delete_comment(comment)
            if success:
                deleted_items.append(
                    RedditItem(
                        id=comment.id,
                        subreddit=subreddit,
                        created_at=created_utc,
                        snippet=text_snippet,
                    )
                )
            else:
                failed_items.append(comment.id)

    return RedditCleanupResponse(
        total_scanned=len(comments),
        deleted_count=len(deleted_items),
        failed_count=len(failed_items),
        items=deleted_items,
    )
