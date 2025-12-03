"""
Tests for session management with cookie persistence.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import httpx

from httpdl.session.manager import (
    SessionManager,
    SessionDownload,
    create_cookie_jar_from_dict,
    extract_cookies_as_dict,
)
from httpdl import DownloadSettings


@pytest.fixture
def temp_session_file(tmp_path):
    """Create temporary session file path."""
    return tmp_path / "test_session.json"


@pytest.fixture
def mock_httpx_client():
    """Create mock httpx.AsyncClient with cookies."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.cookies = httpx.Cookies()

    # Add some mock cookies
    client.cookies.set("session_id", "abc123", domain=".example.com")
    client.cookies.set("auth_token", "xyz789", domain=".example.com")

    return client


@pytest.fixture
def sample_session_data():
    """Sample session data JSON."""
    return {
        "cookies": [
            {
                "name": "session_id",
                "value": "abc123",
                "domain": ".example.com",
                "path": "/",
                "secure": True,
                "expires": None,
            },
            {
                "name": "auth_token",
                "value": "xyz789",
                "domain": ".example.com",
                "path": "/",
                "secure": True,
                "expires": None,
            },
        ],
        "saved_at": "2024-01-15T12:00:00",
    }


class TestSessionManager:
    """Test SessionManager class."""

    def test_initialization_default(self):
        """Test SessionManager initializes with default path."""
        manager = SessionManager()

        assert manager.session_file == Path(".httpdl_session.json")

    def test_initialization_custom_path(self, temp_session_file):
        """Test SessionManager initializes with custom path."""
        manager = SessionManager(session_file=temp_session_file)

        assert manager.session_file == temp_session_file

    @pytest.mark.asyncio
    async def test_save_session(self, temp_session_file, mock_httpx_client):
        """Test save_session saves cookies to disk."""
        manager = SessionManager(session_file=temp_session_file)

        await manager.save_session(mock_httpx_client)

        # Verify file was created
        assert temp_session_file.exists()

        # Verify content
        session_data = json.loads(temp_session_file.read_text())
        assert "cookies" in session_data
        assert "saved_at" in session_data
        assert len(session_data["cookies"]) == 2

    @pytest.mark.asyncio
    async def test_save_session_cookie_serialization(self, temp_session_file, mock_httpx_client):
        """Test save_session correctly serializes cookies."""
        manager = SessionManager(session_file=temp_session_file)

        await manager.save_session(mock_httpx_client)

        session_data = json.loads(temp_session_file.read_text())
        cookies = session_data["cookies"]

        # Check first cookie
        cookie = cookies[0]
        assert cookie["name"] == "session_id"
        assert cookie["value"] == "abc123"
        assert cookie["domain"] == ".example.com"

    @pytest.mark.asyncio
    async def test_load_session_success(self, temp_session_file, sample_session_data):
        """Test load_session loads cookies from disk."""
        # Write sample session file
        temp_session_file.write_text(json.dumps(sample_session_data))

        manager = SessionManager(session_file=temp_session_file)
        client = AsyncMock(spec=httpx.AsyncClient)
        client.cookies = httpx.Cookies()

        result = await manager.load_session(client)

        assert result is True
        assert client.cookies.get("session_id") == "abc123"
        assert client.cookies.get("auth_token") == "xyz789"

    @pytest.mark.asyncio
    async def test_load_session_not_found(self, temp_session_file):
        """Test load_session returns False when file doesn't exist."""
        manager = SessionManager(session_file=temp_session_file)
        client = AsyncMock(spec=httpx.AsyncClient)
        client.cookies = httpx.Cookies()

        result = await manager.load_session(client)

        assert result is False

    @pytest.mark.asyncio
    async def test_load_session_invalid_json(self, temp_session_file):
        """Test load_session handles invalid JSON gracefully."""
        temp_session_file.write_text("invalid json{{{")

        manager = SessionManager(session_file=temp_session_file)
        client = AsyncMock(spec=httpx.AsyncClient)
        client.cookies = httpx.Cookies()

        result = await manager.load_session(client)

        assert result is False

    @pytest.mark.asyncio
    async def test_clear_session(self, temp_session_file):
        """Test clear_session removes session file."""
        # Create session file
        temp_session_file.write_text("test data")
        assert temp_session_file.exists()

        manager = SessionManager(session_file=temp_session_file)
        await manager.clear_session()

        assert not temp_session_file.exists()

    @pytest.mark.asyncio
    async def test_clear_session_nonexistent(self, temp_session_file):
        """Test clear_session handles nonexistent file gracefully."""
        manager = SessionManager(session_file=temp_session_file)

        # Should not raise exception
        await manager.clear_session()

    def test_serialize_cookies(self, mock_httpx_client):
        """Test _serialize_cookies converts cookies to list."""
        manager = SessionManager()

        serialized = manager._serialize_cookies(mock_httpx_client.cookies)

        assert isinstance(serialized, list)
        assert len(serialized) == 2
        assert all("name" in cookie for cookie in serialized)
        assert all("value" in cookie for cookie in serialized)


