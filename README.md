# http-dl 

## Overview

The http-dl Package provides robust functionality for downloading SEC documents with built-in rate limiting, retry logic, and flexible content handling. The package offers two primary download modes:

- **DataDownload**: Processes and decodes content (text decoding, decompression, classification)
- **FileDownload**: Downloads raw files without processing (preserves the original encoding)

### Features

- **Process-Wide Rate Limiting**: Singleton token bucket limiter automatically shared across all DataDownload/FileDownload instances
- **Per-Host Concurrency Control**: Prevents overwhelming individual hosts
- **Automatic Retries**: Exponential backoff with jitter, respects Retry-After headers
- **Transfer Encoding Support**: Handles gzip, deflate, and brotli compression
- **Content Classification**: Automatic detection of content types (JSON, XML, HTML, etc.)
- **Comprehensive Exception Hierarchy**: 19+ specialized exception types for precise error handling
- **Thread-Safe**: All components are thread-safe for concurrent usage

### Rate Limiting Architecture

**Important**: The download library uses a **process-wide singleton rate limiter** (`AsyncRateLimiter._shared_bucket`). This means:

- **All `DataDownload()` and `FileDownload()` instances automatically share the same rate limiting bucket**
- **No need to pass `DownloadSettings` between clients** - they all respect the same global rate limit
- **Simplifies usage** - just create clients with `DataDownload()` and rate limiting works automatically
- **First client to initialize sets the rate** - subsequent clients adopt the same limit

This design prevents accidentally creating multiple rate limiters that could exceed SEC's rate limits. You can safely create multiple download clients throughout your application and they will all coordinate automatically.

## Architecture

```
httpdl/
├── __init__.py      # Package exports
├── core.py          # Base class (BaseDownload) with shared functionality
├── download.py      # DataDownload and FileDownload implementations
├── exceptions.py    # Exception hierarchy (19+ specialized types)
├── limiting.py      # Rate limiting implementations
├── utils.py         # Utility functions for content processing
└── models/
    ├── __init__.py
    ├── config.py    # Configuration settings (DownloadSettings, RetryPolicy, Timeouts)
    └── result.py    # Result data classes (DataDownloadResult, FileDownloadResult)
```


### Configuration Options

The download library supports two levels of customization:

#### 1. Use Default Settings (Simplest)

For most use cases, simply use default settings:

```python
# Simple usage - uses defaults from config.py (8 req/s, 6 concurrent)
async with DataDownload() as client:
    result = await client.download(url)
```

#### 2. Customize Settings Per Client

You can customize any setting by passing a `DownloadSettings` instance:

```python
from download import DataDownload, DownloadSettings
from download.config import RetryPolicy, Timeouts

# Create custom settings
settings = DownloadSettings(
    user_agent="MyApp/1.0 contact@example.com",
    requests_per_second=5,           # Process-wide rate limiter
    max_concurrency_per_host=10,     # Per-instance concurrency
    max_decompressed_size_mb=500,    # Per-instance safety limit
    retry=RetryPolicy(attempts=3),   # Per-instance retry behavior
    timeouts=Timeouts(read=60.0)     # Per-instance timeouts
)

async with DataDownload(settings) as client:
    result = await client.download(url)
```

**Rate Limiter Behavior:**
- The `requests_per_second` setting uses a **process-wide singleton token bucket**
- First client initializes the rate; subsequent clients can only tighten (never loosen) it
- All other settings are **per-instance** and fully independent

**Use custom settings when you need:**
- Different User-Agent headers for different operations
- Tighter rate limits for sensitive endpoints
- Higher concurrency for bulk operations
- Custom timeout/retry policies for specific use cases

#### Settings Scope Reference

