"""
Tests for BatchDownload and DownloadQueue classes.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from httpdl import BatchDownload, DownloadQueue, DownloadSettings
from httpdl.exceptions import DownloadError
from httpdl.models.results import BatchDownloadResult, DataDownloadResult, FileDownloadResult


@pytest.fixture
def sample_data_result():
    """Sample DataDownloadResult used across tests."""
    return DataDownloadResult(
        url="https://example.com/data",
        text="Sample content",
        size_bytes=128,
        kind="json",
        duration_ms=42,
    )


@pytest.fixture
def sample_file_result(tmp_path: Path):
    """Sample FileDownloadResult with a real file on disk."""
    file_path = tmp_path / "example.txt"
    file_path.write_text("content")
    return FileDownloadResult(
        url="https://example.com/file.txt",
        file_path=file_path,
        size_bytes=file_path.stat().st_size,
        duration_ms=50,
        saved_to_disk=True,
    )


class TestBatchDownloadResult:
    """Behavioural tests for BatchDownloadResult helper."""

    def test_success_rate_all_successful(self):
        result = BatchDownloadResult(successful=[1, 2, 3], failed=[], total=3)
        assert result.success_rate == 100.0

    def test_success_rate_all_failed(self):
        result = BatchDownloadResult(
            successful=[],
            failed=[("url1", Exception()), ("url2", Exception())],
            total=2,
        )
        assert result.success_rate == 0.0

    def test_success_rate_mixed(self):
        result = BatchDownloadResult(
            successful=[1, 2],
            failed=[("url3", Exception())],
            total=3,
        )
        assert result.success_rate == pytest.approx(66.666, rel=1e-3)

    def test_success_rate_empty_total(self):
        result = BatchDownloadResult(successful=[], failed=[], total=0)
        assert result.success_rate == 0.0


class TestBatchDownloadData:
    """Tests for BatchDownload when download_type='data'."""

    @pytest.mark.asyncio
    async def test_download_success(self, sample_data_result):
        urls = [f"https://example.com/{i}" for i in range(3)]
        fake_result = BatchDownloadResult(
            successful=[sample_data_result] * 3,
            failed=[],
            total=3,
        )

        with patch("httpdl.clients.batch.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            mock_client.download_batch = AsyncMock(return_value=fake_result)
            MockDataDownload.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockDataDownload.return_value.__aexit__ = AsyncMock(return_value=None)

            batch = BatchDownload(download_type="data", max_concurrent=5)
            result = await batch.download(urls)

        MockDataDownload.assert_called_once_with(None)
        mock_client.download_batch.assert_awaited_once_with(
            urls=urls,
            max_concurrent=5,
            on_success=None,
            on_error=None,
            return_exceptions=True,
        )
        assert result is fake_result

    @pytest.mark.asyncio
    async def test_download_uses_provided_settings(self, sample_data_result):
        urls = ["https://example.com/a"]
        fake_result = BatchDownloadResult(successful=[sample_data_result], failed=[], total=1)
        settings = DownloadSettings(requests_per_second=5)

        with patch("httpdl.clients.batch.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            mock_client.download_batch = AsyncMock(return_value=fake_result)
            MockDataDownload.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockDataDownload.return_value.__aexit__ = AsyncMock(return_value=None)

            batch = BatchDownload(download_type="data", settings=settings, max_concurrent=2)
            await batch.download(urls)

        MockDataDownload.assert_called_once_with(settings)

    @pytest.mark.asyncio
    async def test_download_passes_callbacks(self, sample_data_result):
        urls = ["https://example.com/success", "https://example.com/error"]
        successes, errors = [], []

        async def on_success(result):
            successes.append(result.url)

        async def on_error(url, exc):
            errors.append((url, str(exc)))

        async def fake_download_batch(**kwargs):
            await kwargs["on_success"](sample_data_result)
            await kwargs["on_error"]("https://example.com/error", DownloadError("boom"))
            return BatchDownloadResult(
                successful=[sample_data_result],
                failed=[("https://example.com/error", DownloadError("boom"))],
                total=2,
            )

        with patch("httpdl.clients.batch.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            mock_client.download_batch = AsyncMock(side_effect=fake_download_batch)
            MockDataDownload.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockDataDownload.return_value.__aexit__ = AsyncMock(return_value=None)

            batch = BatchDownload(download_type="data", max_concurrent=2)
            await batch.download(
                urls,
                on_success=on_success,
                on_error=on_error,
            )

        assert successes == [sample_data_result.url]
        assert errors == [("https://example.com/error", "boom")]

    @pytest.mark.asyncio
    async def test_download_propagates_errors(self):
        urls = ["https://example.com/fail"]

        with patch("httpdl.clients.batch.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            mock_client.download_batch = AsyncMock(side_effect=DownloadError("nope"))
            MockDataDownload.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockDataDownload.return_value.__aexit__ = AsyncMock(return_value=None)

            batch = BatchDownload(download_type="data")

            with pytest.raises(DownloadError):
                await batch.download(urls)


class TestBatchDownloadFile:
    """Tests for BatchDownload when download_type='file'."""

    @pytest.mark.asyncio
    async def test_file_download_success(self, sample_file_result):
        urls = [f"https://example.com/file{i}.txt" for i in range(2)]
        fake_result = BatchDownloadResult(
            successful=[sample_file_result] * 2,
            failed=[],
            total=2,
        )

        with patch("httpdl.clients.batch.FileDownload") as MockFileDownload:
            mock_client = AsyncMock()
            mock_client.download_batch = AsyncMock(return_value=fake_result)
            MockFileDownload.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockFileDownload.return_value.__aexit__ = AsyncMock(return_value=None)

            batch = BatchDownload(download_type="file", max_concurrent=3)
            result = await batch.download(urls, resume=True)

        MockFileDownload.assert_called_once_with(None)
        mock_client.download_batch.assert_awaited_once()
        assert result is fake_result

    def test_invalid_download_type(self):
        with pytest.raises(ValueError):
            BatchDownload(download_type="unknown")


class TestDownloadQueue:
    """Integration-style tests for DownloadQueue."""

    @pytest.mark.asyncio
    async def test_queue_processes_all_urls(self, sample_data_result):
        queue = DownloadQueue(max_concurrent=2, download_type="data")
        urls = [f"https://example.com/{i}" for i in range(3)]

        with patch("httpdl.clients.queue.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock(return_value=sample_data_result)
            MockDataDownload.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockDataDownload.return_value.__aexit__ = AsyncMock(return_value=None)

            async def producer():
                for url in urls:
                    await queue.add(url)
                await queue.finish()

            await asyncio.gather(producer(), queue.start())

        result = queue.get_results()
        assert len(result.successful) == len(urls)
        assert result.failed == []
        assert result.success_rate == 100.0

    @pytest.mark.asyncio
    async def test_queue_records_failures(self, sample_data_result):
        queue = DownloadQueue(max_concurrent=2, download_type="data")
        urls = [f"https://example.com/{i}" for i in range(3)]

        async def download_side_effect(url):
            if url.endswith("1"):
                raise DownloadError("boom")
            return sample_data_result

        with patch("httpdl.clients.queue.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock(side_effect=download_side_effect)
            MockDataDownload.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockDataDownload.return_value.__aexit__ = AsyncMock(return_value=None)

            async def producer():
                for url in urls:
                    await queue.add(url)
                await queue.finish()

            await asyncio.gather(producer(), queue.start())

        result = queue.get_results()
        assert len(result.successful) == 2
        assert len(result.failed) == 1
        assert any("boom" in str(err) for _, err in result.failed)

    @pytest.mark.asyncio
    async def test_queue_dynamic_discovery(self, sample_data_result):
        queue = DownloadQueue(max_concurrent=1, download_type="data")

        with patch("httpdl.clients.queue.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock(return_value=sample_data_result)
            MockDataDownload.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockDataDownload.return_value.__aexit__ = AsyncMock(return_value=None)

            async def discover():
                for i in range(4):
                    await asyncio.sleep(0)
                    await queue.add(f"https://example.com/{i}")
                await queue.finish()

            await asyncio.gather(discover(), queue.start())

        result = queue.get_results()
        assert result.total == 4
        assert len(result.successful) == 4

    @pytest.mark.asyncio
    async def test_queue_supports_file_downloads(self, sample_file_result):
        queue = DownloadQueue(max_concurrent=1, download_type="file")

        with patch("httpdl.clients.queue.FileDownload") as MockFileDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock(return_value=sample_file_result)
            MockFileDownload.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockFileDownload.return_value.__aexit__ = AsyncMock(return_value=None)

            async def producer():
                await queue.add("https://example.com/file.txt")
                await queue.finish()

            await asyncio.gather(producer(), queue.start())

        result = queue.get_results()
        assert len(result.successful) == 1
        assert result.failed == []

    @pytest.mark.asyncio
    async def test_queue_handles_finish_without_urls(self):
        queue = DownloadQueue(max_concurrent=2, download_type="data")

        with patch("httpdl.clients.queue.DataDownload") as MockDataDownload:
            mock_client = AsyncMock()
            mock_client.download = AsyncMock()
            MockDataDownload.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockDataDownload.return_value.__aexit__ = AsyncMock(return_value=None)

            async def finisher():
                await queue.finish()

            await asyncio.gather(finisher(), queue.start())

        result = queue.get_results()
        assert result.total == 0
        assert result.successful == []
        assert result.failed == []
