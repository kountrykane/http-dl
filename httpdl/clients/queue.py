from __future__ import annotations

import asyncio
import time
from typing import List, Optional, Callable, Any, TypeVar, Awaitable

from ..models.config import DownloadSettings
from ..clients.data import DataDownload
from ..clients.file import FileDownload
from ..models.results import BatchDownloadResult
from ..observability.logging import get_httpdl_logger, log_exception, HttpdlLoggerAdapter

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
        download_type: str = "data",
    ):
        """
        Initialize DownloadQueue.

        Args:
            settings: Download settings
            max_concurrent: Maximum concurrent downloads
            download_type: Type of downloads - "data" or "file"
        """
        self.settings = settings
        self.max_concurrent = max_concurrent
        self.download_type = download_type
        self._queue: asyncio.Queue = asyncio.Queue()
        self._results: List[Any] = []
        self._errors: List[tuple[str, Exception]] = []
        self._finished = asyncio.Event()
        self._workers: List[asyncio.Task] = []
        self._logger = (settings.logger if settings else None) or get_httpdl_logger(__name__)
        self._start_time: Optional[float] = None
        self._total_added = 0

        self._logger.info(
            "download_queue.initialized",
            max_concurrent=max_concurrent,
            download_type=download_type
        )

    async def add(self, url: str) -> None:
        """Add a URL to the download queue."""
        await self._queue.put(url)
        self._total_added += 1
        self._logger.debug(
            "download_queue.url_added",
            url=url,
            queue_size=self._queue.qsize(),
            total_added=self._total_added
        )

    async def finish(self) -> None:
        """Signal that no more URLs will be added."""
        self._finished.set()
        self._logger.info(
            "download_queue.finished_signal",
            total_urls_added=self._total_added,
            pending_in_queue=self._queue.qsize()
        )

    async def start(self) -> None:
        """Start processing the queue."""
        self._logger.info(
            "download_queue.started",
            download_type=self.download_type,
            max_concurrent=self.max_concurrent
        )
        self._start_time = time.perf_counter()

        try:
            if self.download_type == "data":
                async with DataDownload(self.settings) as client:
                    await self._process_queue(client)
            else:
                async with FileDownload(self.settings) as client:
                    await self._process_queue(client)

            duration_ms = int((time.perf_counter() - self._start_time) * 1000)
            self._logger.info(
                "download_queue.completed",
                total_processed=len(self._results) + len(self._errors),
                successful=len(self._results),
                failed=len(self._errors),
                duration_ms=duration_ms
            )

        except Exception as exc:
            duration_ms = int((time.perf_counter() - (self._start_time or time.perf_counter())) * 1000)
            log_exception(
                self._logger,
                exc,
                "download_queue.failed",
                total_processed=len(self._results) + len(self._errors),
                duration_ms=duration_ms
            )
            raise

    async def _process_queue(self, client) -> None:
        """Process queue with given client."""
        # Create worker tasks
        self._workers = [
            asyncio.create_task(self._worker(client, worker_id=i))
            for i in range(self.max_concurrent)
        ]

        self._logger.debug(
            "download_queue.workers_created",
            worker_count=len(self._workers)
        )

        # Wait for all work to complete
        await self._finished.wait()
        await self._queue.join()

        self._logger.debug(
            "download_queue.queue_empty",
            total_processed=len(self._results) + len(self._errors)
        )

        # Cancel workers
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)

        self._logger.debug("download_queue.workers_cancelled")

    async def _worker(self, client, worker_id: int) -> None:
        """Worker that processes URLs from the queue."""
        self._logger.debug(
            "download_queue.worker_started",
            worker_id=worker_id
        )

        while True:
            try:
                url = await self._queue.get()
                self._logger.debug(
                    "download_queue.worker_processing",
                    worker_id=worker_id,
                    url=url,
                    queue_size=self._queue.qsize()
                )

                try:
                    result = await client.download(url)
                    self._results.append(result)
                    self._logger.debug(
                        "download_queue.worker_success",
                        worker_id=worker_id,
                        url=url,
                        total_completed=len(self._results)
                    )
                except Exception as exc:
                    self._errors.append((url, exc))
                    log_exception(
                        self._logger,
                        exc,
                        "download_queue.worker_error",
                        worker_id=worker_id,
                        url=url,
                        total_failed=len(self._errors)
                    )
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                self._logger.debug(
                    "download_queue.worker_cancelled",
                    worker_id=worker_id
                )
                break

    def get_results(self) -> BatchDownloadResult:
        """Get all download results."""
        result = BatchDownloadResult(
            successful=self._results,
            failed=self._errors,
            total=len(self._results) + len(self._errors),
        )

        self._logger.info(
            "download_queue.results_retrieved",
            total=result.total,
            successful=len(result.successful),
            failed=len(result.failed),
            success_rate=result.success_rate
        )

        return result
