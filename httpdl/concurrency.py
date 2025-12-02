"""
Concurrency utilities for batch download operations.

This module provides helper functions for efficiently downloading multiple URLs
with proper concurrency control, error handling, and progress tracking.
"""

from __future__ import annotations

import asyncio
from typing import List, Optional, Callable, Any, TypeVar, Awaitable
from dataclasses import dataclass

from .download import DataDownload, FileDownload
from .config import DownloadSettings
from .models import DataDownloadResult, FileDownloadResult
from .exceptions import DownloadError

T = TypeVar("T")


@dataclass
class BatchResult:
    """Result of a batch download operation."""

    successful: List[Any]
    failed: List[tuple[str, Exception]]
    total: int

    @property
    def success_rate(self) -> float:
        """Calculate success rate as a percentage."""
        if self.total == 0:
            return 0.0
        return (len(self.successful) / self.total) * 100


async def download_batch(
    urls: List[str],
    settings: Optional[DownloadSettings] = None,
    max_concurrent: int = 10,
    on_success: Optional[Callable[[DataDownloadResult], Awaitable[None]]] = None,
    on_error: Optional[Callable[[str, Exception], Awaitable[None]]] = None,
    return_exceptions: bool = True,
) -> BatchResult:
    """
    Download multiple URLs concurrently with controlled concurrency.

    Args:
        urls: List of URLs to download
        settings: Download settings (shared across all downloads)
        max_concurrent: Maximum concurrent downloads
        on_success: Optional callback for successful downloads
        on_error: Optional callback for failed downloads
        return_exceptions: If True, exceptions are collected; if False, first exception is raised

    Returns:
        BatchResult with successful and failed downloads

    Example:
        async def process_success(result):
            print(f"Downloaded {result.url}: {result.size_bytes} bytes")

        async def process_error(url, error):
            print(f"Failed {url}: {error}")

        result = await download_batch(
            urls=["https://example.com/1", "https://example.com/2"],
            max_concurrent=5,
            on_success=process_success,
            on_error=process_error
        )

        print(f"Success rate: {result.success_rate:.1f}%")
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    successful: List[DataDownloadResult] = []
    failed: List[tuple[str, Exception]] = []

    async def download_one(url: str, client: DataDownload) -> None:
        """Download a single URL with semaphore control."""
        async with semaphore:
            try:
                result = await client.download(url)
                successful.append(result)
                if on_success:
                    await on_success(result)
            except Exception as exc:
                failed.append((url, exc))
                if on_error:
                    await on_error(url, exc)
                if not return_exceptions:
                    raise

    # Create client and download all URLs
    async with DataDownload(settings) as client:
        tasks = [download_one(url, client) for url in urls]
        await asyncio.gather(*tasks, return_exceptions=return_exceptions)

    return BatchResult(
        successful=successful,
        failed=failed,
        total=len(urls),
    )


async def download_files_batch(
    urls: List[str],
    settings: Optional[DownloadSettings] = None,
    max_concurrent: int = 10,
    on_success: Optional[Callable[[FileDownloadResult], Awaitable[None]]] = None,
    on_error: Optional[Callable[[str, Exception], Awaitable[None]]] = None,
    return_exceptions: bool = True,
) -> BatchResult:
    """
    Download multiple files concurrently with controlled concurrency.

    Args:
        urls: List of URLs to download
        settings: Download settings (shared across all downloads)
        max_concurrent: Maximum concurrent downloads
        on_success: Optional callback for successful downloads
        on_error: Optional callback for failed downloads
        return_exceptions: If True, exceptions are collected; if False, first exception is raised

    Returns:
        BatchResult with successful and failed downloads

    Example:
        async def process_success(result):
            print(f"Saved {result.file_path}: {result.size_bytes} bytes")

        result = await download_files_batch(
            urls=["https://example.com/file1.pdf", "https://example.com/file2.zip"],
            max_concurrent=5,
            on_success=process_success
        )
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    successful: List[FileDownloadResult] = []
    failed: List[tuple[str, Exception]] = []

    async def download_one(url: str, client: FileDownload) -> None:
        """Download a single file with semaphore control."""
        async with semaphore:
            try:
                result = await client.download(url)
                successful.append(result)
                if on_success:
                    await on_success(result)
            except Exception as exc:
                failed.append((url, exc))
                if on_error:
                    await on_error(url, exc)
                if not return_exceptions:
                    raise

    # Create client and download all files
    async with FileDownload(settings) as client:
        tasks = [download_one(url, client) for url in urls]
        await asyncio.gather(*tasks, return_exceptions=return_exceptions)

    return BatchResult(
        successful=successful,
        failed=failed,
        total=len(urls),
    )