| Setting | Scope | Customizable Per-Instance? |
|---------|-------|---------------------------|
| `requests_per_second` | **Process-wide** (singleton bucket) | Yes, but only tightens globally |
| `max_concurrency_per_host` | **Per-instance** | ✅ Yes, fully independent |
| `user_agent` | **Per-instance** | ✅ Yes |
| `timeouts` | **Per-instance** | ✅ Yes |
| `retry.attempts` | **Per-instance** | ✅ Yes |
| `max_decompressed_size_mb` | **Per-instance** | ✅ Yes |
| `http2` | **Per-instance** | ✅ Yes |
| `accept` / `accept_encoding` / `connection` | **Per-instance** | ✅ Yes |

## Installation

The package is part of the sectools project and can be imported directly:

```python
from download import DataDownload, FileDownload, DownloadSettings
```

## Usage

### DataDownload (Processed Content)

Use `DataDownload` when you need processed, decoded content ready for parsing:

```python
import asyncio
from download import DataDownload

# Simple usage - uses defaults from config.py
async def download_example():
    async with DataDownload() as client:
        result = await client.download("https://www.sec.gov/files/company_tickers.json")

        # Access processed data
        print(f"Content Type: {result.content_type}")
        print(f"Kind: {result.kind}")  # "json", "xml", "html", etc.

        if result.text:
            # Text content is decoded and ready to use
            import json
            data = json.loads(result.text)
        elif result.bytes_:
            # Binary content preserved as bytes
            process_binary(result.bytes_)

# Run async function
asyncio.run(download_example())
```

#### DataDownloadResult Fields

- `url`: Final URL after redirects
- `status_code`: HTTP status code
- `headers`: Response headers dictionary
- `content_type`: Normalized content type
- `kind`: Classification ("json", "xml", "html", "sgml", "atom", "binary", "archive", "unknown")
- `text`: Decoded text content (for text-like kinds)
- `bytes_`: Raw bytes (for binary/archive/unknown kinds)
- `charset`: Detected character encoding
- `duration_ms`: Download duration in milliseconds
- `size_bytes`: Size of decompressed content
- `sniff_note`: Notes about content detection

### FileDownload (Raw Files)

Use `FileDownload` when you need raw, unprocessed files:

```python
import asyncio
from download import FileDownload
from pathlib import Path

async def file_download_example():
    # Initialize with download directory - uses default config
    async with FileDownload(download_dir=Path("downloads")) as client:

        # Stream large file to disk
        result = await client.download(
            "https://www.sec.gov/Archives/edgar/data/789019/000156459021002316/msft-10k_20200630.htm",
            stream_to_disk=True,
            chunk_size=8192
        )

        print(f"File saved to: {result.file_path}")
        print(f"Raw size: {result.size_bytes} bytes")

        # Or download to memory for small files
        result = await client.download(
            "https://www.sec.gov/robots.txt",
            stream_to_disk=False
        )

        # Access raw bytes
        raw_content = result.bytes_

# Run async function
asyncio.run(file_download_example())
```

#### FileDownloadResult Fields

- `url`: Final URL after redirects
- `status_code`: HTTP status code
- `headers`: Response headers dictionary
- `content_type`: Raw Content-Type header value
- `content_encoding`: Raw Content-Encoding (gzip, deflate, etc.)
- `file_path`: Path where file was saved (if saved to disk)
- `bytes_`: Raw bytes (if not saved to disk)
- `duration_ms`: Download duration in milliseconds
- `size_bytes`: Size of raw downloaded bytes
- `saved_to_disk`: Whether the file was saved to disk

**Note**: The file saving implementation is temporary. In production, files will be saved to object store (S3, Azure Blob, etc.) once the provider is selected.

## Configuration

### DownloadSettings

```python
from download import DownloadSettings
from download.config import RetryPolicy, Timeouts

settings = DownloadSettings(
    # EDGAR / HTTP basics
    user_agent="YourApp/1.0 your.email@example.com",
    base_url="https://www.sec.gov",
    
    # Throughput controls
    requests_per_second=8,
    max_concurrency_per_host=6,
    
    # HTTP behavior
    http2=False,
    retry=RetryPolicy(
        attempts=5,
        base_delay_ms=500,
        respect_retry_after=True
    ),
    timeouts=Timeouts(
        connect=2.0,
        read=120.0,
        write=10.0,
        pool=2.0
    ),
    
    # Default headers
    accept="*/*",
    accept_encoding="gzip, deflate, br",
    connection="keep-alive",
    
    # Safety
    max_decompressed_size_mb=200
)
```

