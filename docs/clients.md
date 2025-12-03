# HTTP-DL Clients Guide

This document explains the responsibilities and usage of all download clients in httpdl:

- `BaseDownload` (abstract foundation with stealth & session support)
- `DataDownload` (processed content with text decoding and classification)
- `FileDownload` (raw file downloads with streaming, resumable downloads, and checksums)
- `BatchDownload` (convenience class for batch operations)
- `DownloadQueue` (async queue for producer-consumer patterns)

All core clients (`DataDownload`, `FileDownload`) support batch operations via `download_batch()` methods.

## Shared Foundations (`BaseDownload`)

- **Lifecycle**: Always use `async with` to ensure the underlying `httpx.AsyncClient`
  is opened and closed correctly.
- **Settings**: Accepts `DownloadSettings` and initializes:
  - httpx client headers, timeouts, HTTP/2 flag, and connection pool limits.
  - Process-wide rate limiter (`AsyncRateLimiter`) configured with requested
    `requests_per_second`.
  - Per-host semaphores sized by `max_concurrency_per_host`.
  - Redirect handling behavior via `follow_redirects` and `max_redirects`.
  - **Stealth features** (optional): User-Agent rotation when `rotate_user_agent=True`.
  - **Session management** (optional): Automatic cookie persistence when `enable_cookies=True` and `session_file` is set.
- **Retry loop**: `_do_request_with_retry` wraps HTTP operations with exponential
  backoff, respect for `Retry-After`, and consistent exception mapping.
- **Redirect handling**: `_follow_redirects` manually follows HTTP redirects (301,
  302, 303, 307, 308) when enabled, tracking the full chain and detecting loops.
- **Rate limiting**: `_apply_rate_limit` awaits the shared token bucket before
  any request is issued.

### Instantiation Example

```python
settings = DownloadSettings(
    user_agent="MyApp/1.0 (ops@example.com)",
    requests_per_second=8,
    max_concurrency_per_host=6,
    retry=RetryPolicy(attempts=3),
    timeouts=Timeouts(read=60.0),
    follow_redirects=True,  # Enable redirect following (default)
    max_redirects=20,       # Maximum redirect chain (default)
)

async with DataDownload(settings) as client:
    ...
```

## `DataDownload`

### Responsibilities

- Issues HTTP GET requests through `_do_request_with_retry`.
- Reads the full response body, applies transfer decoding (gzip, deflate,
  brotli) via `decompress_transfer`.
- Enforces a decompressed-size guard (`max_decompressed_size_mb`).
- Detects content type (`normalize_content_type`, `extract_charset`,
  `classify_kind`) and decodes text payloads (`decode_text`).
- Returns a `DataDownloadResult` with metadata, decoded text or raw bytes,
  and timing information.

### Typical Flow

1. Validate URL (`InvalidURLError` when blank).
2. Apply rate limit and host semaphore.
3. Execute request with retry loop and redirect handling.
4. Decompress transfer encoding and enforce size limits.
5. Classify and decode content.
6. Populate `DataDownloadResult` (includes redirect chain).

### Usage

```python
async with DataDownload() as client:
    result = await client.download("https://www.sec.gov/files/company_tickers.json")
    if result.kind == "json":
        data = json.loads(result.text)

    # Check redirect chain
    if result.redirect_chain:
        print(f"URL was redirected: {' -> '.join(result.redirect_chain)}")
```

`override_kind` lets callers force classification (useful for feeds with
ambiguous headers).

### Redirect Behavior

- `DataDownload` inherits redirect handling from `BaseDownload`.
- The `redirect_chain` field in results contains all intermediate URLs visited.
- If `follow_redirects=False`, the initial response (even if 301/302) is returned.
- Redirects are followed before any content processing begins.

### Batch Data Downloads

