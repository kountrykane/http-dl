"""
Comprehensive tests for FileDownload client.

Tests cover:
- Basic file downloads (streaming to disk)
- Resumable downloads with ETag validation
- Checksum validation (MD5, SHA256, SHA512)
- Progress callbacks
- Batch downloads
- HEAD requests
- Error handling
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from httpdl import DownloadSettings, FileDownload
from httpdl.exceptions import InvalidURLError, DownloadError
from httpdl.models.results import BatchDownloadResult


class DummyStreamResponse:
    """Async context manager that mimics httpx's streaming interface."""

    def __init__(
        self,
        chunks: Iterable[bytes],
        headers: dict[str, str] | None = None,
        status_code: int = 200,
    ) -> None:
        self._chunks = list(chunks)
        self.headers = httpx.Headers(headers or {})
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                message=f"HTTP {self.status_code}",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(self.status_code),
            )
        return None

    async def aiter_raw(self, chunk_size: int = 8192):
        for chunk in self._chunks:
            yield chunk

    async def aiter_bytes(self, chunk_size: int = 8192):
        for chunk in self._chunks:
            yield chunk


@pytest.fixture(autouse=True)
def disable_rate_limit(monkeypatch):
    """Disable rate limiting for deterministic tests."""

    async def _noop(self):
        return None

    monkeypatch.setattr(FileDownload, "_apply_rate_limit", _noop)


@pytest.fixture
async def file_client(tmp_path):
    """Create FileDownload client with temp directory."""
    async with FileDownload(DownloadSettings(), download_dir=tmp_path) as client:
        yield client


class TestBasicDownloads:
    """Test basic file download functionality."""

    @pytest.mark.asyncio
    async def test_initialization(self, tmp_path):
        """Test FileDownload initializes correctly."""
        settings = DownloadSettings()
        client = FileDownload(settings, download_dir=tmp_path)

        assert client.settings == settings
        assert client.download_dir == tmp_path
        assert "md5" in client._checksums
        assert "sha256" in client._checksums
        assert "sha512" in client._checksums

    @pytest.mark.asyncio
    async def test_download_streams_file_to_disk(self, file_client, tmp_path, monkeypatch):
        """Test basic download to disk."""
        chunks = [b"hello ", b"world"]
        content_length = sum(len(c) for c in chunks)

        # Mock HEAD request
        head_response = AsyncMock()
        head_response.headers = httpx.Headers({
            "Content-Length": str(content_length),
            "Content-Type": "text/plain",
        })
        head_response.aclose = AsyncMock()

        file_client._do_request_with_retry = AsyncMock(return_value=(head_response, []))

        def fake_stream(method: str, url: str, headers=None):
            assert method == "GET"
            return DummyStreamResponse(chunks)

        monkeypatch.setattr(file_client._client, "stream", fake_stream)

        file_path = tmp_path / "report.txt"
        result = await file_client.download(
            "https://example.com/report.txt",
            file_path=file_path,
        )

        assert result.saved_to_disk is True
        assert result.file_path == file_path
        assert result.size_bytes == content_length
        assert file_path.exists()
        assert file_path.read_bytes() == b"hello world"

    @pytest.mark.asyncio
    async def test_download_creates_parent_directories(self, file_client, tmp_path, monkeypatch):
        """Test download creates nested parent directories."""
        chunks = [b"test content"]
        nested_path = tmp_path / "nested" / "dir" / "file.txt"

        # Mock HEAD request
        head_response = AsyncMock()
        head_response.headers = httpx.Headers({
            "Content-Length": str(len(b"test content")),
            "Content-Type": "text/plain",
        })
        head_response.aclose = AsyncMock()

        file_client._do_request_with_retry = AsyncMock(return_value=(head_response, []))

        def fake_stream(method: str, url: str, headers=None):
            return DummyStreamResponse(chunks)

        monkeypatch.setattr(file_client._client, "stream", fake_stream)

        result = await file_client.download(
            "https://example.com/file.txt",
            file_path=nested_path,
        )

        assert nested_path.exists()
        assert nested_path.parent.exists()
        assert result.file_path == nested_path

    @pytest.mark.asyncio
    async def test_download_rejects_empty_url(self, file_client):
        """Test download raises InvalidURLError for empty URL."""
        with pytest.raises(InvalidURLError):
            await file_client.download("   ")


