"""
OSINT Scanner for username enumeration across multiple web platforms.
Detects potential forgotten accounts.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Dictionary of platforms: name -> (url_template, delete_url, max_co2_grams)
PLATFORMS = {
    "GitHub": ("https://github.com/{}", "https://github.com/settings/admin", 120),
    "Reddit": ("https://www.reddit.com/user/{}", "https://www.reddit.com/prefs/deactivate", 80),
    "Twitter/X": ("https://twitter.com/{}", "https://twitter.com/settings/deactivate", 90),
    "Instagram": ("https://www.instagram.com/{}/", "https://www.instagram.com/accounts/remove/request/permanent/", 150),
    "Pinterest": ("https://www.pinterest.com/{}/", "https://www.pinterest.com/settings/account-settings", 110),
    "Spotify": ("https://open.spotify.com/user/{}", "https://support.spotify.com/close-account/", 60),
    "HackerNews": ("https://news.ycombinator.com/user?id={}", "mailto:hn@ycombinator.com", 10),
    "Patreon": ("https://www.patreon.com/{}", "https://www.patreon.com/settings/account", 40),
    "Vimeo": ("https://vimeo.com/{}", "https://vimeo.com/settings/account", 130),
    "SoundCloud": ("https://soundcloud.com/{}", "https://soundcloud.com/settings/account", 140),
    "Blogger": ("https://{}.blogspot.com", "https://support.google.com/blogger/answer/41387", 30),
    "Medium": ("https://medium.com/@{}", "https://medium.com/me/settings/account", 50),
    "Dev.to": ("https://dev.to/{}", "https://dev.to/settings/account", 20),
    "GitLab": ("https://gitlab.com/{}", "https://gitlab.com/-/profile/account", 115),
    "BitBucket": ("https://bitbucket.org/{}/", "https://bitbucket.org/account/settings/", 100),
    "Wattpad": ("https://www.wattpad.com/user/{}", "https://www.wattpad.com/user_close", 70),
    "Flickr": ("https://www.flickr.com/people/{}/", "https://www.flickr.com/account/delete", 160),
    "DeviantArt": ("https://www.deviantart.com/{}", "https://www.deviantart.com/settings/deactivation", 125),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


async def check_platform(client: httpx.AsyncClient, name: str, username: str, url_template: str, delete_url: str, co2: int) -> dict[str, Any] | None:
    """Check a single platform for the username."""
    url = url_template.format(username)
    try:
        # Some platforms require GET to actually return 404 properly instead of 405 on HEAD
        response = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=5.0)
        
        # 200 means user likely exists.
        # Note: some sites like Instagram might redirect to login (302 -> 200). We ideally want status_code 200 on the literal profile.
        # For a basic OSINT tool, 200 is our standard hit indicator.
        if response.status_code == 200:
            # Basic false positive filter: if the username isn't in the final URL or page content for certain sites, it might be a generic 200
            if "twitter" in url and "Not found" in response.text:
                return None
                
            return {
                "platform": name,
                "profile_url": url,
                "delete_url": delete_url,
                "estimated_co2_grams": co2,
                "status": "found"
            }
            
    except httpx.RequestError as e:
        logger.debug("Error checking %s for %s: %s", name, username, e)
    
    return None


async def scan_username(username: str) -> dict[str, Any]:
    """Asynchronously scan all platforms for the username."""
    logger.info("Starting OSINT scan for username: %s", username)
    found_accounts = []
    
    # We use a single AsyncClient context to reuse connections and be fast
    async with httpx.AsyncClient() as client:
        tasks = []
        for name, data in PLATFORMS.items():
            url_template, delete_url, co2 = data
            tasks.append(check_platform(client, name, username, url_template, delete_url, co2))
            
        results = await asyncio.gather(*tasks)
        
    for res in results:
        if res:
            found_accounts.append(res)
            
    # Calculate CO2 summation
    total_co2 = sum(acc["estimated_co2_grams"] for acc in found_accounts)
    
    # Sort alphabetically by platform name
    found_accounts.sort(key=lambda x: x["platform"])
            
    return {
        "username": username,
        "accounts_found": len(found_accounts),
        "total_co2_grams": total_co2,
        "platforms": found_accounts
    }