## Extending the Package

### Creating a Custom Download Class

You can extend `BaseDownload` to create custom download behavior:

```python
import asyncio
from download.core import BaseDownload
from download.models import DataDownloadResult

class CustomDownload(BaseDownload):
    async def download(self, url: str, **kwargs) -> DataDownloadResult:
        # Apply rate limiting
        await self._apply_rate_limit()

        # Get host and semaphore
        host = self._get_host_from_url(url)
        sem = self._sem_for_host(host)

        async with sem:
            # Use built-in retry logic
            resp = await self._do_request_with_retry("GET", url)

            # Custom processing here
            data = await resp.aread()

            # Return custom result
            return DataDownloadResult(
                url=str(resp.request.url),
                status_code=resp.status_code,
                headers=dict(resp.headers),
                # ... other fields
            )

# Usage
async def custom_example():
    async with CustomDownload() as client:
        result = await client.download("https://example.com")

asyncio.run(custom_example())
```

## Migration Guide

### From DownloadClient to DataDownload

The `DownloadClient` class has been renamed to `DataDownload` to better reflect its purpose. The API remains unchanged:

**Before:**
```python
from download import DownloadClient

with DownloadClient() as client:
    result = client.download(url)
```

**After:**
```python
from download import DataDownload

with DataDownload() as client:
    result = client.download(url)
```

### Choosing Between DataDownload and FileDownload

| Use Case | Recommended Class | Reason |
|----------|------------------|---------|
| Parsing JSON/XML APIs | DataDownload | Automatic decoding and decompression |
| Analyzing HTML filings | DataDownload | Text is decoded and ready to parse |
| Storing original files | FileDownload | Preserves exact bytes as received |
| Large file downloads | FileDownload | Supports streaming to disk |
| Archiving documents | FileDownload | Maintains original compression |

## Rate Limiting

All download clients share a process-wide asynchronous token bucket. The default 8 requests/second matches SEC guidance and applies everywhere in the Python process, even when multiple threads or asyncio event loops are active. Each wait call computes the exact deficit so tasks yield efficiently instead of busy-waiting.

### Customizing throughput

Adjust `requests_per_second` on `DownloadSettings` to tighten the shared limiter. The strictest value requested by any client wins until the process ends (or a new client requests an even lower rate).

```python
import asyncio
from download import DataDownload, DownloadSettings

slow_settings = DownloadSettings(
    requests_per_second=4,       # halve the default rate
    max_concurrency_per_host=4,
)

async def pull_filings(urls):
    async with DataDownload(slow_settings) as client:
        for url in urls:
            await client.download(url)  # every call respects the shared limiter

asyncio.run(pull_filings([
    "https://www.sec.gov/Archives/edgar/data/320193/000032019324000010/aapl-10q2024.htm",
]))
```

Launch another `DataDownload()` (even with default settings) and it will automatically reuse the 4 req/s global limiter created above.

### Using the limiter directly

The limiter can gate other SEC-bound I/O as well. Import it when you need the same budget outside the download clients.

```python
import asyncio
from download.limiting import AsyncRateLimiter

limiter = AsyncRateLimiter(rate=6)  # shared across the whole process

async def fetch_metadata(session, cik):
    await limiter.wait()            # burns one token from the global bucket
    return await session.get(f"https://data.sec.gov/submissions/{cik}.json")
```


## Concurrency

The async implementation provides excellent concurrency support:

```python
import asyncio
from download import DataDownload

async def download_multiple():
    async with DataDownload() as client:
        urls = ["url1", "url2", "url3"]

        # Concurrent downloads
        tasks = [client.download(url) for url in urls]
        results = await asyncio.gather(*tasks)

        for url, result in zip(urls, results):
            print(f"Downloaded {url}: {result.size_bytes} bytes")

# Run concurrent downloads
asyncio.run(download_multiple())
```

## Error Handling

The download library provides a **comprehensive exception hierarchy** with 19+ specialized exception types for precise error handling. All exceptions inherit from `DownloadError` and include rich context (URL, response, cause chain, custom metadata).

### Exception Hierarchy

```
DownloadError (base)
├── ValidationError
│   ├── InvalidURLError
│   ├── InvalidSettingsError
│   └── PayloadSizeLimitError
├── NetworkError
│   ├── ConnectionError
│   ├── TimeoutError
│   └── DNSResolutionError
├── HTTPError
│   ├── ClientError (4xx)
│   │   ├── BadRequestError (400)
│   │   ├── UnauthorizedError (401)
│   │   ├── ForbiddenError (403)
│   │   ├── NotFoundError (404)
│   │   ├── ClientTimeoutError (408)
│   │   └── RateLimitError (429)
│   └── ServerError (5xx)
│       ├── InternalServerError (500)
│       ├── BadGatewayError (502)
│       └── ServiceUnavailableError (503)
├── ContentError
│   ├── DecompressionError
│   ├── EncodingError
│   └── ContentTypeError
└── RetryError
    ├── RetryAttemptsExceeded
    └── RetryBudgetExceeded
```

### Basic Exception Handling

```python
import asyncio
from download import (
    DataDownload,
    NotFoundError,
    ForbiddenError,
    RateLimitError,
    InvalidURLError,
)

async def error_handling_example():
    async with DataDownload() as client:
        try:
            result = await client.download("https://www.sec.gov/files/data.json")

        except InvalidURLError as e:
            # Empty or malformed URL
            print(f"Invalid URL: {e}")

        except NotFoundError as e:
            # HTTP 404 - document doesn't exist
            print(f"Not found: {e.url}")

        except ForbiddenError as e:
            # HTTP 403 - check User-Agent header
            print(f"Access denied: {e.url}")

        except RateLimitError as e:
            # HTTP 429 - rate limited
            print(f"Rate limited. Retry after {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            # Retry logic here...

asyncio.run(error_handling_example())
```

### Advanced Exception Handling

#### Hierarchical Catching

Catch groups of related exceptions using base classes:

```python
from download import (
    DataDownload,
    ClientError,    # All 4xx errors
    ServerError,    # All 5xx errors
    NetworkError,   # Connection, timeout, DNS errors
    HTTPError,      # All HTTP status errors
)

async with DataDownload() as client:
    try:
        result = await client.download(url)

    except ClientError as e:
        # Catches all 4xx errors (BadRequest, NotFound, Forbidden, etc.)
        print(f"Client error {e.status_code}: {e.url}")
        # These are usually not retryable

    except ServerError as e:
        # Catches all 5xx errors (InternalServer, BadGateway, etc.)
        print(f"Server error {e.status_code}: {e.url}")
        # These might be transient - consider retry

    except NetworkError as e:
        # Catches all network-level errors
        print(f"Network failure: {type(e).__name__}")
        # Connection issues, timeouts, DNS failures
```

#### Network Error Handling

```python
from download import (
    DataDownload,
    TimeoutError as DownloadTimeoutError,
    ConnectionError as DownloadConnectionError,
    DNSResolutionError,
    RetryAttemptsExceeded,
)

async with DataDownload() as client:
    try:
        result = await client.download(url)

    except DownloadTimeoutError as e:
        # Request timed out
        print(f"Timeout: {e.timeout_type} ({e.timeout_seconds}s)")
        # e.timeout_type = "connect", "read", "write", or "pool"

    except DownloadConnectionError as e:
        # TCP connection failed
        print(f"Cannot connect to {e.host}:{e.port}")

    except DNSResolutionError as e:
        # Hostname resolution failed
        print(f"DNS lookup failed for {e.hostname}")

    except RetryAttemptsExceeded as e:
        # All retries exhausted
        print(f"Failed after {e.attempts} attempts")
        if e.last_status_code:
            print(f"Last status: {e.last_status_code}")
```