class TestSessionDownload:
    """Test SessionDownload class."""

    @pytest.mark.asyncio
    async def test_initialization(self, temp_session_file):
        """Test SessionDownload initializes correctly."""
        settings = DownloadSettings()

        client = SessionDownload(
            settings=settings,
            session_file=temp_session_file,
            auto_save=True,
        )

        assert client.session_manager.session_file == temp_session_file
        assert client.auto_save is True

    @pytest.mark.asyncio
    async def test_context_manager_loads_session(self, temp_session_file, sample_session_data):
        """Test SessionDownload loads session on context enter."""
        # Create session file
        temp_session_file.write_text(json.dumps(sample_session_data))

        with patch("httpdl.session.BaseDownload.__aenter__") as mock_base_enter:
            mock_base_enter.return_value = AsyncMock()

            client = SessionDownload(session_file=temp_session_file)

            with patch.object(client.session_manager, "load_session", new=AsyncMock()) as mock_load:
                async with client:
                    pass

                mock_load.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_saves_session(self, temp_session_file):
        """Test SessionDownload saves session on context exit."""
        with patch("httpdl.session.BaseDownload.__aenter__") as mock_base_enter, \
             patch("httpdl.session.BaseDownload.__aexit__") as mock_base_exit:

            mock_base_enter.return_value = AsyncMock()
            mock_base_exit.return_value = AsyncMock()

            client = SessionDownload(session_file=temp_session_file, auto_save=True)
            client._client = AsyncMock(spec=httpx.AsyncClient)
            client._client.cookies = httpx.Cookies()

            with patch.object(client.session_manager, "save_session", new=AsyncMock()) as mock_save, \
                 patch.object(client.session_manager, "load_session", new=AsyncMock()):

                async with client:
                    pass

                mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_no_auto_save(self, temp_session_file):
        """Test SessionDownload doesn't save when auto_save=False."""
        with patch("httpdl.session.BaseDownload.__aenter__") as mock_base_enter, \
             patch("httpdl.session.BaseDownload.__aexit__") as mock_base_exit:

            mock_base_enter.return_value = AsyncMock()
            mock_base_exit.return_value = AsyncMock()

            client = SessionDownload(session_file=temp_session_file, auto_save=False)
            client._client = AsyncMock(spec=httpx.AsyncClient)

            with patch.object(client.session_manager, "save_session", new=AsyncMock()) as mock_save, \
                 patch.object(client.session_manager, "load_session", new=AsyncMock()):

                async with client:
                    pass

                mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_download_not_implemented(self, temp_session_file):
        """Test SessionDownload.download raises NotImplementedError."""
        client = SessionDownload(session_file=temp_session_file)

        with pytest.raises(NotImplementedError, match="SessionDownload is a base class"):
            await client.download("https://example.com")


