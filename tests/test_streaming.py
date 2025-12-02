"""
Tests for streaming downloads with resumable support and checksum validation.
Uses real SEC EDGAR URLs for integration testing.
"""

import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from httpdl.streaming import StreamingDownload, download_with_retry, StreamingResult
from httpdl.config import DownloadSettings
from httpdl.exceptions import DownloadError, InvalidURLError


# Real SEC EDGAR URLs for testing
TEST_SEC_SMALL_FILE = "https://www.sec.gov/files/company_tickers.json"
TEST_SEC_ZIP_FILE = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/2024q3.zip"
TEST_SEC_ROBOTS = "https://www.sec.gov/robots.txt"

# Mark for integration tests that make real network calls
pytestmark = pytest.mark.asyncio


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


class TestStreamingDownload:
    """Test StreamingDownload class."""

    async def test_initialization(self):
        """Test StreamingDownload initializes correctly."""
        settings = DownloadSettings()
        client = StreamingDownload(settings)

        assert client.settings == settings
        assert "md5" in client._checksums
        assert "sha256" in client._checksums
        assert "sha512" in client._checksums

    async def test_head_request_empty_url(self):
        """Test head_request raises InvalidURLError for empty URL."""
        async with StreamingDownload() as client:
            with pytest.raises(InvalidURLError):
                await client.head_request("")

    @pytest.mark.timeout(30)
    @pytest.mark.integration
    async def test_head_request_real_sec_url(self):
        """Test HEAD request with real SEC URL."""
        async with StreamingDownload() as client:
            metadata = await client.head_request(TEST_SEC_ROBOTS)

            # Verify we got real metadata
            assert "content_length" in metadata
            assert metadata["content_length"] > 0
            assert "content_type" in metadata
            # SEC usually returns text/plain for robots.txt
            assert "text" in metadata["content_type"].lower()

    async def test_download_empty_url(self, temp_download_dir):
        """Test download raises InvalidURLError for empty URL."""
        async with StreamingDownload() as client:
            with pytest.raises(InvalidURLError):
                await client.download(
                    url="",
                    file_path=temp_download_dir / "test.zip"
                )

    @pytest.mark.timeout(30)
    @pytest.mark.integration
    async def test_download_creates_parent_dirs_real_url(self, temp_download_dir):
        """Test download creates parent directories with real SEC URL."""
        nested_path = temp_download_dir / "nested" / "dir" / "robots.txt"

        async with StreamingDownload() as client:
            result = await client.download(
                url=TEST_SEC_ROBOTS,
                file_path=nested_path
            )

        # Verify parent directories were created
        assert nested_path.exists()
        assert nested_path.parent.exists()
        # Verify file has content
        assert result.size_bytes > 0
        assert nested_path.stat().st_size > 0

    @pytest.mark.timeout(30)
    @pytest.mark.integration
    async def test_download_with_checksum_validation_real_url(self, temp_download_dir):
        """Test download with checksum validation using real SEC URL."""
        file_path = temp_download_dir / "robots.txt"

        # First download to get actual checksum
        async with StreamingDownload() as client:
            initial_result = await client.download(
                url=TEST_SEC_ROBOTS,
                file_path=file_path,
                checksum_type="sha256"
            )

            actual_checksum = initial_result.checksum
            assert actual_checksum is not None
            assert len(actual_checksum) == 64  # SHA256 is 64 hex chars

        # Clean up and download again with expected checksum
        file_path.unlink()

        async with StreamingDownload() as client:
            result = await client.download(
                url=TEST_SEC_ROBOTS,
                file_path=file_path,
                checksum_type="sha256",
                expected_checksum=actual_checksum
            )

        assert result.checksum == actual_checksum
        assert result.checksum_type == "sha256"
        assert file_path.exists()

    @pytest.mark.timeout(30)
    @pytest.mark.integration
    async def test_download_checksum_mismatch(self, temp_download_dir):
        """Test download fails on checksum mismatch with real SEC URL."""
        file_path = temp_download_dir / "robots.txt"
        wrong_checksum = "0" * 64  # Invalid SHA256 checksum

        async with StreamingDownload() as client:
            with pytest.raises(DownloadError, match="Checksum validation failed"):
                await client.download(
                    url=TEST_SEC_ROBOTS,
                    file_path=file_path,
                    checksum_type="sha256",
                    expected_checksum=wrong_checksum
                )

        # File should be cleaned up on validation failure
        assert not file_path.exists()

    @pytest.mark.timeout(30)
    @pytest.mark.integration
    async def test_download_with_etag_save_real_url(self, temp_download_dir):
        """Test download saves ETag for future resume with real SEC URL."""
        file_path = temp_download_dir / "company_tickers.json"

        async with StreamingDownload() as client:
            result = await client.download(
                url=TEST_SEC_SMALL_FILE,
                file_path=file_path
            )

        # If the server provided an ETag, it should be saved
        if result.etag:
            etag_file = file_path.with_suffix(file_path.suffix + ".etag")
            assert etag_file.exists()
            assert etag_file.read_text().strip() == result.etag

        # Verify the downloaded file exists and has content
        assert file_path.exists()
        assert result.size_bytes > 0

    async def test_download_unsupported_checksum(self, temp_download_dir):
        """Test download raises error for unsupported checksum type."""
        file_path = temp_download_dir / "robots.txt"

        async with StreamingDownload() as client:
            with pytest.raises(ValueError, match="Unsupported checksum type"):
                await client.download(
                    url=TEST_SEC_ROBOTS,
                    file_path=file_path,
                    checksum_type="invalid_algorithm"
                )

    @pytest.mark.timeout(30)
    @pytest.mark.integration
    async def test_progress_callback_real_url(self, temp_download_dir):
        """Test download calls progress callback with real SEC URL."""
        file_path = temp_download_dir / "robots.txt"
        progress_calls = []

        async def progress_callback(current, total):
            progress_calls.append((current, total))

        async with StreamingDownload() as client:
            result = await client.download(
                url=TEST_SEC_ROBOTS,
                file_path=file_path,
                progress_callback=progress_callback
            )

        # Progress callback should have been called
        assert len(progress_calls) > 0
        # Verify final progress matches downloaded size
        last_call = progress_calls[-1]
        assert last_call[0] == result.size_bytes  # Current bytes
        assert last_call[1] == result.size_bytes  # Total bytes
        assert file_path.exists()

    @pytest.mark.timeout(120)  # Large file needs more time
    @pytest.mark.integration
    @pytest.mark.slow
    async def test_download_large_zip_file(self, temp_download_dir):
        """Test downloading a large ZIP file from SEC."""
        file_path = temp_download_dir / "2024q3.zip"

        async with StreamingDownload() as client:
            result = await client.download(
                url=TEST_SEC_ZIP_FILE,
                file_path=file_path
            )

        # Verify ZIP file was downloaded
        assert file_path.exists()
        assert result.size_bytes > 0
        assert result.content_type in ["application/zip", "application/x-zip-compressed"]
        # ZIP files should be large (at least 1MB)
        assert file_path.stat().st_size > 1_000_000


