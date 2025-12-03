from __future__ import annotations
import contextlib
import time
import asyncio
import inspect
from typing import Optional, Union, Callable, Awaitable, List
from pathlib import Path
from collections.abc import Iterable

from .base import BaseDownload
from ..models.config import DownloadSettings
from ..utils import (
    normalize_content_type,
    extract_charset,
    classify_kind,
    decode_text,
    decompress_transfer,
)
from ..models.results import DataDownloadResult, FileDownloadResult
from ..exceptions import (
    InvalidURLError,
    PayloadSizeLimitError,
    DecompressionError,
    classify_http_error,
)
from ..observability.logging import (
    get_httpdl_logger,
    log_content_processing,
    log_exception,
    HttpdlLoggerAdapter,
)

from ..models.results import BatchDownloadResult


# Helper functions for streaming support
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


class DataDownload(BaseDownload):
    """
    Async-only EDGAR/HTTP download client for in-memory data.

    Responsibilities:
      - Rate limit (token bucket, default 8 r/s)
      - Per-host concurrency guard
      - Retries with jittered backoff (+ Retry-After)
      - Transfer decompression (gzip/deflate/br)
      - Classify + decode text; keep bytes for archive/binary
      - No parsing, no caching

    Example:
        async with DataDownload() as client:
            result = await client.download("https://example.com/data.json")
            print(result.text)
    """

    async def download(self, url: str, override_kind: Optional[str] = None) -> DataDownloadResult:
        """
        High-level entry for processed downloads:
          - Performs GET with retries/limits.
          - Decompresses *transfer* encodings.
          - Classifies (header + sniff).
          - Decodes to str for text kinds; keeps bytes for archive/binary.
          - Returns DataDownloadResult; no parsing.

        Args:
            url: Target URL to download
            override_kind: Optional content kind override (json/xml/html/sgml/atom)

        Returns:
            DataDownloadResult with processed content

        Raises:
            InvalidURLError: When URL is empty or malformed
            PayloadSizeLimitError: When decompressed size exceeds safety limit
            DecompressionError: When transfer encoding decompression fails
            HTTPError: For 4xx/5xx responses (after body read)
            NetworkError: For connection/timeout/DNS failures
        """
        if not url or not url.strip():
            self._logger.error("download.invalid_url", url=url)
            raise InvalidURLError(
                message="URL cannot be empty",
                url=url,
            )

        self._logger.debug("download.started", url=url, override_kind=override_kind)

        # global rate limit
        await self._apply_rate_limit()

        host = self._get_host_from_url(url)
        sem = self._sem_for_host(host)
        start = time.perf_counter()

        async with sem:
            resp, redirect_chain = await self._do_request_with_retry("GET", url)

        duration_ms = int((time.perf_counter() - start) * 1000)

        # read body
        raw = await resp.aread()
        self._logger.debug("download.body_read", url=url, raw_size_bytes=len(raw))

        # transfer decompression with structured error handling
        content_encoding = resp.headers.get("Content-Encoding")
        try:
            data = decompress_transfer(raw, content_encoding)
            if content_encoding:
                log_content_processing(
                    self._logger,
                    operation="decompress",
                    content_type=resp.headers.get("Content-Type"),
                    size_bytes=len(data),
                    compression=content_encoding,
                    url=url
                )
        except Exception as exc:
            with contextlib.suppress(Exception):
                await resp.aclose()
            log_exception(self._logger, exc, "download.decompression_failed", url=url, encoding=content_encoding)
            raise DecompressionError(
                message=f"Failed to decompress response body: {exc}",
                url=str(resp.request.url),
                encoding=content_encoding,
                cause=exc,
            ) from exc

        # guard against decompression bombs
        max_bytes = self.settings.max_decompressed_size_mb * 1024 * 1024
        if len(data) > max_bytes:
            with contextlib.suppress(Exception):
                await resp.aclose()
            self._logger.error(
                "download.payload_too_large",
                url=url,
                actual_size=len(data),
                max_size=max_bytes
            )
            raise PayloadSizeLimitError(
                message="",  # Will be auto-generated
                url=str(resp.request.url),
                actual_size=len(data),
                max_size=max_bytes,
            )

        # classify + decode (no parsing)
        content_type = normalize_content_type(resp.headers)
        charset = extract_charset(resp.headers)
        kind, sniff_note = classify_kind(content_type, data)
        if override_kind:
            kind, sniff_note = override_kind, (sniff_note or "override_kind")

        log_content_processing(
            self._logger,
            operation="classify",
            content_type=content_type,
            charset=charset,
            size_bytes=len(data),
            kind=kind,
            sniff_note=sniff_note,
            url=url
        )

        text: Optional[str] = None
        bytes_: Optional[bytes] = None

        if kind in {"json", "xml", "html", "sgml", "atom"}:
            text, note = decode_text(data, charset)
            if note:
                sniff_note = f"{sniff_note}; {note}" if sniff_note else note
            log_content_processing(
                self._logger,
                operation="decode",
                content_type=content_type,
                charset=charset,
                size_bytes=len(text) if text else 0,
                kind=kind,
                url=url
            )
        else:
            bytes_ = data

        # error surfacing with domain-specific exceptions (after body read)
        if resp.status_code >= 400:
            excerpt = (text or (bytes_[:512].decode("utf-8", "replace") if bytes_ else ""))[:512]
            with contextlib.suppress(Exception):
                await resp.aclose()
            self._logger.error(
                "download.http_error",
                url=url,
                status_code=resp.status_code,
                excerpt=excerpt[:100]
            )
            # Use classify_http_error to create appropriate exception
            raise classify_http_error(
                status_code=resp.status_code,
                url=str(resp.request.url),
                response=resp,
                excerpt=excerpt,
            )

        result = DataDownloadResult(
            url=str(resp.request.url),
            status_code=resp.status_code,
            headers=dict(resp.headers),
            content_type=content_type,
            kind=kind,
            text=text,
            bytes_=bytes_,
            charset=charset,
            duration_ms=duration_ms,
            size_bytes=len(data),
            sniff_note=sniff_note,
            redirect_chain=redirect_chain,
        )

        self._logger.info(
            "download.completed",
            url=url,
            status_code=resp.status_code,
            kind=kind,
            size_bytes=len(data),
            duration_ms=duration_ms,
            redirect_count=len(redirect_chain)
        )

        with contextlib.suppress(Exception):
            await resp.aclose()
        return result

    async def download_batch(
        self,
        urls: List[str],
        max_concurrent: int = 10,
        on_success: Optional[Callable[[DataDownloadResult], Awaitable[None]]] = None,
        on_error: Optional[Callable[[str, Exception], Awaitable[None]]] = None,
        return_exceptions: bool = True,
    ) -> "BatchDownloadResult":
        """
        Download multiple URLs concurrently with controlled concurrency.

        Args:
            urls: List of URLs to download
            max_concurrent: Maximum concurrent downloads
            on_success: Optional callback for successful downloads
            on_error: Optional callback for failed downloads
            return_exceptions: If True, exceptions are collected; if False, first exception is raised

        Returns:
            BatchResult with successful and failed downloads

        Example:
            async with DataDownload() as client:
                result = await client.download_batch(
                    urls=["https://example.com/1", "https://example.com/2"],
                    max_concurrent=5,
                    on_success=lambda r: print(f"✓ {r.url}"),
                )
                print(f"Success rate: {result.success_rate:.1f}%")
        """

        semaphore = asyncio.Semaphore(max_concurrent)
        successful: List[DataDownloadResult] = []
        failed: List[tuple[str, Exception]] = []

        async def download_one(url: str) -> None:
            """Download a single URL with semaphore control."""
            async with semaphore:
                try:
                    result = await self.download(url)
                    successful.append(result)
                    if on_success:
                        await on_success(result)
                except Exception as exc:
                    failed.append((url, exc))
                    if on_error:
                        await on_error(url, exc)
                    if not return_exceptions:
                        raise

        tasks = [download_one(url) for url in urls]
        await asyncio.gather(*tasks, return_exceptions=return_exceptions)

        return BatchDownloadResult(
            successful=successful,
            failed=failed,
            total=len(urls),
        )
