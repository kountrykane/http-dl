from __future__ import annotations
import time
import asyncio
import hashlib
from typing import Optional, Union, Callable, Awaitable, List
from pathlib import Path
import os
import aiofiles

import httpx

from .utils import maybe_await, ensure_async_iterator

from .base import BaseDownload
from ..models.config import DownloadSettings
from ..models.results import (
    FileDownloadResult, 
    BatchDownloadResult
)
from ..utils import (
    normalize_content_type,
    extract_charset,
    classify_kind,
    decode_text,
    decompress_transfer,
)
from ..exceptions import (
    InvalidURLError,
    PayloadSizeLimitError,
    DecompressionError,
    DownloadError,
    classify_http_error,
)
from ..observability.logging import (
    get_httpdl_logger,
    log_content_processing,
    log_exception,
    log_timing,
    log_retry,
    HttpdlLoggerAdapter,
)

class FileDownload(BaseDownload):
    """
    Asynchronous download client for files with streaming, resumable downloads,
    and checksum validation.

    Features:
    - Streaming to disk for large files
    - Resumable downloads using Range headers and ETags
    - Checksum validation (MD5, SHA256, SHA512)
    - HEAD request precheck for content size
    - Progress callbacks
    - Batch downloads

    Example:
        # Basic download
        async with FileDownload() as client:
            result = await client.download(
                url="https://example.com/file.zip",
                file_path=Path("downloads/file.zip")
            )

        # Resumable download with checksum
        async with FileDownload() as client:
            result = await client.download(
                url="https://example.com/large.zip",
                file_path=Path("downloads/large.zip"),
                checksum_type="sha256",
                expected_checksum="abc123...",
                resume=True,
                progress_callback=lambda curr, total: print(f"{curr}/{total}")
            )
    """

    def __init__(
        self,
        settings: Optional[DownloadSettings] = None,
        download_dir: Optional[Path] = None
    ):
        """
        Initialize FileDownload client.

        Args:
            settings: Download settings
            download_dir: Default directory to save files
        """
        super().__init__(settings)
        self.download_dir = download_dir or Path("downloads")
        if self.download_dir:
            self.download_dir.mkdir(parents=True, exist_ok=True)
            self._logger.info(
                "file_download.initialized",
                download_dir=str(self.download_dir),
                max_connections=self.settings.max_connections,
                http2=self.settings.http2
            )

        # Checksum algorithms
        self._checksums = {
            "md5": hashlib.md5,
            "sha256": hashlib.sha256,
            "sha512": hashlib.sha512,
        }

    async def head_request(self, url: str) -> dict:
        """
        Perform HEAD request to get file metadata before download.

        Args:
            url: URL to check

        Returns:
            Dict with metadata: content_length, etag, content_type, accept_ranges

        Raises:
            InvalidURLError: If URL is empty
            DownloadError: If HEAD request fails
        """
        if not url or not url.strip():
            self._logger.error("head_request.invalid_url", url=url)
            raise InvalidURLError(message="URL cannot be empty", url=url)

        self._logger.debug("head_request.started", url=url)
        start_time = time.perf_counter()

        await self._apply_rate_limit()
        host = self._get_host_from_url(url)
        sem = self._sem_for_host(host)

        async with sem:
            resp, _ = await self._do_request_with_retry("HEAD", url)

        metadata = {
            "content_length": int(resp.headers.get("Content-Length", 0)),
            "etag": resp.headers.get("ETag"),
            "content_type": resp.headers.get("Content-Type"),
            "accept_ranges": resp.headers.get("Accept-Ranges") == "bytes",
            "last_modified": resp.headers.get("Last-Modified"),
        }

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        self._logger.info(
            "head_request.completed",
            url=url,
            content_length=metadata["content_length"],
            accept_ranges=metadata["accept_ranges"],
            duration_ms=duration_ms
        )

        await resp.aclose()
        return metadata

    async def download(
        self,
        url: str,
        file_path: Optional[Path] = None,
        checksum_type: Optional[str] = None,
        expected_checksum: Optional[str] = None,
        chunk_size: int = 65536,
        resume: bool = True,
        progress_callback: Optional[Callable[[int, int], Awaitable[None]]] = None,
        stream_to_disk: bool = True,
    ) -> FileDownloadResult:
        """
        Download file with optional resumable support and checksum validation.

        Args:
            url: URL to download
            file_path: Path to save file (auto-generated if not provided)
            checksum_type: Checksum algorithm ("md5", "sha256", "sha512")
            expected_checksum: Expected checksum value for validation
            chunk_size: Size of download chunks in bytes
            resume: Whether to resume partial downloads
            progress_callback: Optional async callback(current_bytes, total_bytes)
            stream_to_disk: Whether to stream to disk (True) or load to memory (False)

        Returns:
            FileDownloadResult with download metadata

        Raises:
            InvalidURLError: If URL is empty
            DownloadError: On download or validation failure
            ValueError: If checksum_type is unsupported

        Example:
            async def progress(current, total):
                print(f"Progress: {current}/{total} ({current/total*100:.1f}%)")

            async with FileDownload() as client:
                result = await client.download(
                    url="https://example.com/file.zip",
                    file_path=Path("downloads/file.zip"),
                    checksum_type="sha256",
                    expected_checksum="abc123...",
                    resume=True,
                    progress_callback=progress
                )
        """
        if not url or not url.strip():
            self._logger.error("file_download.invalid_url", url=url)
            raise InvalidURLError(
                message="URL cannot be empty",
                url=url,
            )

        self._logger.info(
            "file_download.started",
            url=url,
            file_path=str(file_path) if file_path else "auto",
            resume=resume,
            checksum_type=checksum_type
        )
        start_time = time.perf_counter()

        # Generate file path if not provided
        if file_path is None:
            url_path = httpx.URL(url).path
            if url_path:
                filename = os.path.basename(url_path)
                if not filename or filename == "/":
                    filename = f"download_{int(time.time())}.bin"
            else:
                filename = f"download_{int(time.time())}.bin"
            file_path = self.download_dir / filename
            self._logger.debug("file_download.path_generated", file_path=str(file_path), filename=filename)

        # Create parent directories
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if we can resume
        resume_position = 0
        resumed = False
        saved_etag = None

        if resume and file_path.exists():
            resume_position = file_path.stat().st_size
            # Try to load saved ETag from sidecar file
            etag_file = file_path.with_suffix(file_path.suffix + ".etag")
            if etag_file.exists():
                saved_etag = etag_file.read_text().strip()

        # Get file metadata via HEAD request
        metadata = await self.head_request(url)
        total_size = metadata["content_length"]
        etag = metadata["etag"]
        content_type = metadata["content_type"]

        # Validate resume conditions
        if resume_position > 0:
            if not metadata["accept_ranges"]:
                self._logger.warning(
                    "file_download.resume_not_supported",
                    url=url,
                    file_path=str(file_path),
                )
                resume_position = 0
            elif saved_etag and etag and saved_etag != etag:
                self._logger.warning(
                    "file_download.etag_mismatch",
                    url=url,
                    saved_etag=saved_etag,
                    current_etag=etag,
                )
                resume_position = 0
            else:
                resumed = True
                self._logger.info(
                    "file_download.resuming",
                    url=url,
                    resume_position=resume_position,
                    total_size=total_size,
                )

        # Prepare checksum hasher
        hasher = None
        if checksum_type:
            if checksum_type not in self._checksums:
                raise ValueError(f"Unsupported checksum type: {checksum_type}")
            hasher = self._checksums[checksum_type]()

            # If resuming, need to hash existing content first
            if resume_position > 0:
                async with aiofiles.open(file_path, "rb") as f:
                    while True:
                        chunk = await f.read(chunk_size)
                        if not chunk:
                            break
                        hasher.update(chunk)

        # Download with range support
        await self._apply_rate_limit()
        host = self._get_host_from_url(url)
        sem = self._sem_for_host(host)

        headers = {}
        if resume_position > 0:
            headers["Range"] = f"bytes={resume_position}-"

        current_bytes = resume_position

        async with sem:
            # Create streaming request
            assert self._client is not None

            async with self._client.stream("GET", url, headers=headers) as resp:
                await maybe_await(resp.raise_for_status())

                # Verify range response
                if resume_position > 0 and resp.status_code != 206:
                    raise DownloadError(
                        message="Server doesn't support range requests",
                        url=url,
                    )

                # Open file for writing (append if resuming)
                mode = "ab" if resumed else "wb"
                async with aiofiles.open(file_path, mode) as f:
                    byte_iterator = await ensure_async_iterator(
                        resp.aiter_bytes(chunk_size=chunk_size)
                    )

                    async for chunk in byte_iterator:
                        # Write chunk
                        await f.write(chunk)
                        current_bytes += len(chunk)

                        # Update checksum
                        if hasher:
                            hasher.update(chunk)

                        # Progress callback
                        if progress_callback:
                            await progress_callback(current_bytes, total_size)

        # Save ETag for future resume
        if etag:
            etag_file = file_path.with_suffix(file_path.suffix + ".etag")
            etag_file.write_text(etag)

        # Validate checksum
        actual_checksum = None
        if hasher:
            actual_checksum = hasher.hexdigest()
            self._logger.debug(
                "file_download.checksum_computed",
                url=url,
                checksum_type=checksum_type,
                checksum=actual_checksum
            )
            if expected_checksum and actual_checksum != expected_checksum:
                # Clean up invalid file
                file_path.unlink(missing_ok=True)
                self._logger.error(
                    "file_download.checksum_mismatch",
                    url=url,
                    expected=expected_checksum,
                    actual=actual_checksum,
                    file_path=str(file_path)
                )
                raise DownloadError(
                    message=f"Checksum validation failed: expected {expected_checksum}, got {actual_checksum}",
                    url=url,
                )

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        self._logger.info(
            "file_download.completed",
            url=url,
            file_path=str(file_path),
            size_bytes=current_bytes,
            resumed=resumed,
            checksum_type=checksum_type,
            checksum_valid=True if expected_checksum else None,
            duration_ms=duration_ms,
        )

        return FileDownloadResult(
            url=url,
            status_code=200 if resume_position == 0 else 206,
            headers={},
            content_type=content_type,
            content_encoding=None,
            file_path=file_path,
            bytes_=None,
            duration_ms=duration_ms,
            size_bytes=current_bytes,
            saved_to_disk=True,
            redirect_chain=[],
            checksum=actual_checksum,
            checksum_type=checksum_type,
            resumed=resumed,
            etag=etag,
        )

    async def download_batch(
        self,
        urls: List[str],
        max_concurrent: int = 10,
        on_success: Optional[Callable[[FileDownloadResult], Awaitable[None]]] = None,
        on_error: Optional[Callable[[str, Exception], Awaitable[None]]] = None,
        return_exceptions: bool = True,
    ) -> "BatchDownloadResult":
        """
        Download multiple files concurrently with controlled concurrency.

        Args:
            urls: List of URLs to download
            max_concurrent: Maximum concurrent downloads
            on_success: Optional callback for successful downloads
            on_error: Optional callback for failed downloads
            return_exceptions: If True, exceptions are collected; if False, first exception is raised

        Returns:
            BatchDownloadResult with successful and failed downloads

        Example:
            async with FileDownload() as client:
                result = await client.download_batch(
                    urls=["https://example.com/file1.zip", "https://example.com/file2.zip"],
                    max_concurrent=5,
                    on_success=lambda r: print(f"Saved {r.file_path}"),
                )
        """
        self._logger.info(
            "file_download_batch.started",
            total_urls=len(urls),
            max_concurrent=max_concurrent
        )
        batch_start = time.perf_counter()

        semaphore = asyncio.Semaphore(max_concurrent)
        successful: List[FileDownloadResult] = []
        failed: List[tuple[str, Exception]] = []

        async def download_one(url: str) -> None:
            """Download a single file with semaphore control."""
            async with semaphore:
                try:
                    result = await self.download(url)
                    successful.append(result)
                    if on_success:
                        await on_success(result)
                except Exception as exc:
                    failed.append((url, exc))
                    log_exception(self._logger, exc, "file_download_batch.item_failed", url=url)
                    if on_error:
                        await on_error(url, exc)
                    if not return_exceptions:
                        raise

        tasks = [download_one(url) for url in urls]
        await asyncio.gather(*tasks, return_exceptions=return_exceptions)

        batch_duration_ms = int((time.perf_counter() - batch_start) * 1000)
        result = BatchDownloadResult(
            successful=successful,
            failed=failed,
            total=len(urls),
        )

        self._logger.info(
            "file_download_batch.completed",
            total_urls=len(urls),
            successful=len(successful),
            failed=len(failed),
            success_rate=result.success_rate,
            duration_ms=batch_duration_ms
        )

        return result