class TestResumableDownloads:
    """Test resumable download functionality."""

    @pytest.mark.asyncio
    async def test_resume_partial_download(self, file_client, tmp_path, monkeypatch):
        """Test resuming a partial download."""
        file_path = tmp_path / "partial.txt"

        # Create partial file
        file_path.write_bytes(b"hello ")
        etag_file = file_path.with_suffix(file_path.suffix + ".etag")
        etag_file.write_text('"etag123"')

        # Mock HEAD request - server supports resume
        head_response = AsyncMock()
        head_response.headers = httpx.Headers({
            "Content-Length": "11",
            "Content-Type": "text/plain",
            "ETag": '"etag123"',
            "Accept-Ranges": "bytes",
        })
        head_response.aclose = AsyncMock()

        file_client._do_request_with_retry = AsyncMock(return_value=(head_response, []))

        # Mock streaming with Range header
        def fake_stream(method: str, url: str, headers=None):
            if headers and "Range" in headers:
                assert headers["Range"] == "bytes=6-"
                # Return remaining content
                return DummyStreamResponse([b"world"], status_code=206)
            return DummyStreamResponse([b"hello world"])

        monkeypatch.setattr(file_client._client, "stream", fake_stream)

        result = await file_client.download(
            "https://example.com/file.txt",
            file_path=file_path,
            resume=True,
        )

        assert result.resumed is True
        assert result.size_bytes == 11
        assert file_path.read_bytes() == b"hello world"

    @pytest.mark.asyncio
    async def test_resume_fails_on_etag_mismatch(self, file_client, tmp_path, monkeypatch):
        """Test resume is skipped when ETag changes."""
        file_path = tmp_path / "partial.txt"
        file_path.write_bytes(b"old ")

        etag_file = file_path.with_suffix(file_path.suffix + ".etag")
        etag_file.write_text('"old_etag"')

        # Mock HEAD request with different ETag
        head_response = AsyncMock()
        head_response.headers = httpx.Headers({
            "Content-Length": "11",
            "ETag": '"new_etag"',
            "Accept-Ranges": "bytes",
        })
        head_response.aclose = AsyncMock()

        file_client._do_request_with_retry = AsyncMock(return_value=(head_response, []))

        # Should download from scratch
        def fake_stream(method: str, url: str, headers=None):
            # Should NOT have Range header
            assert not (headers and "Range" in headers)
            return DummyStreamResponse([b"new content"])

        monkeypatch.setattr(file_client._client, "stream", fake_stream)

        result = await file_client.download(
            "https://example.com/file.txt",
            file_path=file_path,
            resume=True,
        )

        assert result.resumed is False
        assert file_path.read_bytes() == b"new content"


class TestChecksumValidation:
    """Test checksum validation functionality."""

    @pytest.mark.asyncio
    async def test_download_with_valid_checksum(self, file_client, tmp_path, monkeypatch):
        """Test download with successful checksum validation."""
        content = b"test content for checksum"
        expected_checksum = hashlib.sha256(content).hexdigest()
        file_path = tmp_path / "file.txt"

        # Mock HEAD request
        head_response = AsyncMock()
        head_response.headers = httpx.Headers({
            "Content-Length": str(len(content)),
        })
        head_response.aclose = AsyncMock()

        file_client._do_request_with_retry = AsyncMock(return_value=(head_response, []))

        def fake_stream(method: str, url: str, headers=None):
            return DummyStreamResponse([content])

        monkeypatch.setattr(file_client._client, "stream", fake_stream)

        result = await file_client.download(
            "https://example.com/file.txt",
            file_path=file_path,
            checksum_type="sha256",
            expected_checksum=expected_checksum,
        )

        assert result.checksum == expected_checksum
        assert result.checksum_type == "sha256"
        assert file_path.exists()

    @pytest.mark.asyncio
    async def test_download_fails_on_checksum_mismatch(self, file_client, tmp_path, monkeypatch):
        """Test download fails when checksum doesn't match."""
        content = b"test content"
        wrong_checksum = "0" * 64  # Invalid SHA256
        file_path = tmp_path / "file.txt"

        # Mock HEAD request
        head_response = AsyncMock()
        head_response.headers = httpx.Headers({
            "Content-Length": str(len(content)),
        })
        head_response.aclose = AsyncMock()

        file_client._do_request_with_retry = AsyncMock(return_value=(head_response, []))

        def fake_stream(method: str, url: str, headers=None):
            return DummyStreamResponse([content])

        monkeypatch.setattr(file_client._client, "stream", fake_stream)

        with pytest.raises(DownloadError, match="Checksum validation failed"):
            await file_client.download(
                "https://example.com/file.txt",
                file_path=file_path,
                checksum_type="sha256",
                expected_checksum=wrong_checksum,
            )

        # File should be cleaned up
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_download_unsupported_checksum_type(self, file_client, tmp_path):
        """Test download raises error for unsupported checksum type."""
        with pytest.raises(ValueError, match="Unsupported checksum type"):
            await file_client.download(
                "https://example.com/file.txt",
                file_path=tmp_path / "file.txt",
                checksum_type="invalid_algorithm",
            )


