"""
Robust streaming downloads with resumable support and checksum validation.

This module extends FileDownload with advanced streaming features:
- Resumable downloads using Range headers and ETags
- Checksum validation (MD5, SHA256)
- HEAD request precheck for content size
- Chunked writing with progress callbacks
- Partial download support
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass
import inspect
from collections.abc import Iterable

import aiofiles
import httpx

from .core import BaseDownload
from .config import DownloadSettings
from .exceptions import DownloadError, InvalidURLError
from .logging import get_httpdl_logger


async def _maybe_await(result):
    """Await value if it is awaitable, otherwise return as-is."""
    if inspect.isawaitable(result):
        return await result
    return result


async def _ensure_async_iterator(candidate):
    """
    Convert various iterable/coroutine shapes into an async iterator.

    Testing utilities often rely on AsyncMock or plain lists; this helper keeps
    the production code resilient to those stubs while continuing to accept the
    real httpx streaming interfaces.
    """
    if inspect.isawaitable(candidate):
        candidate = await candidate

    if hasattr(candidate, "__aiter__"):
        return candidate

    if isinstance(candidate, Iterable):
        async def _generator():
            for chunk in candidate:
                yield chunk
        return _generator()

    raise TypeError("streaming response did not provide an async iterator")


@dataclass
class StreamingResult:
    """Result of a streaming download operation."""

    url: str
    file_path: Path
    size_bytes: int
    checksum: Optional[str]
    checksum_type: Optional[str]
    duration_ms: int
    resumed: bool
    etag: Optional[str]
    content_type: Optional[str]


class StreamingDownload(BaseDownload):
    """
    Advanced streaming download client with resumable support.

    Features:
    - Resumable downloads using Range headers
    - ETag validation for resume integrity
    - Checksum validation (MD5, SHA256)
    - HEAD request precheck
    - Progress callbacks
    - Chunk-level error recovery

    Example:
        async with StreamingDownload() as client:
            result = await client.download(
                url="https://example.com/large-file.zip",
                file_path=Path("downloads/file.zip"),
                checksum_type="sha256",
                progress_callback=lambda current, total: print(f"{current}/{total}")
            )
    """

    def __init__(self, settings: Optional[DownloadSettings] = None):
        super().__init__(settings)
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
            DownloadError: If HEAD request fails
        """
        if not url or not url.strip():
            raise InvalidURLError(message="URL cannot be empty", url=url)

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

        await resp.aclose()
        return metadata

    async def download(
        self,
        url: str,
        file_path: Path,
        checksum_type: Optional[str] = None,
        expected_checksum: Optional[str] = None,
        chunk_size: int = 65536,
        resume: bool = True,
        progress_callback: Optional[Callable[[int, int], Awaitable[None]]] = None,
    ) -> StreamingResult:
        """
        Download file with resumable support and checksum validation.

        Args:
            url: URL to download
            file_path: Path to save file
            checksum_type: Checksum algorithm ("md5", "sha256", "sha512")
            expected_checksum: Expected checksum value for validation
            chunk_size: Size of download chunks in bytes
            resume: Whether to resume partial downloads
            progress_callback: Optional async callback(current_bytes, total_bytes)

        Returns:
            StreamingResult with download metadata

        Raises:
            DownloadError: On download or validation failure

        Example:
            async def progress(current, total):
                print(f"Progress: {current}/{total} ({current/total*100:.1f}%)")

            result = await client.download(
                url="https://example.com/file.zip",
                file_path=Path("downloads/file.zip"),
                checksum_type="sha256",
                expected_checksum="abc123...",
                resume=True,
                progress_callback=progress
            )
        """
        import time

        if not url or not url.strip():
            raise InvalidURLError(message="URL cannot be empty", url=url)

        start_time = time.perf_counter()

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
                    "streaming.resume_not_supported",
                    url=url,
                    file_path=str(file_path),
                )
                resume_position = 0
            elif saved_etag and etag and saved_etag != etag:
                self._logger.warning(
                    "streaming.etag_mismatch",
                    url=url,
                    saved_etag=saved_etag,
                    current_etag=etag,
                )
                resume_position = 0
            else:
                resumed = True
                self._logger.info(
                    "streaming.resuming",
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
                await _maybe_await(resp.raise_for_status())

                # Verify range response
                if resume_position > 0 and resp.status_code != 206:
                    raise DownloadError(
                        message="Server doesn't support range requests",
                        url=url,
                    )

                # Open file for writing (append if resuming)
                mode = "ab" if resumed else "wb"
                async with aiofiles.open(file_path, mode) as f:
                    byte_iterator = await _ensure_async_iterator(
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
            if expected_checksum and actual_checksum != expected_checksum:
                # Clean up invalid file
                file_path.unlink(missing_ok=True)
                raise DownloadError(
                    message=f"Checksum validation failed: expected {expected_checksum}, got {actual_checksum}",
                    url=url,
                )

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        self._logger.info(
            "streaming.completed",
            url=url,
            file_path=str(file_path),
            size_bytes=current_bytes,
            resumed=resumed,
            checksum_type=checksum_type,
            duration_ms=duration_ms,
        )

        return StreamingResult(
            url=url,
            file_path=file_path,
            size_bytes=current_bytes,
            checksum=actual_checksum,
            checksum_type=checksum_type,
            duration_ms=duration_ms,
            resumed=resumed,
            etag=etag,
            content_type=content_type,
        )


async def download_with_retry(
    url: str,
    file_path: Path,
    max_retries: int = 3,
    checksum_type: Optional[str] = None,
    expected_checksum: Optional[str] = None,
    settings: Optional[DownloadSettings] = None,
) -> StreamingResult:
    """
    Download file with automatic retry and resume on failure.

    This is a convenience function that wraps StreamingDownload with
    retry logic. If download fails, it will retry and resume from the
    last successful position.

    Args:
        url: URL to download
        file_path: Path to save file
        max_retries: Maximum number of retry attempts
        checksum_type: Checksum algorithm for validation
        expected_checksum: Expected checksum value
        settings: Download settings

    Returns:
        StreamingResult with download metadata

    Example:
        result = await download_with_retry(
            url="https://example.com/large-file.zip",
            file_path=Path("downloads/file.zip"),
            max_retries=5,
            checksum_type="sha256",
            expected_checksum="abc123..."
        )
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            async with StreamingDownload(settings) as client:
                return await client.download(
                    url=url,
                    file_path=file_path,
                    checksum_type=checksum_type,
                    expected_checksum=expected_checksum,
                    resume=True,
                )
        except Exception as exc:
            last_error = exc
            if attempt < max_retries - 1:
                # Exponential backoff
                await asyncio.sleep(2 ** attempt)
            else:
                raise

    # Should not reach here, but for type checking
    raise last_error