#### Content Processing Errors

```python
from download import (
    DataDownload,
    PayloadSizeLimitError,
    DecompressionError,
)

async with DataDownload() as client:
    try:
        result = await client.download(url)

    except PayloadSizeLimitError as e:
        # Decompressed payload exceeds safety limit
        print(f"Payload too large: {e.actual_size:,} > {e.max_size:,} bytes")

    except DecompressionError as e:
        # gzip/deflate/brotli decompression failed
        print(f"Decompression failed ({e.encoding}): {e.message}")
```

#### Smart Rate Limit Handling

Automatically retry with proper delay:

```python
async def download_with_retry(url: str, max_retries: int = 3):
    """Download with automatic rate limit retry."""
    for attempt in range(max_retries):
        try:
            async with DataDownload() as client:
                return await client.download(url)

        except RateLimitError as e:
            if attempt < max_retries - 1:
                # Retry-After header automatically parsed
                print(f"Rate limited. Waiting {e.retry_after}s...")
                await asyncio.sleep(e.retry_after)
            else:
                raise
```

### Exception Context

Every exception includes rich debugging context:

```python
try:
    result = await client.download(url)
except NotFoundError as e:
    # Access exception attributes
    print(f"Message: {e.message}")
    print(f"URL: {e.url}")
    print(f"Status: {e.status_code}")
    print(f"Response excerpt: {e.response_excerpt[:100]}")

    # Access original response
    if e.response:
        print(f"Headers: {e.response.headers}")

    # Access root cause
    if e.cause:
        print(f"Root cause: {type(e.cause).__name__}")

    # Custom context dictionary
    if e.context:
        print(f"Context: {e.context}")
```

### Exception Factory

Use `classify_http_error()` to create appropriate exception from status code:

```python
from download.exceptions import classify_http_error

# Automatically creates NotFoundError, RateLimitError, etc.
error = classify_http_error(
    status_code=404,
    url="https://www.sec.gov/missing.json",
    response=response,
    excerpt="Page not found"
)
raise error
```

### Complete Example

See [examples/exception_handling_demo.py](../../examples/exception_handling_demo.py) for comprehensive examples demonstrating:

1. Basic error handling with specific exception types
2. Smart rate limit handling with automatic retry
3. Network error handling (timeout, DNS, connection)
4. Content error handling (payload size, decompression)
5. Hierarchical exception catching
6. Using error context for debugging

## Testing

The package includes comprehensive tests:

```bash
# Test DataDownload functionality
python tests/download/test_download_request.py

# Test FileDownload functionality  
python tests/download/test_file_download.py

# Test rate limiting
python tests/download/test_download_rate_limiter.py
```

## Performance Considerations

1. **Rate Limiting**: Process-wide token bucket limiter (default 8 requests/second, shared across all clients)
2. **Connection Pooling**: Reuses HTTP connections for efficiency
3. **Streaming**: FileDownload supports streaming for large files
4. **Memory Safety**: Configurable max decompressed size prevents bombs
5. **Concurrent Limits**: Per-host semaphores prevent overwhelming servers

## API Reference

### Core Classes

- **`DataDownload(settings: Optional[DownloadSettings] = None)`**: Async client for processed downloads
  - `async download(url: str, override_kind: Optional[str] = None) -> DataDownloadResult`

- **`FileDownload(settings: Optional[DownloadSettings] = None, download_dir: Optional[Path] = None)`**: Async client for raw file downloads
  - `async download(url: str, save_path: Optional[Path] = None, stream_to_disk: bool = True, chunk_size: int = 8192) -> FileDownloadResult`