```python
from httpdl import DataDownload

urls = [
    "https://api.example.com/data1.json",
    "https://api.example.com/data2.json",
    "https://api.example.com/data3.json",
]

async with DataDownload() as client:
    result = await client.download_batch(
        urls,
        max_concurrent=10,
        on_success=lambda r: print(f"✓ {r.url}: {r.kind}"),
        on_error=lambda url, e: print(f"✗ {url}: {e}"),
    )

    print(f"Success rate: {result.success_rate:.1f}%")

    # Process successful results
    for data_result in result.successful:
        if data_result.kind == "json":
            data = json.loads(data_result.text)
            # Process data...
```

## `FileDownload`

### Responsibilities

- Streams raw content to disk or memory without text decoding or decompression.
- **Resumable downloads**: Supports ETag validation and HTTP Range headers to resume partial downloads.
- **Checksum validation**: MD5, SHA256, SHA512 hash verification with automatic cleanup on mismatch.
- **Progress tracking**: Optional async callback for real-time download progress.
- **Batch operations**: Built-in `download_batch()` method for concurrent file downloads.
- Optional disk persistence via `file_path` parameter, using the `download_dir` created in the constructor.
- Handles rate limiting, retries, and per-host semaphores the same way `DataDownload` does.
- Returns a `FileDownloadResult` with path or bytes, checksums, resume status, and timing.

### Typical Flow (streaming)

1. Validate URL.
2. If resuming: Check for partial file and ETag, issue HEAD request to validate.
3. Acquire rate-limiter token and per-host semaphore.
4. Start streaming response (`httpx.AsyncClient.stream`) with Range header if resuming.
5. Write chunks to disk through `aiofiles`, computing checksum if requested.
6. Validate checksum against expected value (cleanup file if mismatch).
7. Save ETag for future resume attempts.
8. Build `FileDownloadResult` with all metadata.

### Basic Usage

```python
from pathlib import Path
from httpdl import FileDownload

async with FileDownload(download_dir=Path("downloads")) as client:
    result = await client.download(
        "https://example.com/large-file.zip",
        file_path=Path("file.zip")
    )
    print(f"Saved to: {result.file_path}")
    print(f"Size: {result.size_bytes} bytes")
```

### Resumable Downloads

```python
async with FileDownload() as client:
    result = await client.download(
        "https://example.com/large-file.zip",
        file_path=Path("file.zip"),
        resume=True,  # Automatically resume if interrupted
    )

    if result.resumed:
        print("Download was resumed from partial file")
    print(f"ETag: {result.etag}")
```

### Checksum Validation

```python
async with FileDownload() as client:
    result = await client.download(
        "https://example.com/file.zip",
        file_path=Path("file.zip"),
        checksum_type="sha256",
        expected_checksum="abc123...",  # Will raise DownloadError if mismatch
    )

    print(f"Verified {result.checksum_type}: {result.checksum}")
```

### Progress Callbacks

```python
async def progress(current: int, total: int):
    percent = (current / total) * 100 if total > 0 else 0
    print(f"Progress: {percent:.1f}% ({current}/{total} bytes)")

async with FileDownload() as client:
    result = await client.download(
        "https://example.com/large-file.zip",
        file_path=Path("file.zip"),
        progress_callback=progress,
        chunk_size=65536,  # 64KB chunks
    )
```

### Batch File Downloads

```python
from httpdl import FileDownload

urls = [
    "https://example.com/file1.zip",
    "https://example.com/file2.zip",
    "https://example.com/file3.zip",
]

async with FileDownload(download_dir=Path("downloads")) as client:
    result = await client.download_batch(
        urls,
        max_concurrent=5,
        on_success=lambda r: print(f"✓ Downloaded: {r.file_path}"),
        on_error=lambda url, e: print(f"✗ Failed {url}: {e}"),
    )

    print(f"Success rate: {result.success_rate:.1f}%")
    print(f"Successful: {len(result.successful)}")
    print(f"Failed: {len(result.failed)}")
```

### HEAD Requests (Metadata)

```python
async with FileDownload() as client:
    metadata = await client.head_request("https://example.com/file.zip")

    print(f"Content-Length: {metadata['content_length']} bytes")
    print(f"Content-Type: {metadata['content_type']}")
    print(f"ETag: {metadata['etag']}")
    print(f"Supports Resume: {metadata['accept_ranges']}")
```