class TestDownloadWithRetry:
    """Test download_with_retry convenience function."""

    @pytest.mark.timeout(30)
    @pytest.mark.integration
    async def test_download_with_retry_success_real_url(self, temp_download_dir):
        """Test successful download with retry using real SEC URL."""
        file_path = temp_download_dir / "robots.txt"

        result = await download_with_retry(
            url=TEST_SEC_ROBOTS,
            file_path=file_path,
            max_retries=3
        )

        assert result.url == TEST_SEC_ROBOTS
        assert result.size_bytes > 0
        assert file_path.exists()
        assert result.file_path == file_path

    async def test_download_with_retry_retries_on_failure(self, temp_download_dir):
        """Test download_with_retry retries on failure."""
        file_path = temp_download_dir / "file.txt"

        with patch("httpdl.streaming.StreamingDownload") as MockStreamingDownload:
            mock_client = AsyncMock()
            # Fail twice, succeed on third attempt
            mock_client.download = AsyncMock(side_effect=[
                DownloadError("Failed 1"),
                DownloadError("Failed 2"),
                StreamingResult(
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
            MockStreamingDownload.return_value.__aenter__.return_value = mock_client

            result = await download_with_retry(
                url="https://example.com/file.txt",
                file_path=file_path,
                max_retries=3
            )

        # Should succeed on third attempt
        assert result.size_bytes == 100
        assert mock_client.download.call_count == 3

    async def test_download_with_retry_max_retries_exceeded(self, temp_download_dir):
        """Test download_with_retry fails after max retries."""
        file_path = temp_download_dir / "file.txt"

        with patch("httpdl.streaming.StreamingDownload") as MockStreamingDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock(side_effect=DownloadError("Always fails"))
            MockStreamingDownload.return_value.__aenter__.return_value = mock_client

            with pytest.raises(DownloadError, match="Always fails"):
                await download_with_retry(
                    url="https://example.com/file.txt",
                    file_path=file_path,
                    max_retries=2
                )

        # Should have tried 2 times
        assert mock_client.download.call_count == 2
