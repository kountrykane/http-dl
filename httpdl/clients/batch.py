from __future__ import annotations

import time
from typing import List, Optional, Callable, Any, TypeVar, Awaitable

from ..models.config import DownloadSettings
from ..clients.data import DataDownload
from ..clients.file import FileDownload
from ..models.results import BatchDownloadResult
from ..observability.logging import get_httpdl_logger, log_exception, HttpdlLoggerAdapter

T = TypeVar("T")



class BatchDownload:
    """
    Convenience class for batch download operations.

    Provides a clean API for downloading multiple URLs concurrently with
    automatic client management and progress tracking.

    Example:
        # Data downloads
        batch = BatchDownload(download_type="data", max_concurrent=10)
        result = await batch.download(
            urls=["https://example.com/1", "https://example.com/2"],
            on_success=lambda r: print(f"✓ {r.url}"),
            on_error=lambda url, e: print(f"✗ {url}: {e}")
        )
        print(f"Success rate: {result.success_rate:.1f}%")

        # File downloads
        batch = BatchDownload(download_type="file", max_concurrent=5)
        result = await batch.download(
            urls=["https://example.com/file1.zip", "https://example.com/file2.zip"],
            on_success=lambda r: print(f"Saved {r.file_path}")
        )
    """

    def __init__(
        self,
        download_type: str = "data",
        settings: Optional[DownloadSettings] = None,
        max_concurrent: int = 10,
    ):
        """
        Initialize BatchDownload.

        Args:
            download_type: Type of downloads - "data" or "file"
            settings: Download settings (shared across all downloads)
            max_concurrent: Maximum concurrent downloads
        """
        if download_type not in ("data", "file"):
            raise ValueError(f"download_type must be 'data' or 'file', got: {download_type}")

        self.download_type = download_type
        self.settings = settings
        self.max_concurrent = max_concurrent
        self._logger = (settings.logger if settings else None) or get_httpdl_logger(__name__)

        self._logger.info(
            "batch_download.initialized",
            download_type=download_type,
            max_concurrent=max_concurrent
        )

    async def download(
        self,
        urls: List[str],
        on_success: Optional[Callable[[Any], Awaitable[None]]] = None,
        on_error: Optional[Callable[[str, Exception], Awaitable[None]]] = None,
        return_exceptions: bool = True,
        **download_kwargs,
    ) -> BatchDownloadResult:
        """
        Download multiple URLs concurrently.

        Args:
            urls: List of URLs to download
            on_success: Optional callback for successful downloads
            on_error: Optional callback for failed downloads
            return_exceptions: If True, exceptions are collected; if False, first exception is raised
            **download_kwargs: Additional arguments passed to download() method

        Returns:
            BatchDownloadResult with successful and failed downloads

        Example:
            batch = BatchDownload(download_type="file")
            result = await batch.download(
                urls=["https://example.com/file1.zip"],
                checksum_type="sha256",
                resume=True
            )
        """
        self._logger.info(
            "batch_download.started",
            download_type=self.download_type,
            total_urls=len(urls),
            max_concurrent=self.max_concurrent
        )
        start_time = time.perf_counter()

        try:
            if self.download_type == "data":
                async with DataDownload(self.settings) as client:
                    result = await client.download_batch(
                        urls=urls,
                        max_concurrent=self.max_concurrent,
                        on_success=on_success,
                        on_error=on_error,
                        return_exceptions=return_exceptions,
                    )
            else:  # file
                async with FileDownload(self.settings) as client:
                    result = await client.download_batch(
                        urls=urls,
                        max_concurrent=self.max_concurrent,
                        on_success=on_success,
                        on_error=on_error,
                        return_exceptions=return_exceptions,
                    )

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            self._logger.info(
                "batch_download.completed",
                download_type=self.download_type,
                total_urls=len(urls),
                successful=len(result.successful),
                failed=len(result.failed),
                success_rate=result.success_rate,
                duration_ms=duration_ms
            )

            return result

        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            log_exception(
                self._logger,
                exc,
                "batch_download.failed",
                download_type=self.download_type,
                total_urls=len(urls),
                duration_ms=duration_ms
            )
            raise