## Choosing the Right Client

- **Processed content** (auto decoding, classification, text extraction):
  `DataDownload` - Perfect for APIs, JSON, XML, HTML that needs text decoding.
- **Raw file storage** (preserve original encoding, large files, checksums):
  `FileDownload` - Perfect for downloading binaries, archives, large datasets with resumable downloads.
- **Batch operations**: Both clients support `download_batch()` methods, or use the `BatchDownload` convenience class.
- **Customization**: Subclass `BaseDownload` when you need specialized
  behavior (e.g., streaming to external storage). Override `download()` but
  reuse `_apply_rate_limit`, `_do_request_with_retry`, and semaphore helpers.

## `BatchDownload` - Convenience Class for Batch Operations

### Overview

`BatchDownload` provides a simplified API for downloading multiple URLs concurrently without manually managing client lifecycle. It's a thin wrapper around `DataDownload` and `FileDownload` batch methods.

### Features

- Automatic client management (no need for `async with`)
- Consistent interface for both data and file downloads
- Comprehensive logging of batch operations
- Built-in error handling and progress tracking
- Returns `BatchDownloadResult` with success metrics

### Basic Usage

```python
from httpdl import BatchDownload

# Data downloads (JSON, XML, HTML)
batch = BatchDownload(download_type="data", max_concurrent=10)
result = await batch.download(
    urls=["https://api.example.com/data1.json", "https://api.example.com/data2.json"],
    on_success=lambda r: print(f"✓ {r.url}"),
    on_error=lambda url, e: print(f"✗ {url}: {e}"),
)

print(f"Success rate: {result.success_rate:.1f}%")
print(f"Successful: {len(result.successful)}")
print(f"Failed: {len(result.failed)}")
```

### File Batch Downloads

```python
from pathlib import Path

# File downloads with resume and checksums
batch = BatchDownload(
    download_type="file",
    max_concurrent=5,
    settings=DownloadSettings(
        requests_per_second=10,
        http2=True
    )
)

result = await batch.download(
    urls=[
        "https://example.com/file1.zip",
        "https://example.com/file2.zip",
        "https://example.com/file3.zip"
    ],
    on_success=lambda r: print(f"✓ Saved to {r.file_path}"),
    on_error=lambda url, e: print(f"✗ {url}: {e}")
)
```

### Configuration

```python
batch = BatchDownload(
    download_type="data",  # or "file"
    max_concurrent=10,     # Maximum concurrent downloads
    settings=DownloadSettings(
        requests_per_second=8,
        rate_limit_backend="redis",
        redis_url="redis://localhost:6379"
    )
)
```

### Logging

`BatchDownload` includes comprehensive logging:
- `batch_download.initialized` - Client created
- `batch_download.started` - Batch operation started
- `batch_download.completed` - All downloads finished
- `batch_download.failed` - Batch operation failed

---

## `DownloadQueue` - Producer-Consumer Pattern

### Overview

`DownloadQueue` implements an async queue for downloading URLs discovered dynamically. Perfect for web scraping scenarios where URLs are generated on-the-fly.

### Features

- Producer-consumer pattern with async queue
- Dynamic URL addition during execution
- Worker pool with configurable concurrency
- Comprehensive logging of queue state and worker activity
- Graceful shutdown after all URLs processed

### Basic Usage

```python
from httpdl import DownloadQueue
import asyncio

queue = DownloadQueue(
    max_concurrent=10,
    download_type="data",  # or "file"
    settings=DownloadSettings(requests_per_second=8)
)

# Producer: Add URLs dynamically
async def discover_urls():
    for page in range(1, 11):
        url = f"https://api.example.com/data?page={page}"
        await queue.add(url)
        # Can add more URLs based on response content
    await queue.finish()  # Signal no more URLs

# Consumer: Automatically processes queue
await asyncio.gather(
    discover_urls(),
    queue.start()
)

# Get results
result = queue.get_results()
print(f"Processed: {result.total}")
print(f"Success rate: {result.success_rate:.1f}%")
```