class TestCreateCookieJarFromDict:
    """Test create_cookie_jar_from_dict utility function."""

    def test_create_empty_jar(self):
        """Test create_cookie_jar_from_dict with empty dict."""
        jar = create_cookie_jar_from_dict({})

        assert isinstance(jar, httpx.Cookies)
        assert len(jar) == 0

    def test_create_jar_with_cookies(self):
        """Test create_cookie_jar_from_dict with cookies."""
        cookies = {
            "session_id": "abc123",
            "auth_token": "xyz789",
        }

        jar = create_cookie_jar_from_dict(cookies, domain=".example.com")

        assert isinstance(jar, httpx.Cookies)
        assert len(jar) == 2

    def test_create_jar_with_domain(self):
        """Test create_cookie_jar_from_dict sets domain correctly."""
        cookies = {"session_id": "abc123"}

        jar = create_cookie_jar_from_dict(cookies, domain=".example.com")

        # Verify domain is set (check via jar iteration)
        cookie_list = list(jar.jar)
        assert cookie_list[0].domain == ".example.com"

    def test_create_jar_no_domain(self):
        """Test create_cookie_jar_from_dict with no domain."""
        cookies = {"session_id": "abc123"}

        jar = create_cookie_jar_from_dict(cookies, domain="")

        assert len(jar) == 1


class TestExtractCookiesAsDict:
    """Test extract_cookies_as_dict utility function."""

    def test_extract_empty_jar(self):
        """Test extract_cookies_as_dict with empty jar."""
        jar = httpx.Cookies()

        result = extract_cookies_as_dict(jar)

        assert result == {}

    def test_extract_cookies(self):
        """Test extract_cookies_as_dict extracts cookies."""
        jar = httpx.Cookies()
        jar.set("session_id", "abc123", domain=".example.com")
        jar.set("auth_token", "xyz789", domain=".example.com")

        result = extract_cookies_as_dict(jar)

        assert result["session_id"] == "abc123"
        assert result["auth_token"] == "xyz789"

    def test_extract_cookies_with_domain_filter(self):
        """Test extract_cookies_as_dict with domain filter."""
        jar = httpx.Cookies()
        jar.set("cookie1", "value1", domain=".example.com")
        jar.set("cookie2", "value2", domain=".other.com")

        result = extract_cookies_as_dict(jar, domain=".example.com")

        assert "cookie1" in result
        assert "cookie2" not in result

    def test_extract_cookies_no_domain_filter(self):
        """Test extract_cookies_as_dict without domain filter."""
        jar = httpx.Cookies()
        jar.set("cookie1", "value1", domain=".example.com")
        jar.set("cookie2", "value2", domain=".other.com")

        result = extract_cookies_as_dict(jar)

        assert "cookie1" in result
        assert "cookie2" in result


class TestSessionIntegration:
    """Integration tests for session management."""

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, temp_session_file):
        """Test save and load session roundtrip."""
        manager = SessionManager(session_file=temp_session_file)

        # Create client with cookies
        save_client = AsyncMock(spec=httpx.AsyncClient)
        save_client.cookies = httpx.Cookies()
        save_client.cookies.set("test_cookie", "test_value", domain=".example.com")

        # Save session
        await manager.save_session(save_client)

        # Load into new client
        load_client = AsyncMock(spec=httpx.AsyncClient)
        load_client.cookies = httpx.Cookies()

        result = await manager.load_session(load_client)

        assert result is True
        assert load_client.cookies.get("test_cookie") == "test_value"

    @pytest.mark.asyncio
    async def test_multiple_cookies_roundtrip(self, temp_session_file):
        """Test save and load with multiple cookies."""
        manager = SessionManager(session_file=temp_session_file)

        # Create client with multiple cookies
        save_client = AsyncMock(spec=httpx.AsyncClient)
        save_client.cookies = httpx.Cookies()
        save_client.cookies.set("cookie1", "value1", domain=".example.com")
        save_client.cookies.set("cookie2", "value2", domain=".example.com")
        save_client.cookies.set("cookie3", "value3", domain=".example.com")

        # Save session
        await manager.save_session(save_client)

        # Verify file content
        session_data = json.loads(temp_session_file.read_text())
        assert len(session_data["cookies"]) == 3

        # Load into new client
        load_client = AsyncMock(spec=httpx.AsyncClient)
        load_client.cookies = httpx.Cookies()

        await manager.load_session(load_client)

        stored = extract_cookies_as_dict(load_client.cookies)
        assert stored["cookie1"] == "value1"
        assert stored["cookie2"] == "value2"
        assert stored["cookie3"] == "value3"
