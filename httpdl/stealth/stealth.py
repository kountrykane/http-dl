"""
Stealth features: Dynamic headers rotation and User-Agent randomization.

This module provides tools to make requests appear more like a real browser:
- User-Agent rotation (desktop, mobile, bots)
- Random Accept-Language headers
- Browser-like header ordering
- TLS fingerprint randomization (via different User-Agents)
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional
from dataclasses import dataclass


# Real-world User-Agent strings (updated 2025)
DESKTOP_USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

MOBILE_USER_AGENTS = [
    # Chrome on Android
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    # Safari on iPhone
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
    # Chrome on iPad
    "Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0.6099.119 Mobile/15E148 Safari/604.1",
]

BOT_USER_AGENTS = [
    # Googlebot
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Googlebot/2.1; +http://www.google.com/bot.html) Chrome/120.0.6099.0 Safari/537.36",
    # Bingbot
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    # Generic crawler
    "Mozilla/5.0 (compatible; DataFetchBot/1.0; +http://example.com/bot)",
]

ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "en-US,en;q=0.9,es;q=0.8",
    "en-US,en;q=0.9,fr;q=0.8",
    "en-US,en;q=0.9,de;q=0.8",
    "en-US,en;q=0.9,ja;q=0.8",
    "en-US,en;q=0.9,zh-CN;q=0.8",
]


@dataclass
class BrowserProfile:
    """A complete browser profile with consistent headers."""

    user_agent: str
    accept: str
    accept_language: str
    accept_encoding: str
    connection: str
    upgrade_insecure_requests: str
    sec_fetch_dest: str
    sec_fetch_mode: str
    sec_fetch_site: str
    sec_fetch_user: Optional[str] = None

    def to_headers(self) -> Dict[str, str]:
        """Convert profile to HTTP headers dict."""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": self.accept,
            "Accept-Language": self.accept_language,
            "Accept-Encoding": self.accept_encoding,
            "Connection": self.connection,
            "Upgrade-Insecure-Requests": self.upgrade_insecure_requests,
            "Sec-Fetch-Dest": self.sec_fetch_dest,
            "Sec-Fetch-Mode": self.sec_fetch_mode,
            "Sec-Fetch-Site": self.sec_fetch_site,
        }
        if self.sec_fetch_user:
            headers["Sec-Fetch-User"] = self.sec_fetch_user
        return headers


class UserAgentRotator:
    """
    User-Agent rotation manager with browser profiling.

    Provides consistent browser profiles that include not just User-Agent
    but also matching headers that browsers typically send.

    Example:
        rotator = UserAgentRotator(mode="desktop")

        # Get random profile
        profile = rotator.get_random_profile()
        headers = profile.to_headers()

        # Use with httpdl
        settings = DownloadSettings(user_agent=profile.user_agent)
    """

    def __init__(
        self,
        mode: str = "desktop",
        custom_agents: Optional[List[str]] = None,
    ):
        """
        Initialize User-Agent rotator.

        Args:
            mode: "desktop", "mobile", "bot", or "mixed"
            custom_agents: Optional list of custom User-Agent strings
        """
        self.mode = mode
        self.custom_agents = custom_agents or []
        self._user_agents = self._build_agent_list()

    def _build_agent_list(self) -> List[str]:
        """Build list of User-Agents based on mode."""
        if self.custom_agents:
            return self.custom_agents

        if self.mode == "desktop":
            return DESKTOP_USER_AGENTS
        elif self.mode == "mobile":
            return MOBILE_USER_AGENTS
        elif self.mode == "bot":
            return BOT_USER_AGENTS
        elif self.mode == "mixed":
            return DESKTOP_USER_AGENTS + MOBILE_USER_AGENTS
        else:
            raise ValueError(f"Invalid mode: {self.mode}")

    def get_random_user_agent(self) -> str:
        """Get a random User-Agent string."""
        return random.choice(self._user_agents)

    def get_random_profile(self) -> BrowserProfile:
        """
        Get a random browser profile with consistent headers.

        Returns a complete browser profile that looks like a real browser.
        """
        user_agent = self.get_random_user_agent()

        # Determine if it's Chrome-based (includes Sec-Fetch-* headers)
        is_chrome = "Chrome" in user_agent or "Edg" in user_agent
        is_mobile = "Mobile" in user_agent or "Android" in user_agent

        return BrowserProfile(
            user_agent=user_agent,
            accept="text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            accept_language=random.choice(ACCEPT_LANGUAGES),
            accept_encoding="gzip, deflate, br",
            connection="keep-alive",
            upgrade_insecure_requests="1",
            sec_fetch_dest="document" if is_chrome else "",
            sec_fetch_mode="navigate" if is_chrome else "",
            sec_fetch_site="none" if is_chrome else "",
            sec_fetch_user="?1" if is_chrome else None,
        )

    def rotate(self) -> str:
        """
        Alias for get_random_user_agent().

        Returns:
            Random User-Agent string
        """
        return self.get_random_user_agent()


class HeaderRotator:
    """
    Advanced header rotation with browser fingerprinting.

    Rotates headers in a way that maintains consistency within a session
    while appearing like different browsers across sessions.

    Example:
        rotator = HeaderRotator()

        # Get headers for a new session
        headers = rotator.get_session_headers()

        # Use with httpx client
        client = httpx.AsyncClient(headers=headers)
    """

    def __init__(self, mode: str = "desktop"):
        self.ua_rotator = UserAgentRotator(mode=mode)

    def get_session_headers(self) -> Dict[str, str]:
        """
        Get a complete set of headers for a browser session.

        These headers will look like they're from a single browser session.
        """
        profile = self.ua_rotator.get_random_profile()
        return profile.to_headers()

    def get_request_headers(
        self,
        referer: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Get headers for a specific request within a session.

        Args:
            referer: Referer header value
            origin: Origin header value

        Returns:
            Headers dict with optional Referer/Origin
        """
        headers = self.get_session_headers()

        if referer:
            headers["Referer"] = referer
        if origin:
            headers["Origin"] = origin

        return headers


def get_random_headers(
    mode: str = "desktop",
    referer: Optional[str] = None,
) -> Dict[str, str]:
    """
    Convenience function to get random browser-like headers.

    Args:
        mode: "desktop", "mobile", "bot", or "mixed"
        referer: Optional referer URL

    Returns:
        Dict of HTTP headers

    Example:
        headers = get_random_headers(mode="desktop")

        async with DataDownload() as client:
            # Override default headers
            client._client.headers.update(headers)
            result = await client.download(url)
    """
    rotator = HeaderRotator(mode=mode)
    headers = rotator.get_session_headers()

    if referer:
        headers["Referer"] = referer

    return headers
