"""
Unit tests for the DataDownload client.

The original script in this module attempted to hit real SEC endpoints from the
test-suite, which caused pytest to hang indefinitely.  These tests stub the
network layer so we can focus on the transformation logic (decoding, kind
classification, error surfacing) without performing live HTTP requests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from httpdl import DataDownload, DownloadSettings
from httpdl.exceptions import NotFoundError


class DummyResponse:
    """Minimal async response object compatible with DataDownload."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
        url: str = "https://example.com/resource",
    ) -> None:
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})
        self._content = content
        self.request = httpx.Request("GET", url)
        self.closed = False

    async def aread(self) -> bytes:
        return self._content

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def disable_rate_limit(monkeypatch):
    """Short-circuit the global rate limiter so tests run instantly."""

    async def _noop(self):
        return None

    monkeypatch.setattr(DataDownload, "_apply_rate_limit", _noop)


@pytest.fixture
async def data_client():
    """Yield a fully initialised DataDownload instance."""
    async with DataDownload(DownloadSettings()) as client:
        yield client


@pytest.mark.asyncio
async def test_download_decodes_text_payload(data_client):
    response = DummyResponse(
        headers={"Content-Type": "application/json; charset=utf-8"},
        content=b'{"message": "hello"}',
    )
    data_client._do_request_with_retry = AsyncMock(return_value=(response, []))

    result = await data_client.download("https://example.com/data.json")

    assert result.status_code == 200
    assert result.text == '{"message": "hello"}'
    assert result.bytes_ is None
    assert result.kind == "json"


@pytest.mark.asyncio
async def test_download_returns_raw_bytes_for_binary_payload(data_client):
    payload = b"\x00\x01binary-data"
    response = DummyResponse(
        headers={"Content-Type": "application/octet-stream"},
        content=payload,
    )
    data_client._do_request_with_retry = AsyncMock(return_value=(response, []))

    result = await data_client.download("https://example.com/file.bin")

    assert result.text is None
    assert result.bytes_ == payload
    assert result.kind == "unknown"


@pytest.mark.asyncio
async def test_download_override_kind_respected(data_client):
    response = DummyResponse(
        headers={"Content-Type": "text/html; charset=utf-8"},
        content=b"<html><body>Hello</body></html>",
    )
    data_client._do_request_with_retry = AsyncMock(return_value=(response, []))

    result = await data_client.download(
        "https://example.com/override", override_kind="json"
    )

    assert result.kind == "json"
    assert "override_kind" in (result.sniff_note or "")


@pytest.mark.asyncio
async def test_download_raises_for_http_errors(data_client):
    response = DummyResponse(
        status_code=404,
        headers={"Content-Type": "text/html; charset=utf-8"},
        content=b"<html>missing</html>",
    )
    data_client._do_request_with_retry = AsyncMock(return_value=(response, []))

    with pytest.raises(NotFoundError):
        await data_client.download("https://example.com/missing")