async def map_concurrent(
    items: List[T],
    async_func: Callable[[T], Awaitable[Any]],
    max_concurrent: int = 10,
    return_exceptions: bool = True,
) -> List[Any]:
    """
    Map an async function over a list of items with controlled concurrency.

    Similar to asyncio.gather but with a concurrency limit.

    Args:
        items: List of items to process
        async_func: Async function to apply to each item
        max_concurrent: Maximum concurrent operations
        return_exceptions: If True, exceptions are returned in results

    Returns:
        List of results (in same order as input items)

    Example:
        async def process_url(url: str) -> int:
            async with DataDownload() as client:
                result = await client.download(url)
                return result.size_bytes

        sizes = await map_concurrent(
            urls,
            process_url,
            max_concurrent=5
        )
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_one(item: T) -> Any:
        async with semaphore:
            return await async_func(item)

    tasks = [process_one(item) for item in items]
    return await asyncio.gather(*tasks, return_exceptions=return_exceptions)


async def retry_failed(
    failed: List[tuple[str, Exception]],
    settings: Optional[DownloadSettings] = None,
    max_retries: int = 3,
    max_concurrent: int = 5,
) -> BatchResult:
    """
    Retry failed downloads with exponential backoff.

    Args:
        failed: List of (url, exception) tuples from previous batch
        settings: Download settings
        max_retries: Maximum retry attempts per URL
        max_concurrent: Maximum concurrent retry operations

    Returns:
        BatchResult with retry outcomes

    Example:
        # Initial batch download
        result = await download_batch(urls)

        # Retry failures
        if result.failed:
            retry_result = await retry_failed(
                result.failed,
                max_retries=3
            )
            print(f"Recovered {len(retry_result.successful)} failures")
    """
    successful: List[DataDownloadResult] = []
    still_failed: List[tuple[str, Exception]] = []

    semaphore = asyncio.Semaphore(max_concurrent)

    async def retry_one(url: str, client: DataDownload) -> None:
        """Retry a single URL with exponential backoff."""
        async with semaphore:
            for attempt in range(max_retries):
                try:
                    result = await client.download(url)
                    successful.append(result)
                    return
                except Exception as exc:
                    if attempt == max_retries - 1:
                        still_failed.append((url, exc))
                    else:
                        # Exponential backoff
                        await asyncio.sleep(2 ** attempt)

    # Extract URLs from failed list
    retry_urls = [url for url, _ in failed]

    async with DataDownload(settings) as client:
        tasks = [retry_one(url, client) for url in retry_urls]
        await asyncio.gather(*tasks, return_exceptions=True)

    return BatchResult(
        successful=successful,
        failed=still_failed,
        total=len(retry_urls),
    )


class DownloadQueue:
    """
    Async queue for processing download tasks with concurrency control.

    Useful for producer-consumer patterns where URLs are discovered
    dynamically and need to be downloaded.

    Example:
        queue = DownloadQueue(max_concurrent=10)

        # Producer
        async def discover_urls():
            for url in discover_process():
                await queue.add(url)
            await queue.finish()

        # Consumer processes automatically
        await asyncio.gather(
            discover_urls(),
            queue.start()
        )

        results = queue.get_results()
    """

    def __init__(
        self,
        settings: Optional[DownloadSettings] = None,
        max_concurrent: int = 10,
    ):
        self.settings = settings
        self.max_concurrent = max_concurrent
        self._queue: asyncio.Queue = asyncio.Queue()
        self._results: List[DataDownloadResult] = []
        self._errors: List[tuple[str, Exception]] = []
        self._finished = asyncio.Event()
        self._workers: List[asyncio.Task] = []

    async def add(self, url: str) -> None:
        """Add a URL to the download queue."""
        await self._queue.put(url)

    async def finish(self) -> None:
        """Signal that no more URLs will be added."""
        self._finished.set()

    async def start(self) -> None:
        """Start processing the queue."""
        async with DataDownload(self.settings) as client:
            # Create worker tasks
            self._workers = [
                asyncio.create_task(self._worker(client))
                for _ in range(self.max_concurrent)
            ]

            # Wait for all work to complete
            await self._finished.wait()
            await self._queue.join()

            # Cancel workers
            for worker in self._workers:
                worker.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)

    async def _worker(self, client: DataDownload) -> None:
        """Worker that processes URLs from the queue."""
        while True:
            try:
                url = await self._queue.get()
                try:
                    result = await client.download(url)
                    self._results.append(result)
                except Exception as exc:
                    self._errors.append((url, exc))
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break

    def get_results(self) -> BatchResult:
        """Get all download results."""
        return BatchResult(
            successful=self._results,
            failed=self._errors,
            total=len(self._results) + len(self._errors),
        )
