"""
Tests for streaming downloads with resumable support and checksum validation.
"""

import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from httpdl import FileDownload, DownloadSettings
from httpdl.models.results import FileDownloadResult
from httpdl.exceptions import DownloadError, InvalidURLError


@pytest.fixture
def temp_download_dir(tmp_path):
    """Create temporary download directory."""
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    return download_dir


@pytest.fixture
def sample_content():
    """Sample download content."""
    return b"This is sample file content for testing."


@pytest.fixture
def sample_checksum():
    """SHA256 checksum of sample content."""
    content = b"This is sample file content for testing."
    return hashlib.sha256(content).hexdigest()


class TestFileDownload:
    """Test FileDownload class."""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test FileDownload initializes correctly."""
        settings = DownloadSettings()
        client = FileDownload(settings)

        assert client.settings == settings
        assert "md5" in client._checksums
        assert "sha256" in client._checksums
        assert "sha512" in client._checksums

    @pytest.mark.asyncio
    async def test_head_request_empty_url(self):
        """Test head_request raises InvalidURLError for empty URL."""
        async with FileDownload() as client:
            with pytest.raises(InvalidURLError):
                await client.head_request("")

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_head_request_success(self, mock_client_class):
        """Test successful HEAD request."""
        # Mock response
        mock_response = AsyncMock()
        mock_response.headers = {
            "Content-Length": "1024",
            "ETag": '"abc123"',
            "Content-Type": "application/zip",
            "Accept-Ranges": "bytes",
            "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"
        }

        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client

        async with FileDownload() as client:
            client._client = mock_client

            # Mock _do_request_with_retry
            client._do_request_with_retry = AsyncMock(return_value=(mock_response, None))

            metadata = await client.head_request("https://example.com/file.zip")

        assert metadata["content_length"] == 1024
        assert metadata["etag"] == '"abc123"'
        assert metadata["content_type"] == "application/zip"
        assert metadata["accept_ranges"] is True
        assert "last_modified" in metadata

    @pytest.mark.asyncio
    async def test_download_empty_url(self, temp_download_dir):
        """Test download raises InvalidURLError for empty URL."""
        async with FileDownload() as client:
            with pytest.raises(InvalidURLError):
                await client.download(
                    url="",
                    file_path=temp_download_dir / "test.zip"
                )

    @pytest.mark.asyncio
    async def test_download_creates_parent_dirs(self, temp_download_dir, sample_content):
        """Test download creates parent directories."""
        nested_path = temp_download_dir / "nested" / "dir" / "file.txt"

        async with FileDownload() as client:
            # Mock the HEAD and download process
            client.head_request = AsyncMock(return_value={
                "content_length": len(sample_content),
                "etag": '"test"',
                "content_type": "text/plain",
                "accept_ranges": True,
            })

            # Mock streaming response
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.aiter_bytes = AsyncMock(return_value=[sample_content])

            client._client = AsyncMock()
            client._client.stream = MagicMock()
            client._client.stream.return_value.__aenter__.return_value = mock_response

            result = await client.download(
                url="https://example.com/file.txt",
                file_path=nested_path
            )

        assert nested_path.exists()
        assert nested_path.parent.exists()

    @pytest.mark.asyncio
    async def test_download_with_checksum_validation(self, temp_download_dir, sample_content, sample_checksum):
        """Test download with successful checksum validation."""
        file_path = temp_download_dir / "file.txt"

        async with FileDownload() as client:
            # Mock HEAD request
            client.head_request = AsyncMock(return_value={
                "content_length": len(sample_content),
                "etag": '"test"',
                "content_type": "text/plain",
                "accept_ranges": False,
            })

            # Mock streaming response
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.aiter_bytes = AsyncMock(return_value=[sample_content])

            client._client = AsyncMock()
            client._client.stream = MagicMock()
            client._client.stream.return_value.__aenter__.return_value = mock_response

            result = await client.download(
                url="https://example.com/file.txt",
                file_path=file_path,
                checksum_type="sha256",
                expected_checksum=sample_checksum
            )

        assert result.checksum == sample_checksum
        assert result.checksum_type == "sha256"
        assert file_path.exists()

    @pytest.mark.asyncio
    async def test_download_checksum_mismatch(self, temp_download_dir, sample_content):
        """Test download fails on checksum mismatch."""
        file_path = temp_download_dir / "file.txt"
        wrong_checksum = "wrong_checksum_value"

        async with FileDownload() as client:
            # Mock HEAD request
            client.head_request = AsyncMock(return_value={
                "content_length": len(sample_content),
                "etag": None,
                "content_type": "text/plain",
                "accept_ranges": False,
            })

            # Mock streaming response
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.aiter_bytes = AsyncMock(return_value=[sample_content])

            client._client = AsyncMock()
            client._client.stream = MagicMock()
            client._client.stream.return_value.__aenter__.return_value = mock_response

            with pytest.raises(DownloadError, match="Checksum validation failed"):
                await client.download(
                    url="https://example.com/file.txt",
                    file_path=file_path,
                    checksum_type="sha256",
                    expected_checksum=wrong_checksum
                )

        # File should be cleaned up on validation failure
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_download_with_etag_save(self, temp_download_dir, sample_content):
        """Test download saves ETag for future resume."""
        file_path = temp_download_dir / "file.txt"
        etag = '"abc123"'

        async with FileDownload() as client:
            client.head_request = AsyncMock(return_value={
                "content_length": len(sample_content),
                "etag": etag,
                "content_type": "text/plain",
                "accept_ranges": True,
            })

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.aiter_bytes = AsyncMock(return_value=[sample_content])

            client._client = AsyncMock()
            client._client.stream = MagicMock()
            client._client.stream.return_value.__aenter__.return_value = mock_response

            await client.download(
                url="https://example.com/file.txt",
                file_path=file_path
            )

        # ETag should be saved
        etag_file = file_path.with_suffix(file_path.suffix + ".etag")
        assert etag_file.exists()
        assert etag_file.read_text().strip() == etag

    @pytest.mark.asyncio
    async def test_download_unsupported_checksum(self, temp_download_dir):
        """Test download raises error for unsupported checksum type."""
        file_path = temp_download_dir / "file.txt"

        async with FileDownload() as client:
            with pytest.raises(ValueError, match="Unsupported checksum type"):
                await client.download(
                    url="https://example.com/file.txt",
                    file_path=file_path,
                    checksum_type="invalid_algorithm"
                )

    @pytest.mark.asyncio
    async def test_progress_callback(self, temp_download_dir, sample_content):
        """Test download calls progress callback."""
        file_path = temp_download_dir / "file.txt"
        progress_calls = []

        async def progress_callback(current, total):
            progress_calls.append((current, total))

        async with FileDownload() as client:
            client.head_request = AsyncMock(return_value={
                "content_length": len(sample_content),
                "etag": None,
                "content_type": "text/plain",
                "accept_ranges": False,
            })

            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.aiter_bytes = AsyncMock(return_value=[sample_content])

            client._client = AsyncMock()
            client._client.stream = MagicMock()
            client._client.stream.return_value.__aenter__.return_value = mock_response

            await client.download(
                url="https://example.com/file.txt",
                file_path=file_path,
                progress_callback=progress_callback
            )

        # Progress callback should have been called
        assert len(progress_calls) > 0
        last_call = progress_calls[-1]
        assert last_call[0] == len(sample_content)  # Current bytes
        assert last_call[1] == len(sample_content)  # Total bytes


    @pytest.mark.asyncio
    async def test_download_with_retry_success(self, temp_download_dir, sample_content):
        """Test successful download with retry."""
        file_path = temp_download_dir / "file.txt"

        with patch("httpdl.streaming.FileDownload") as MockFileDownload:
            mock_client = AsyncMock()
            mock_result = FileDownloadResult(
                url="https://example.com/file.txt",
                file_path=file_path,
                size_bytes=len(sample_content),
                checksum=None,
                checksum_type=None,
                duration_ms=100,
                resumed=False,
                etag=None,
                content_type="text/plain"
            )
            mock_client.download = AsyncMock(return_value=mock_result)
            MockFileDownload.return_value.__aenter__.return_value = mock_client

            result = await download_with_retry(
                url="https://example.com/file.txt",
                file_path=file_path,
                max_retries=3
            )

        assert result.url == "https://example.com/file.txt"
        assert result.size_bytes == len(sample_content)

    @pytest.mark.asyncio
    async def test_download_with_retry_retries_on_failure(self, temp_download_dir):
        """Test download_with_retry retries on failure."""
        file_path = temp_download_dir / "file.txt"

        with patch("httpdl.streaming.FileDownload") as MockFileDownload:
            mock_client = AsyncMock()
            # Fail twice, succeed on third attempt
            mock_client.download = AsyncMock(side_effect=[
                DownloadError("Failed 1"),
                DownloadError("Failed 2"),
                FileDownloadResult(
                    url="https://example.com/file.txt",
                    file_path=file_path,
                    size_bytes=100,
                    checksum=None,
                    checksum_type=None,
                    duration_ms=100,
                    resumed=False,
                    etag=None,
                    content_type="text/plain"
                )
            ])
            MockFileDownload.return_value.__aenter__.return_value = mock_client

            result = await download_with_retry(
                url="https://example.com/file.txt",
                file_path=file_path,
                max_retries=3
            )

        # Should succeed on third attempt
        assert result.size_bytes == 100
        assert mock_client.download.call_count == 3

    @pytest.mark.asyncio
    async def test_download_with_retry_max_retries_exceeded(self, temp_download_dir):
        """Test download_with_retry fails after max retries."""
        file_path = temp_download_dir / "file.txt"

        with patch("httpdl.streaming.FileDownload") as MockFileDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock(side_effect=DownloadError("Always fails"))
            MockFileDownload.return_value.__aenter__.return_value = mock_client

            with pytest.raises(DownloadError, match="Always fails"):
                await download_with_retry(
                    url="https://example.com/file.txt",
                    file_path=file_path,
                    max_retries=2
                )

        # Should have tried 2 times
        assert mock_client.download.call_count == 2