class TestProgressCallback:
    """Test progress callback functionality."""

    @pytest.mark.asyncio
    async def test_progress_callback_called(self, file_client, tmp_path, monkeypatch):
        """Test progress callback is called during download."""
        content = b"test content"
        file_path = tmp_path / "file.txt"
        progress_calls = []

        async def progress_callback(current, total):
            progress_calls.append((current, total))

        # Mock HEAD request
        head_response = AsyncMock()
        head_response.headers = httpx.Headers({
            "Content-Length": str(len(content)),
        })
        head_response.aclose = AsyncMock()

        file_client._do_request_with_retry = AsyncMock(return_value=(head_response, []))

        def fake_stream(method: str, url: str, headers=None):
            return DummyStreamResponse([content])

        monkeypatch.setattr(file_client._client, "stream", fake_stream)

        await file_client.download(
            "https://example.com/file.txt",
            file_path=file_path,
            progress_callback=progress_callback,
        )

        # Progress callback should have been called
        assert len(progress_calls) > 0
        last_call = progress_calls[-1]
        assert last_call[0] == len(content)
        assert last_call[1] == len(content)


class TestHEADRequest:
    """Test HEAD request functionality."""

    @pytest.mark.asyncio
    async def test_head_request_success(self, file_client):
        """Test successful HEAD request."""
        # Mock HEAD response
        head_response = AsyncMock()
        head_response.headers = httpx.Headers({
            "Content-Length": "1024",
            "ETag": '"abc123"',
            "Content-Type": "application/zip",
            "Accept-Ranges": "bytes",
            "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
        })
        head_response.aclose = AsyncMock()

        file_client._do_request_with_retry = AsyncMock(return_value=(head_response, []))

        metadata = await file_client.head_request("https://example.com/file.zip")

        assert metadata["content_length"] == 1024
        assert metadata["etag"] == '"abc123"'
        assert metadata["content_type"] == "application/zip"
        assert metadata["accept_ranges"] is True
        assert "last_modified" in metadata

    @pytest.mark.asyncio
    async def test_head_request_empty_url(self, file_client):
        """Test HEAD request raises InvalidURLError for empty URL."""
        with pytest.raises(InvalidURLError):
            await file_client.head_request("")


class TestBatchDownloads:
    """Test batch download functionality."""

    @pytest.mark.asyncio
    async def test_download_batch_success(self, file_client, tmp_path, monkeypatch):
        """Test batch download with all successful downloads."""
        urls = [f"https://example.com/file{i}.txt" for i in range(3)]

        # Mock HEAD request
        head_response = AsyncMock()
        head_response.headers = httpx.Headers({"Content-Length": "10"})
        head_response.aclose = AsyncMock()

        file_client._do_request_with_retry = AsyncMock(return_value=(head_response, []))

        def fake_stream(method: str, url: str, headers=None):
            return DummyStreamResponse([b"test data!"])

        monkeypatch.setattr(file_client._client, "stream", fake_stream)

        result = await file_client.download_batch(urls, max_concurrent=2)

        assert isinstance(result, BatchDownloadResult)
        assert len(result.successful) == 3
        assert len(result.failed) == 0
        assert result.success_rate == 100.0

    @pytest.mark.asyncio
    async def test_download_batch_with_callbacks(self, file_client, tmp_path, monkeypatch):
        """Test batch download with success and error callbacks."""
        urls = ["https://example.com/file1.txt", "https://example.com/file2.txt"]
        success_calls = []
        error_calls = []

        async def on_success(result):
            success_calls.append(result)

        async def on_error(url, error):
            error_calls.append((url, error))

        # Mock HEAD request
        head_response = AsyncMock()
        head_response.headers = httpx.Headers({"Content-Length": "10"})
        head_response.aclose = AsyncMock()

        file_client._do_request_with_retry = AsyncMock(return_value=(head_response, []))

        def fake_stream(method: str, url: str, headers=None):
            return DummyStreamResponse([b"test data!"])

        monkeypatch.setattr(file_client._client, "stream", fake_stream)

        result = await file_client.download_batch(
            urls,
            max_concurrent=2,
            on_success=on_success,
            on_error=on_error,
        )

        assert len(success_calls) == 2
        assert len(error_calls) == 0
