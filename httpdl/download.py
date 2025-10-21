from __future__ import annotations
import contextlib
import time
import asyncio
from typing import Optional, Union
from pathlib import Path
import os
import aiofiles

import httpx

from .core import BaseDownload
from .config import DownloadSettings
from .utils import (
    normalize_content_type,
    extract_charset,
    classify_kind,
    decode_text,
    decompress_transfer,
)
from .models import DataDownloadResult, FileDownloadResult
from .exceptions import (
    InvalidURLError,
    PayloadSizeLimitError,
    DecompressionError,
    classify_http_error,
)


class DataDownload(BaseDownload):
    """
    Async-only EDGAR/HTTP download client.

    Responsibilities:
      - Rate limit (token bucket, default 8 r/s)
      - Per-host concurrency guard
      - Retries with jittered backoff (+ Retry-After)
      - Transfer decompression (gzip/deflate/br)
      - Classify + decode text; keep bytes for archive/binary
      - No parsing, no caching
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
            raise InvalidURLError(
                message="URL cannot be empty",
                url=url,
            )

        # global rate limit
        await self._apply_rate_limit()

        host = self._get_host_from_url(url)
        sem = self._sem_for_host(host)
        start = time.perf_counter()

        async with sem:
            resp = await self._do_request_with_retry("GET", url)

        duration_ms = int((time.perf_counter() - start) * 1000)

        # read body
        raw = await resp.aread()

        # transfer decompression with structured error handling
        content_encoding = resp.headers.get("Content-Encoding")
        try:
            data = decompress_transfer(raw, content_encoding)
        except Exception as exc:
            with contextlib.suppress(Exception):
                await resp.aclose()
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

        text: Optional[str] = None
        bytes_: Optional[bytes] = None

        if kind in {"json", "xml", "html", "sgml", "atom"}:
            text, note = decode_text(data, charset)
            if note:
                sniff_note = f"{sniff_note}; {note}" if sniff_note else note
        else:
            bytes_ = data

        # error surfacing with domain-specific exceptions (after body read)
        if resp.status_code >= 400:
            excerpt = (text or (bytes_[:512].decode("utf-8", "replace") if bytes_ else ""))[:512]
            with contextlib.suppress(Exception):
                await resp.aclose()
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
        )

        with contextlib.suppress(Exception):
            await resp.aclose()
        return result


class FileDownload(BaseDownload):
    """
    Asynchronous download client for raw files.

    Downloads files without processing:
      - No decompression (keeps gzip, deflate, br as-is)
      - No text decoding
      - Supports streaming to disk for large files
      - Returns raw bytes or file path

    Note: The file saving implementation is temporary. In production,
    files will be saved to object store (S3, Azure Blob, etc.) using
    the appropriate SDK once the provider is selected.
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
            download_dir: Directory to save files (temporary implementation)
                         Will be replaced with object store configuration
        """
        super().__init__(settings)
        # TODO: Replace with object store configuration once provider is selected
        # self.object_store_client = boto3.client('s3')  # Example for S3
        # self.bucket_name = 'sec-downloads'
        self.download_dir = download_dir or Path("downloads")
        if self.download_dir:
            self.download_dir.mkdir(parents=True, exist_ok=True)

    async def download(
        self,
        url: str,
        save_path: Optional[Path] = None,
        stream_to_disk: bool = True,
        chunk_size: int = 8192
    ) -> FileDownloadResult:
        """
        Download raw file without processing.

        Args:
            url: URL to download
            save_path: Optional specific path to save file
                      If not provided, generates from URL
            stream_to_disk: Whether to stream large files to disk
                           If False, loads entire file into memory
            chunk_size: Size of chunks for streaming (in bytes)

        Returns:
            FileDownloadResult with file path or raw bytes

        Raises:
            InvalidURLError: When URL is empty or malformed
            HTTPError: For 4xx/5xx responses
            NetworkError: For connection/timeout/DNS failures

        Note: In production, save_path will be replaced with object_key
        for object store uploads.
        """
        if not url or not url.strip():
            raise InvalidURLError(
                message="URL cannot be empty",
                url=url,
            )

        # Apply rate limiting
        await self._apply_rate_limit()

        host = self._get_host_from_url(url)
        sem = self._sem_for_host(host)
        start = time.perf_counter()

        file_path: Optional[Path] = None
        bytes_: Optional[bytes] = None
        saved_to_disk = False
        content_type: Optional[str] = None
        content_encoding: Optional[str] = None
        headers_dict = {}

        async with sem:
            if stream_to_disk:
                # Generate file path if not provided
                if save_path is None:
                    # Extract filename from URL or use a default
                    url_path = httpx.URL(url).path
                    if url_path:
                        filename = os.path.basename(url_path)
                        if not filename or filename == "/":
                            filename = f"download_{int(time.time())}.bin"
                    else:
                        filename = f"download_{int(time.time())}.bin"
                    save_path = self.download_dir / filename

                file_path = Path(save_path)
                file_path.parent.mkdir(parents=True, exist_ok=True)

                # TODO: Replace file writing with object store upload
                # Example for S3:
                # multipart_upload = self.s3_client.create_multipart_upload(
                #     Bucket=self.bucket_name,
                #     Key=object_key
                # )

                # Stream to file using async file I/O
                total_bytes = 0
                async with self._client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    headers_dict = dict(resp.headers)
                    content_type = resp.headers.get("Content-Type")
                    content_encoding = resp.headers.get("Content-Encoding")

                    async with aiofiles.open(file_path, 'wb') as f:
                        async for chunk in resp.aiter_raw(chunk_size=chunk_size):
                            await f.write(chunk)
                            total_bytes += len(chunk)

                saved_to_disk = True
                size_bytes = total_bytes

            else:
                # Load entire response into memory - preserve raw bytes
                async with self._client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    headers_dict = dict(resp.headers)
                    content_type = resp.headers.get("Content-Type")
                    content_encoding = resp.headers.get("Content-Encoding")

                    # Read raw stream without decompression
                    chunks = []
                    async for chunk in resp.aiter_raw():
                        chunks.append(chunk)
                    bytes_ = b''.join(chunks)
                    size_bytes = len(bytes_)

        duration_ms = int((time.perf_counter() - start) * 1000)

        # Note: Error handling was done with raise_for_status above
        # This simplifies the error handling logic

        result = FileDownloadResult(
            url=url,
            status_code=200,  # If we got here, status was OK
            headers=headers_dict,
            content_type=content_type,
            content_encoding=content_encoding,
            file_path=file_path,
            bytes_=bytes_,
            duration_ms=duration_ms,
            size_bytes=size_bytes,
            saved_to_disk=saved_to_disk,
        )

        return result

