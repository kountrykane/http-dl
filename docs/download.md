# Download Clients Guide

This document explains the responsibilities and usage of the three download
clients:

- `BaseDownload` (abstract foundation)
- `DataDownload` (processed content)
- `FileDownload` (raw file storage or bytes)

Refer here instead of relying on the exports in `httpdl/__init__.py`.

## Shared Foundations (`BaseDownload`)

- **Lifecycle**: Always use `async with` to ensure the underlying `httpx.AsyncClient`
  is opened and closed correctly.
- **Settings**: Accepts `DownloadSettings` and initializes:
  - httpx client headers, timeouts, HTTP/2 flag, and connection pool limits.
  - Process-wide rate limiter (`AsyncRateLimiter`) configured with requested
    `requests_per_second`.
  - Per-host semaphores sized by `max_concurrency_per_host`.
  - Redirect handling behavior via `follow_redirects` and `max_redirects`.
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

## `FileDownload`

### Responsibilities

- Streams or buffers raw content without decoding.
- Optional disk persistence via `stream_to_disk=True`, using the `download_dir`
  created in the constructor.
- Handles rate limiting, retries, and per-host semaphores the same way
  `DataDownload` does.
- Returns a `FileDownloadResult` with path or bytes, plus timing and headers.

### Typical Flow (streaming)

1. Validate URL.
2. Acquire rate-limiter token and per-host semaphore.
3. Start streaming response (`httpx.AsyncClient.stream`).
4. Write chunks to disk through `aiofiles` (or collect bytes in memory if
   `stream_to_disk=False`).
5. Build `FileDownloadResult`.

### Usage

```python
from pathlib import Path

async with FileDownload(download_dir=Path("bulk")) as client:
    result = await client.download(
        "https://www.sec.gov/Archives/edgar/data/1318605/000095017023001409/tsla-20221231.htm"
    )
    print("Saved to:", result.file_path)
```

## Choosing the Right Client

- **Processed content** (auto decoding, classification, text extraction):
  `DataDownload`.
- **Raw transfer** (store as-is, integrate with object storage, manual parsing):
  `FileDownload`.
- **Customization**: Subclass `BaseDownload` when you need specialized
  behavior (e.g., streaming to external storage). Override `download()` but
  reuse `_apply_rate_limit`, `_do_request_with_retry`, and semaphore helpers.

## Interaction with Settings and Exceptions

- Both clients consume `DownloadSettings` for rate limiting, retries, and
  timeouts. See the configuration dataclasses in `httpdl/models/config.py`.
- Exceptions raised during the lifecycle flow through the hierarchy documented
  in `docs/exceptions.md`. Catch what you need at call sites.

## Testing References

- `tests/test_data_download.py`: demonstrates synchronous harness usage.
- `tests/test_file_download.py`: validates streaming behavior and error cases.
- `tests/test_rate_limiter.py`: covers concurrency and rate enforcement shared
  by both clients.