- **`BaseDownload(settings: Optional[DownloadSettings] = None)`**: Abstract base class for custom implementations
  - `async _do_request_with_retry(method: str, url: str, stream: bool = False) -> httpx.Response`
  - `async _apply_rate_limit() -> None`
  - `_sem_for_host(host: str) -> asyncio.Semaphore`
  - `_get_host_from_url(url: str) -> str`

### Result Models

- **`DataDownloadResult`**: Processed download result
  - `url: str` - Final URL after redirects
  - `status_code: int` - HTTP status code
  - `headers: Mapping[str, str]` - Response headers
  - `content_type: Optional[str]` - Normalized content type
  - `kind: str` - Content classification
  - `text: Optional[str]` - Decoded text content
  - `bytes_: Optional[bytes]` - Raw bytes
  - `charset: Optional[str]` - Character encoding
  - `duration_ms: int` - Download duration
  - `size_bytes: int` - Payload size
  - `sniff_note: Optional[str]` - Detection notes

- **`FileDownloadResult`**: Raw file download result
  - `url: str` - Final URL
  - `status_code: int` - HTTP status
  - `headers: Mapping[str, str]` - Response headers
  - `content_type: Optional[str]` - Content-Type header
  - `content_encoding: Optional[str]` - Content-Encoding header
  - `file_path: Optional[Path]` - File path (if saved to disk)
  - `bytes_: Optional[bytes]` - Raw bytes (if in memory)
  - `duration_ms: int` - Download duration
  - `size_bytes: int` - File size
  - `saved_to_disk: bool` - Whether saved to disk

### Configuration

- **`DownloadSettings`**: Download configuration
  - `user_agent: str` - User-Agent header (default: "edgarSYS j.jansenbravo@gmail.com")
  - `base_url: str` - Base URL (default: "https://www.sec.gov")
  - `requests_per_second: int` - Rate limit (default: 8)
  - `max_concurrency_per_host: int` - Per-host semaphore limit (default: 6)
  - `http2: bool` - Enable HTTP/2 (default: False)
  - `retry: RetryPolicy` - Retry configuration
  - `timeouts: Timeouts` - Timeout configuration
  - `max_decompressed_size_mb: int` - Payload size limit (default: 200)

- **`RetryPolicy`**: Retry behavior
  - `attempts: int` - Max retry attempts (default: 5)
  - `base_delay_ms: int` - Base backoff delay (default: 500)
  - `respect_retry_after: bool` - Honor Retry-After header (default: True)

- **`Timeouts`**: Timeout configuration
  - `connect: float` - Connection timeout (default: 2.0s)
  - `read: float` - Read timeout (default: 120.0s)
  - `write: float` - Write timeout (default: 10.0s)
  - `pool: float` - Pool timeout (default: 2.0s)

### Exception Types

See [Error Handling](#error-handling) section for complete exception hierarchy and usage examples.

### Utility Functions

- **`normalize_content_type(headers: httpx.Headers) -> Optional[str]`**: Extract normalized content type
- **`extract_charset(headers: httpx.Headers) -> Optional[str]`**: Extract charset from headers
- **`classify_kind(content_type: Optional[str], data: bytes) -> Tuple[str, Optional[str]]`**: Classify content kind
- **`decode_text(data: bytes, charset: Optional[str]) -> Tuple[str, Optional[str]]`**: Decode bytes to text
- **`decompress_transfer(body: bytes, content_encoding: Optional[str]) -> bytes`**: Decompress transfer encoding
- **`retry_after_from_response(response: Optional[httpx.Response]) -> float`**: Parse Retry-After header
- **`classify_http_error(status_code: int, url: str, response: Optional[httpx.Response] = None, excerpt: Optional[str] = None) -> HTTPError`**: Create appropriate HTTPError subclass

## Future Enhancements

- [ ] Object store integration (S3, Azure Blob) for FileDownload
- [ ] Caching layer for frequently accessed documents
- [ ] Download progress callbacks
