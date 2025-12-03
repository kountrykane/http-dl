"""
Session management with cookie persistence and state management.

This module provides session management for maintaining state across requests:
- Cookie jar persistence (save/load from disk)
- Session state management
- Per-domain cookie isolation
- Automatic cookie handling
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Dict, Any
from http.cookiejar import Cookie
from datetime import datetime

import httpx

from ..clients.base import BaseDownload
from ..models.config import DownloadSettings
from ..observability.logging import get_httpdl_logger


class SessionManager:
    """
    Manage HTTP sessions with persistent cookie storage.

    Handles cookie persistence across application restarts and provides
    per-domain cookie isolation for multi-tenant scenarios.

    Example:
        # Save session after scraping
        session_mgr = SessionManager(session_file=Path("session.json"))
        async with DataDownload() as client:
            # Perform authenticated requests
            await client.download(url1)
            await client.download(url2)

            # Save cookies for next run
            await session_mgr.save_session(client._client)

        # Load session later
        async with DataDownload() as client:
            await session_mgr.load_session(client._client)
            # Cookies are restored, authentication maintained
            await client.download(url3)
    """

    def __init__(self, session_file: Optional[Path] = None):
        """
        Initialize session manager.

        Args:
            session_file: Path to store session data (cookies, etc.)
        """
        self.session_file = session_file or Path(".httpdl_session.json")
        self._logger = get_httpdl_logger(__name__)

    async def save_session(self, client: httpx.AsyncClient) -> None:
        """
        Save session state (cookies) to disk.

        Args:
            client: httpx.AsyncClient instance to extract cookies from
        """
        session_data = {
            "cookies": self._serialize_cookies(client.cookies),
            "saved_at": datetime.now().isoformat(),
        }

        self.session_file.write_text(json.dumps(session_data, indent=2))

        self._logger.info(
            "session.saved",
            session_file=str(self.session_file),
            cookie_count=len(client.cookies),
        )

    async def load_session(self, client: httpx.AsyncClient) -> bool:
        """
        Load session state (cookies) from disk.

        Args:
            client: httpx.AsyncClient instance to load cookies into

        Returns:
            True if session was loaded successfully, False if no session exists
        """
        if not self.session_file.exists():
            self._logger.debug("session.not_found", session_file=str(self.session_file))
            return False

        try:
            session_data = json.loads(self.session_file.read_text())
            cookies_data = session_data.get("cookies", [])

            # Load cookies into client
            for cookie_dict in cookies_data:
                client.cookies.set(
                    name=cookie_dict["name"],
                    value=cookie_dict["value"],
                    domain=cookie_dict.get("domain"),
                    path=cookie_dict.get("path", "/"),
                )

            self._logger.info(
                "session.loaded",
                session_file=str(self.session_file),
                cookie_count=len(cookies_data),
                saved_at=session_data.get("saved_at"),
            )

            return True

        except Exception as exc:
            self._logger.error(
                "session.load_failed",
                session_file=str(self.session_file),
                error=str(exc),
                exc_info=exc,
            )
            return False

    async def clear_session(self) -> None:
        """Clear saved session data."""
        if self.session_file.exists():
            self.session_file.unlink()
            self._logger.info("session.cleared", session_file=str(self.session_file))

    def _serialize_cookies(self, cookies: httpx.Cookies) -> list[dict]:
        """
        Serialize httpx.Cookies to JSON-compatible format.

        Args:
            cookies: httpx.Cookies instance

        Returns:
            List of cookie dictionaries
        """
        serialized = []

        for cookie in cookies.jar:
            cookie_dict = {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "secure": cookie.secure,
                "expires": cookie.expires,
            }
            serialized.append(cookie_dict)

        return serialized


class SessionDownload(BaseDownload):
    """
    Download client with automatic session management.

    Automatically saves and restores cookies between requests,
    making it easy to maintain authenticated sessions.

    Example:
        settings = DownloadSettings()
        session_file = Path("my_session.json")

        async with SessionDownload(settings, session_file=session_file) as client:
            # Session is automatically loaded

            # Make requests (cookies are maintained)
            result1 = await client.download(url1)
            result2 = await client.download(url2)

            # Session is automatically saved on exit
    """

    def __init__(
        self,
        settings: Optional[DownloadSettings] = None,
        session_file: Optional[Path] = None,
        auto_save: bool = True,
    ):
        """
        Initialize session-aware download client.

        Args:
            settings: Download settings
            session_file: Path to session file
            auto_save: Automatically save session on exit
        """
        super().__init__(settings)
        self.session_manager = SessionManager(session_file=session_file)
        self.auto_save = auto_save

    async def __aenter__(self) -> "SessionDownload":
        """Enter context and load session."""
        await super().__aenter__()

        # Load existing session
        await self.session_manager.load_session(self._client)

        return self

    async def __aexit__(self, *exc) -> None:
        """Exit context and optionally save session."""
        # Save session if enabled
        if self.auto_save and self._client is not None:
            await self.session_manager.save_session(self._client)

        await super().__aexit__(*exc)

    async def download(self, url: str, **kwargs):
        """
        Download with session management.

        Note: This is a base implementation. Subclass should implement
        actual download logic (DataDownload or FileDownload pattern).
        """
        raise NotImplementedError(
            "SessionDownload is a base class. Use SessionDataDownload or SessionFileDownload"
        )


def create_cookie_jar_from_dict(cookies: Dict[str, str], domain: str = "") -> httpx.Cookies:
    """
    Create httpx.Cookies from a dictionary.

    Utility function for manually creating cookie jars.

    Args:
        cookies: Dict of cookie name -> value
        domain: Domain to associate cookies with

    Returns:
        httpx.Cookies instance

    Example:
        cookies = create_cookie_jar_from_dict(
            {"session_id": "abc123", "auth_token": "xyz789"},
            domain=".example.com"
        )

        async with DataDownload() as client:
            client._client.cookies = cookies
            result = await client.download(url)
    """
    jar = httpx.Cookies()

    for name, value in cookies.items():
        jar.set(name=name, value=value, domain=domain)

    return jar


def extract_cookies_as_dict(cookies: httpx.Cookies, domain: Optional[str] = None) -> Dict[str, str]:
    """
    Extract cookies as a simple dict.

    Args:
        cookies: httpx.Cookies instance
        domain: Optional domain filter

    Returns:
        Dict of cookie name -> value

    Example:
        async with DataDownload() as client:
            result = await client.download(url)

            # Extract cookies
            cookie_dict = extract_cookies_as_dict(client._client.cookies)
            print(f"Session ID: {cookie_dict.get('session_id')}")
    """
    cookie_dict = {}

    for cookie in cookies.jar:
        # Filter by domain if specified
        if domain and cookie.domain != domain:
            continue

        cookie_dict[cookie.name] = cookie.value

    return cookie_dict
