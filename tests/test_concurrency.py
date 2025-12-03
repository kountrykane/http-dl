"""
Tests for batch download operations - BatchDownload and DownloadQueue.
"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from httpdl import BatchDownload, DownloadQueue, DownloadSettings
from httpdl.models.results import DataDownloadResult, FileDownloadResult, BatchDownloadResult
from httpdl.exceptions import DownloadError


@pytest.fixture
def sample_data_result():
    """Sample DataDownloadResult."""
    return DataDownloadResult(
        url="https://example.com/data",
        text="Sample content",
        size_bytes=100,
        kind="text/plain",
        duration_ms=50,
    )


@pytest.fixture
def sample_file_result(tmp_path):
    """Sample FileDownloadResult."""
    file_path = tmp_path / "test.txt"
    file_path.write_text("content")
    return FileDownloadResult(
        url="https://example.com/file",
        file_path=file_path,
        size_bytes=100,
        kind="text/plain",
        duration_ms=50,
    )


class TestBatchResult:
    """Test BatchResult dataclass."""

    def test_success_rate_all_successful(self):
        """Test success_rate with all successful downloads."""
        result = BatchResult(
            successful=[1, 2, 3, 4, 5],
            failed=[],
            total=5,
        )
        assert result.success_rate == 100.0

    def test_success_rate_all_failed(self):
        """Test success_rate with all failed downloads."""
        result = BatchResult(
            successful=[],
            failed=[("url1", Exception()), ("url2", Exception())],
            total=2,
        )
        assert result.success_rate == 0.0

    def test_success_rate_mixed(self):
        """Test success_rate with mixed results."""
        result = BatchResult(
            successful=[1, 2, 3],
            failed=[("url1", Exception()), ("url2", Exception())],
            total=5,
        )
        assert result.success_rate == 60.0

    def test_success_rate_empty(self):
        """Test success_rate with no downloads."""
        result = BatchResult(
            successful=[],
            failed=[],
            total=0,
        )
        assert result.success_rate == 0.0


class TestDownloadBatch:
    """Test download_batch function."""

    @pytest.mark.asyncio
    async def test_download_batch_success(self, sample_data_result):
        """Test download_batch with all successful downloads."""
        urls = [f"https://example.com/{i}" for i in range(5)]

        with patch("httpdl.concurrency.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock(return_value=sample_data_result)
            MockDataDownload.return_value.__aenter__.return_value = mock_client

            result = await download_batch(urls, max_concurrent=3)

        assert len(result.successful) == 5
        assert len(result.failed) == 0
        assert result.total == 5
        assert result.success_rate == 100.0

    @pytest.mark.asyncio
    async def test_download_batch_with_failures(self, sample_data_result):
        """Test download_batch with some failures."""
        urls = [f"https://example.com/{i}" for i in range(5)]

        with patch("httpdl.concurrency.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()

            # Fail on URLs 2 and 4
            def download_side_effect(url):
                if "2" in url or "4" in url:
                    raise DownloadError(f"Failed {url}")
                return sample_data_result

            mock_client.download = AsyncMock(side_effect=download_side_effect)
            MockDataDownload.return_value.__aenter__.return_value = mock_client

            result = await download_batch(urls, max_concurrent=3)

        assert len(result.successful) == 3
        assert len(result.failed) == 2
        assert result.total == 5
        assert result.success_rate == 60.0

    @pytest.mark.asyncio
    async def test_download_batch_callbacks(self, sample_data_result):
        """Test download_batch with success and error callbacks."""
        urls = [f"https://example.com/{i}" for i in range(3)]
        success_calls = []
        error_calls = []

        async def on_success(result):
            success_calls.append(result)

        async def on_error(url, error):
            error_calls.append((url, error))

        with patch("httpdl.concurrency.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()

            def download_side_effect(url):
                if "2" in url:
                    raise DownloadError(f"Failed {url}")
                return sample_data_result

            mock_client.download = AsyncMock(side_effect=download_side_effect)
            MockDataDownload.return_value.__aenter__.return_value = mock_client

            result = await download_batch(
                urls,
                max_concurrent=2,
                on_success=on_success,
                on_error=on_error,
            )

        assert len(success_calls) == 2
        assert len(error_calls) == 1

    @pytest.mark.asyncio
    async def test_download_batch_return_exceptions_false(self, sample_data_result):
        """Test download_batch with return_exceptions=False."""
        urls = [f"https://example.com/{i}" for i in range(3)]

        with patch("httpdl.concurrency.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()

            def download_side_effect(url):
                if "1" in url:
                    raise DownloadError("Test error")
                return sample_data_result

            mock_client.download = AsyncMock(side_effect=download_side_effect)
            MockDataDownload.return_value.__aenter__.return_value = mock_client

            with pytest.raises(DownloadError):
                await download_batch(
                    urls,
                    max_concurrent=2,
                    return_exceptions=False,
                )


class TestDownloadFilesBatch:
    """Test download_files_batch function."""

    @pytest.mark.asyncio
    async def test_download_files_batch_success(self, sample_file_result):
        """Test download_files_batch with successful downloads."""
        urls = [f"https://example.com/file{i}.txt" for i in range(3)]

        with patch("httpdl.concurrency.FileDownload") as MockFileDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock(return_value=sample_file_result)
            MockFileDownload.return_value.__aenter__.return_value = mock_client

            result = await download_files_batch(urls, max_concurrent=2)

        assert len(result.successful) == 3
        assert len(result.failed) == 0
        assert result.success_rate == 100.0

    @pytest.mark.asyncio
    async def test_download_files_batch_with_callback(self, sample_file_result):
        """Test download_files_batch with success callback."""
        urls = [f"https://example.com/file{i}.txt" for i in range(2)]
        callback_calls = []

        async def on_success(result):
            callback_calls.append(result)

        with patch("httpdl.concurrency.FileDownload") as MockFileDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock(return_value=sample_file_result)
            MockFileDownload.return_value.__aenter__.return_value = mock_client

            result = await download_files_batch(
                urls,
                max_concurrent=2,
                on_success=on_success,
            )

        assert len(callback_calls) == 2


class TestMapConcurrent:
    """Test map_concurrent function."""

    @pytest.mark.asyncio
    async def test_map_concurrent_success(self):
        """Test map_concurrent with successful operations."""
        async def multiply_by_two(x):
            await asyncio.sleep(0.01)
            return x * 2

        items = [1, 2, 3, 4, 5]
        results = await map_concurrent(items, multiply_by_two, max_concurrent=3)

        assert results == [2, 4, 6, 8, 10]

    @pytest.mark.asyncio
    async def test_map_concurrent_with_exceptions(self):
        """Test map_concurrent with some exceptions."""
        async def process(x):
            await asyncio.sleep(0.01)
            if x == 3:
                raise ValueError(f"Error for {x}")
            return x * 2

        items = [1, 2, 3, 4, 5]
        results = await map_concurrent(items, process, max_concurrent=3)

        assert len(results) == 5
        assert results[0] == 2
        assert results[1] == 4
        assert isinstance(results[2], ValueError)
        assert results[3] == 8
        assert results[4] == 10

    @pytest.mark.asyncio
    async def test_map_concurrent_order_preserved(self):
        """Test map_concurrent preserves input order."""
        async def slow_for_odd(x):
            if x % 2 == 1:
                await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(0.01)
            return x

        items = [1, 2, 3, 4, 5]
        results = await map_concurrent(items, slow_for_odd, max_concurrent=5)

        assert results == items


class TestRetryFailed:
    """Test retry_failed function."""

    @pytest.mark.asyncio
    async def test_retry_failed_all_succeed(self, sample_data_result):
        """Test retry_failed when all retries succeed."""
        failed = [
            ("https://example.com/1", DownloadError("Temp error")),
            ("https://example.com/2", DownloadError("Temp error")),
        ]

        with patch("httpdl.concurrency.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock(return_value=sample_data_result)
            MockDataDownload.return_value.__aenter__.return_value = mock_client

            result = await retry_failed(failed, max_retries=3, max_concurrent=2)

        assert len(result.successful) == 2
        assert len(result.failed) == 0
        assert result.success_rate == 100.0

    @pytest.mark.asyncio
    async def test_retry_failed_all_fail(self):
        """Test retry_failed when all retries fail."""
        failed = [
            ("https://example.com/1", DownloadError("Permanent error")),
            ("https://example.com/2", DownloadError("Permanent error")),
        ]

        with patch("httpdl.concurrency.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock(side_effect=DownloadError("Still failing"))
            MockDataDownload.return_value.__aenter__.return_value = mock_client

            result = await retry_failed(failed, max_retries=2, max_concurrent=2)

        assert len(result.successful) == 0
        assert len(result.failed) == 2
        assert result.success_rate == 0.0

    @pytest.mark.asyncio
    async def test_retry_failed_succeed_on_second_attempt(self, sample_data_result):
        """Test retry_failed succeeds on second attempt."""
        failed = [("https://example.com/1", DownloadError("Temp error"))]

        with patch("httpdl.concurrency.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()

            # Fail once, then succeed
            mock_client.download = AsyncMock(
                side_effect=[DownloadError("Try 1"), sample_data_result]
            )
            MockDataDownload.return_value.__aenter__.return_value = mock_client

            result = await retry_failed(failed, max_retries=3, max_concurrent=1)

        assert len(result.successful) == 1
        assert len(result.failed) == 0

    @pytest.mark.asyncio
    async def test_retry_failed_exponential_backoff(self, sample_data_result):
        """Test retry_failed uses exponential backoff."""
        failed = [("https://example.com/1", DownloadError("Error"))]

        with patch("httpdl.concurrency.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()

            # Fail twice, succeed on third
            mock_client.download = AsyncMock(
                side_effect=[
                    DownloadError("Try 1"),
                    DownloadError("Try 2"),
                    sample_data_result,
                ]
            )
            MockDataDownload.return_value.__aenter__.return_value = mock_client

            with patch("asyncio.sleep") as mock_sleep:
                result = await retry_failed(failed, max_retries=3, max_concurrent=1)

                # Check exponential backoff was used
                assert mock_sleep.call_count == 2
                # First backoff: 2^0 = 1 second
                # Second backoff: 2^1 = 2 seconds


class TestDownloadQueue:
    """Test DownloadQueue class."""

    @pytest.mark.asyncio
    async def test_download_queue_basic(self, sample_data_result):
        """Test basic DownloadQueue usage."""
        queue = DownloadQueue(max_concurrent=2)
        urls = [f"https://example.com/{i}" for i in range(3)]

        with patch("httpdl.concurrency.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock(return_value=sample_data_result)
            MockDataDownload.return_value.__aenter__.return_value = mock_client

            # Producer
            async def add_urls():
                for url in urls:
                    await queue.add(url)
                await queue.finish()

            # Run producer and consumer
            await asyncio.gather(add_urls(), queue.start())

        result = queue.get_results()
        assert len(result.successful) == 3
        assert len(result.failed) == 0
        assert result.success_rate == 100.0

    @pytest.mark.asyncio
    async def test_download_queue_with_errors(self, sample_data_result):
        """Test DownloadQueue handles errors correctly."""
        queue = DownloadQueue(max_concurrent=2)
        urls = [f"https://example.com/{i}" for i in range(3)]

        with patch("httpdl.concurrency.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()

            def download_side_effect(url):
                if "1" in url:
                    raise DownloadError("Error")
                return sample_data_result

            mock_client.download = AsyncMock(side_effect=download_side_effect)
            MockDataDownload.return_value.__aenter__.return_value = mock_client

            async def add_urls():
                for url in urls:
                    await queue.add(url)
                await queue.finish()

            await asyncio.gather(add_urls(), queue.start())

        result = queue.get_results()
        assert len(result.successful) == 2
        assert len(result.failed) == 1

    @pytest.mark.asyncio
    async def test_download_queue_dynamic_discovery(self, sample_data_result):
        """Test DownloadQueue with dynamic URL discovery."""
        queue = DownloadQueue(max_concurrent=2)

        with patch("httpdl.concurrency.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock(return_value=sample_data_result)
            MockDataDownload.return_value.__aenter__.return_value = mock_client

            # Simulate discovering URLs over time
            async def discover_urls():
                for i in range(5):
                    await asyncio.sleep(0.01)  # Simulate discovery delay
                    await queue.add(f"https://example.com/{i}")
                await queue.finish()

            await asyncio.gather(discover_urls(), queue.start())

        result = queue.get_results()
        assert len(result.successful) == 5
        assert result.total == 5

    @pytest.mark.asyncio
    async def test_download_queue_empty(self):
        """Test DownloadQueue with no URLs."""
        queue = DownloadQueue(max_concurrent=2)

        with patch("httpdl.concurrency.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            MockDataDownload.return_value.__aenter__.return_value = mock_client

            async def finish_immediately():
                await queue.finish()

            await asyncio.gather(finish_immediately(), queue.start())

        result = queue.get_results()
        assert len(result.successful) == 0
        assert len(result.failed) == 0
        assert result.total == 0
