"""
Comprehensive tests for DataDownload client.

Tests cover:
- Text decoding and classification
- Binary payload handling
- Content type classification (JSON, XML, HTML, etc.)
- Error handling and HTTP error surfacing
- Batch downloads with concurrency control
- Override kind functionality
- Character encoding handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from httpdl import DataDownload, DownloadSettings
from httpdl.exceptions import NotFoundError, InvalidURLError
from httpdl.models.results import BatchDownloadResult


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


class TestBasicDownloads:
    """Test basic data download functionality."""

    @pytest.mark.asyncio
    async def test_download_decodes_text_payload(self, data_client):
        """Test download correctly decodes JSON payload."""
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
    async def test_download_returns_raw_bytes_for_binary_payload(self, data_client):
        """Test download returns raw bytes for binary content."""
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
    async def test_download_rejects_empty_url(self, data_client):
        """Test download raises InvalidURLError for empty URL."""
        with pytest.raises(InvalidURLError):
            await data_client.download("   ")


class TestContentTypeClassification:
    """Test content type classification and decoding."""

    @pytest.mark.asyncio
    async def test_download_classifies_json(self, data_client):
        """Test JSON content is properly classified."""
        response = DummyResponse(
            headers={"Content-Type": "application/json"},
            content=b'{"key": "value"}',
        )
        data_client._do_request_with_retry = AsyncMock(return_value=(response, []))

        result = await data_client.download("https://example.com/data.json")

        assert result.kind == "json"
        assert result.text is not None
        assert result.bytes_ is None

    @pytest.mark.asyncio
    async def test_download_classifies_xml(self, data_client):
        """Test XML content is properly classified."""
        response = DummyResponse(
            headers={"Content-Type": "application/xml"},
            content=b"<?xml version='1.0'?><root>data</root>",
        )
        data_client._do_request_with_retry = AsyncMock(return_value=(response, []))

        result = await data_client.download("https://example.com/data.xml")

        assert result.kind == "xml"
        assert result.text is not None

    @pytest.mark.asyncio
    async def test_download_classifies_html(self, data_client):
        """Test HTML content is properly classified."""
        response = DummyResponse(
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=b"<html><body>Hello</body></html>",
        )
        data_client._do_request_with_retry = AsyncMock(return_value=(response, []))

        result = await data_client.download("https://example.com/page.html")

        assert result.kind == "html"
        assert result.text is not None

    @pytest.mark.asyncio
    async def test_download_override_kind_respected(self, data_client):
        """Test override_kind parameter overrides content classification."""
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


class TestErrorHandling:
    """Test error handling and HTTP status codes."""

    @pytest.mark.asyncio
    async def test_download_raises_for_404(self, data_client):
        """Test download raises NotFoundError for 404 responses."""
        response = DummyResponse(
            status_code=404,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=b"<html>missing</html>",
        )
        data_client._do_request_with_retry = AsyncMock(return_value=(response, []))

        with pytest.raises(NotFoundError):
            await data_client.download("https://example.com/missing")

    @pytest.mark.asyncio
    async def test_download_closes_response_on_error(self, data_client):
        """Test download properly closes response on error."""
        response = DummyResponse(
            status_code=500,
            headers={"Content-Type": "text/plain"},
            content=b"Internal Server Error",
        )
        data_client._do_request_with_retry = AsyncMock(return_value=(response, []))

        with pytest.raises(Exception):  # Should raise some HTTPError
            await data_client.download("https://example.com/error")

        # Response should be closed
        assert response.closed


class TestCharacterEncoding:
    """Test character encoding handling."""

    @pytest.mark.asyncio
    async def test_download_respects_charset_in_header(self, data_client):
        """Test download uses charset from Content-Type header."""
        # UTF-8 encoded text
        content = "Hello, 世界".encode("utf-8")
        response = DummyResponse(
            headers={"Content-Type": "text/plain; charset=utf-8"},
            content=content,
        )
        data_client._do_request_with_retry = AsyncMock(return_value=(response, []))

        result = await data_client.download("https://example.com/text.txt")

        assert result.text == "Hello, 世界"
        assert result.charset == "utf-8"

    @pytest.mark.asyncio
    async def test_download_handles_missing_charset(self, data_client):
        """Test download handles content without explicit charset."""
        response = DummyResponse(
            headers={"Content-Type": "text/plain"},
            content=b"Hello, world",
        )
        data_client._do_request_with_retry = AsyncMock(return_value=(response, []))

        result = await data_client.download("https://example.com/text.txt")

        assert result.text == "Hello, world"


class TestBatchDownloads:
    """Test batch download functionality."""

    @pytest.mark.asyncio
    async def test_download_batch_success(self, data_client):
        """Test batch download with all successful downloads."""
        urls = [f"https://example.com/data{i}.json" for i in range(3)]

        # Mock responses for all URLs
        def mock_request(*args):
            response = DummyResponse(
                headers={"Content-Type": "application/json"},
                content=b'{"data": "test"}',
            )
            return (response, [])

        data_client._do_request_with_retry = AsyncMock(side_effect=mock_request)

        result = await data_client.download_batch(urls, max_concurrent=2)

        assert isinstance(result, BatchResult)
        assert len(result.successful) == 3
        assert len(result.failed) == 0
        assert result.success_rate == 100.0

    @pytest.mark.asyncio
    async def test_download_batch_with_failures(self, data_client):
        """Test batch download with some failures."""
        urls = [f"https://example.com/data{i}.json" for i in range(3)]

        call_count = [0]

        def mock_request(*args):
            call_count[0] += 1
            if call_count[0] == 2:
                # Second request fails
                response = DummyResponse(
                    status_code=404,
                    headers={"Content-Type": "text/plain"},
                    content=b"Not Found",
                )
            else:
                response = DummyResponse(
                    headers={"Content-Type": "application/json"},
                    content=b'{"data": "test"}',
                )
            return (response, [])

        data_client._do_request_with_retry = AsyncMock(side_effect=mock_request)

        result = await data_client.download_batch(urls, max_concurrent=2)

        assert len(result.successful) == 2
        assert len(result.failed) == 1
        assert result.success_rate == pytest.approx(66.7, rel=0.1)

    @pytest.mark.asyncio
    async def test_download_batch_with_callbacks(self, data_client):
        """Test batch download with success and error callbacks."""
        urls = ["https://example.com/data1.json", "https://example.com/data2.json"]
        success_calls = []
        error_calls = []

        async def on_success(result):
            success_calls.append(result)

        async def on_error(url, error):
            error_calls.append((url, error))

        def mock_request(*args):
            response = DummyResponse(
                headers={"Content-Type": "application/json"},
                content=b'{"data": "test"}',
            )
            return (response, [])

        data_client._do_request_with_retry = AsyncMock(side_effect=mock_request)

        result = await data_client.download_batch(
            urls,
            max_concurrent=2,
            on_success=on_success,
            on_error=on_error,
        )

        assert len(success_calls) == 2
        assert len(error_calls) == 0
        assert result.success_rate == 100.0

    @pytest.mark.asyncio
    async def test_download_batch_empty_list(self, data_client):
        """Test batch download with empty URL list."""
        result = await data_client.download_batch([], max_concurrent=2)

        assert len(result.successful) == 0
        assert len(result.failed) == 0
        assert result.total == 0
        assert result.success_rate == 0.0


class TestRedirectHandling:
    """Test redirect chain tracking."""

    @pytest.mark.asyncio
    async def test_download_tracks_redirect_chain(self, data_client):
        """Test download tracks redirect URLs."""
        redirect_chain = [
            "https://example.com/redirect1",
            "https://example.com/redirect2",
        ]
        response = DummyResponse(
            headers={"Content-Type": "application/json"},
            content=b'{"data": "final"}',
            url="https://example.com/final",
        )
        data_client._do_request_with_retry = AsyncMock(return_value=(response, redirect_chain))

        result = await data_client.download("https://example.com/start")

        assert result.redirect_chain == redirect_chain
        assert len(result.redirect_chain) == 2


class TestMetadataCapture:
    """Test metadata capture in results."""

    @pytest.mark.asyncio
    async def test_download_captures_headers(self, data_client):
        """Test download captures response headers."""
        response = DummyResponse(
            headers={
                "Content-Type": "application/json",
                "X-Custom-Header": "test-value",
            },
            content=b'{"data": "test"}',
        )
        data_client._do_request_with_retry = AsyncMock(return_value=(response, []))

        result = await data_client.download("https://example.com/data.json")

        assert result.headers["Content-Type"] == "application/json"
        assert result.headers["X-Custom-Header"] == "test-value"

    @pytest.mark.asyncio
    async def test_download_captures_content_metrics(self, data_client):
        """Test download captures content size and duration."""
        content = b'{"message": "hello world"}'
        response = DummyResponse(
            headers={"Content-Type": "application/json"},
            content=content,
        )
        data_client._do_request_with_retry = AsyncMock(return_value=(response, []))

        result = await data_client.download("https://example.com/data.json")

        assert result.size_bytes == len(content)
        assert result.duration_ms > 0
        assert result.content_type == "application/json"