### Web Scraping Example

```python
from httpdl import DownloadQueue, DataDownload
import asyncio
import json

queue = DownloadQueue(max_concurrent=5, download_type="data")

async def crawl_api():
    """Discover URLs by following pagination."""
    page = 1
    while True:
        url = f"https://api.example.com/items?page={page}"
        await queue.add(url)

        # Fetch page to check for more
        async with DataDownload() as client:
            result = await client.download(url)
            data = json.loads(result.text)

            if not data.get("has_more"):
                break
            page += 1

    await queue.finish()

# Start crawling and processing concurrently
await asyncio.gather(
    crawl_api(),
    queue.start()
)

result = queue.get_results()
```

### Queue Methods

```python
# Add URL to queue
await queue.add("https://example.com/file.json")

# Signal completion (no more URLs)
await queue.finish()

# Start processing (blocks until all complete)
await queue.start()

# Get results
result = queue.get_results()  # Returns BatchDownloadResult
```

### Configuration

```python
queue = DownloadQueue(
    settings=DownloadSettings(
        requests_per_second=8,
        max_concurrency_per_host=6,
        http2=True
    ),
    max_concurrent=10,      # Worker pool size
    download_type="data"    # or "file"
)
```

### Logging

`DownloadQueue` includes detailed logging:
- `download_queue.initialized` - Queue created
- `download_queue.url_added` - URL added to queue
- `download_queue.finished_signal` - No more URLs will be added
- `download_queue.started` - Workers started processing
- `download_queue.worker_started` - Individual worker started
- `download_queue.worker_processing` - Worker processing URL
- `download_queue.worker_success` - Worker completed download
- `download_queue.worker_error` - Worker failed download
- `download_queue.completed` - All processing finished

### Comparison: BatchDownload vs DownloadQueue

| Feature | BatchDownload | DownloadQueue |
|---------|---------------|---------------|
| **URL Discovery** | All URLs known upfront | URLs discovered dynamically |
| **Use Case** | Fixed list of downloads | Web scraping, pagination |
| **Pattern** | Simple batch operation | Producer-consumer |
| **Complexity** | Low | Medium |
| **When to Use** | Download known URLs | Crawl and discover URLs |

---

## Choosing the Right Client

- **Single downloads**: Use `DataDownload` or `FileDownload` directly
- **Fixed batch**: Use `BatchDownload` convenience class
- **Dynamic discovery**: Use `DownloadQueue` for producer-consumer pattern
- **Processed content** (auto decoding, classification, text extraction):
  `DataDownload` - Perfect for APIs, JSON, XML, HTML that needs text decoding.
- **Raw file storage** (preserve original encoding, large files, checksums):
  `FileDownload` - Perfect for downloading binaries, archives, large datasets with resumable downloads.
- **Customization**: Subclass `BaseDownload` when you need specialized
  behavior (e.g., streaming to external storage). Override `download()` but
  reuse `_apply_rate_limit`, `_do_request_with_retry`, and semaphore helpers.

## Interaction with Settings and Exceptions

- Both clients consume `DownloadSettings` for rate limiting, retries, and
  timeouts. See the configuration dataclasses in `httpdl/models/config.py`.
- Exceptions raised during the lifecycle flow through the hierarchy documented
  in `docs/exceptions.md`. Catch what you need at call sites.

## Testing References

- `tests/test_data_download.py`: Comprehensive tests for DataDownload including batch operations, content classification, error handling, and redirect tracking.
- `tests/test_file_download.py`: Comprehensive tests for FileDownload including resumable downloads, checksum validation, progress callbacks, batch operations, and HEAD requests.
- `tests/test_rate_limiter.py`: Tests for rate limiting across all backends (Redis, multiprocessing, in-memory).
- `tests/test_concurrency.py`: Tests for batch operations and concurrent download patterns.
