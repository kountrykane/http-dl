# Logging

`http-dl` provides comprehensive structured logging for HTTP operations with a dependency-injectable architecture that keeps the library decoupled from specific logging implementations.

## Table of Contents

- [Architecture](#architecture)
- [Basic Usage](#basic-usage)
- [Dependency Injection](#dependency-injection)
- [Event Taxonomy](#event-taxonomy)
- [Integration Examples](#integration-examples)
- [Best Practices](#best-practices)

## Architecture

### Design Philosophy

The logging system follows the same dependency injection pattern as [datura](https://github.com/yourusername/datura), designed for:

1. **Decoupling**: `http-dl` doesn't depend on specific logging libraries
2. **Flexibility**: Applications can inject any `LoggerAdapter`-compatible logger
3. **Default Experience**: Works out-of-box with Python's `logging` module
4. **Zero Configuration**: Logging is optional; library works without setup

### Components

```
httpdl.logging
├── HttpdlLoggerAdapter       # Thin wrapper with httpdl-specific helpers
├── configure_logging()        # Global logger factory configuration
├── get_httpdl_logger()        # Factory function for creating loggers
└── Helper functions:
    ├── log_timing()           # Context manager for timing operations
    ├── log_exception()        # Exception logging with context
    ├── log_retry()            # Retry attempt logging
    ├── log_redirect()         # HTTP redirect logging
    ├── log_rate_limit()       # Rate limiter wait logging
    └── log_content_processing() # Content processing operations
```

## Basic Usage

### Default Logging (Standard Library)

By default, `http-dl` uses Python's standard `logging` module:

```python
import logging
import asyncio
from httpdl import DataDownload

# Configure Python logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def main():
    async with DataDownload() as client:
        result = await client.download("https://www.sec.gov/files/company_tickers.json")
        # Logs automatically go to configured handlers

asyncio.run(main())
```

**Output:**
```
2025-01-15 10:30:45 - httpdl.core - INFO - request.started method=GET url=https://www.sec.gov/files/company_tickers.json
2025-01-15 10:30:46 - httpdl.core - INFO - request.completed status_code=200 duration_ms=850.23
2025-01-15 10:30:46 - httpdl.download - INFO - download.completed kind=json size_bytes=1024
```

### Adjusting Log Levels

```python
import logging

# Show debug logs for detailed HTTP operations
logging.getLogger('httpdl').setLevel(logging.DEBUG)

# Only show warnings and errors
logging.getLogger('httpdl').setLevel(logging.WARNING)

# Disable httpdl logging entirely
logging.getLogger('httpdl').setLevel(logging.CRITICAL + 1)
```

## Dependency Injection

### Method 1: Logger per Client (Recommended)

Inject a custom logger via `DownloadSettings.logger`:

```python
from httpdl import DataDownload, DownloadSettings
from httpdl.logging import get_httpdl_logger

# Create a custom logger with context
logger = get_httpdl_logger(
    __name__,
    url="https://www.sec.gov",
    job_id="batch_001",
    tenant="acme_corp"
)

settings = DownloadSettings(logger=logger)

async with DataDownload(settings) as client:
    result = await client.download("https://www.sec.gov/files/company_tickers.json")
    # All operations use the custom logger with bound context
```

### Method 2: Global Logger Factory

Configure a global logger factory for all `http-dl` instances:

```python
from httpdl.logging import configure_logging
from my_app.logging import create_structured_logger

# Your custom logger factory
def my_logger_factory(name: str, **context):
    return create_structured_logger(name, **context)

# Configure globally
configure_logging(logger_factory=my_logger_factory)

# Now all DataDownload/FileDownload instances use your logger
async with DataDownload() as client:
    result = await client.download(url)
```

### Method 3: Structlog Integration

Example integration with `structlog`:

```python
import structlog
from logging import LoggerAdapter

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

def structlog_factory(name: str, **context) -> LoggerAdapter:
    """Factory that returns a LoggerAdapter wrapping structlog."""
    logger = structlog.get_logger(name)

    # Wrap structlog logger in LoggerAdapter-compatible interface
    class StructlogAdapter(LoggerAdapter):
        def __init__(self, logger, extra):
            self.logger = logger
            self.extra = extra or {}

        def process(self, msg, kwargs):
            # Merge bound context with kwargs
            kwargs.setdefault('extra', {}).update(self.extra)
            return msg, kwargs

        def debug(self, msg, *args, **kwargs):
            extra = kwargs.pop('extra', {})
            self.logger.debug(msg, **extra)

        def info(self, msg, *args, **kwargs):
            extra = kwargs.pop('extra', {})
            self.logger.info(msg, **extra)

        def warning(self, msg, *args, **kwargs):
            extra = kwargs.pop('extra', {})
            self.logger.warning(msg, **extra)

        def error(self, msg, *args, **kwargs):
            extra = kwargs.pop('extra', {})
            exc_info = kwargs.pop('exc_info', None)
            if exc_info:
                extra['exc_info'] = exc_info
            self.logger.error(msg, **extra)

    return StructlogAdapter(logger, context)

# Configure http-dl to use structlog
from httpdl.logging import configure_logging
configure_logging(logger_factory=structlog_factory)

async with DataDownload() as client:
    result = await client.download(url)
```

**Structured JSON Output:**
```json
{"event": "request.started", "level": "info", "timestamp": "2025-01-15T10:30:45.123Z", "method": "GET", "url": "https://www.sec.gov/files/company_tickers.json"}
{"event": "request.completed", "level": "info", "timestamp": "2025-01-15T10:30:46.000Z", "status_code": 200, "duration_ms": 850.23}
```

## Event Taxonomy

### Request Lifecycle Events

#### `client.initialized`
**Level:** DEBUG
**Location:** `BaseDownload.__aenter__`
**Context:**
- `http2`: HTTP/2 enabled flag
- `requests_per_second`: Rate limit setting
- `max_concurrency_per_host`: Concurrency setting

#### `client.closed`
**Level:** DEBUG
**Location:** `BaseDownload.__aexit__`

#### `request.started`
**Level:** INFO
**Location:** `BaseDownload._do_request_with_retry`
**Context:**
- `method`: HTTP method (GET, POST, etc.)
- `url`: Target URL
- `host`: Target hostname

#### `request.completed`
**Level:** INFO
**Location:** `BaseDownload._do_request_with_retry`
**Context:**
- `method`: HTTP method
- `url`: Target URL
- `host`: Target hostname
- `status_code`: HTTP status code
- `redirect_count`: Number of redirects followed
- `attempts`: Total attempts (including retries)
- `duration_ms`: Total duration in milliseconds

#### `request.failed`
**Level:** ERROR
**Location:** `BaseDownload._do_request_with_retry`
**Context:**
- `method`: HTTP method
- `url`: Target URL
- `host`: Target hostname
- `error_type`: Error category (connection_error, timeout, dns_error, network_error, rate_limit)
- `attempts`: Total attempts before failure
- `duration_ms`: Total duration
- `exc_info`: Exception object (for traceback)
- Additional fields depending on `error_type`:
  - `timeout_type`: For timeout errors (connect, read, write, pool)
  - `status_code`, `retry_after`: For rate limit errors

### Retry Events

#### `request.retry`
**Level:** WARNING
**Location:** `BaseDownload._do_request_with_retry` (via `log_retry()`)
**Context:**
- `attempt`: Current attempt number (0-indexed)
- `max_attempts`: Maximum retry attempts
- `delay_ms`: Backoff delay in milliseconds
- `reason`: Retry reason (connection_error, timeout, dns_error, rate_limit_429, server_error_503, etc.)
- `method`: HTTP method
- `url`: Target URL
- `status_code`: HTTP status (for server errors)

### Redirect Events

#### `redirect.loop_detected`
**Level:** ERROR
**Location:** `BaseDownload._follow_redirects`
**Context:**
- `from_url`: Source URL
- `to_url`: Target URL (already visited)
- `redirect_count`: Number of redirects
- `redirect_chain`: List of URLs in chain

#### `redirect.too_many`
**Level:** ERROR
**Location:** `BaseDownload._follow_redirects`
**Context:**
- `redirect_count`: Actual redirect count
- `max_redirects`: Configured limit
- `redirect_chain`: List of URLs in chain

#### `request.redirect`
**Level:** DEBUG
**Location:** `BaseDownload._follow_redirects` (via `log_redirect()`)
**Context:**
- `from_url`: Source URL
- `to_url`: Redirect target
- `status_code`: HTTP redirect status (301, 302, 303, 307, 308)
- `redirect_count`: Current position in chain

### Rate Limiting Events

#### `token_bucket.initialized`
**Level:** DEBUG
**Location:** `AsyncTokenBucket.__init__`
**Context:**
- `rate`: Requests per second
- `capacity`: Token bucket capacity

#### `token_bucket.reconfigured`
**Level:** INFO
**Location:** `AsyncTokenBucket.configure`
**Context:**
- `new_rate`: Updated rate
- `new_capacity`: Updated capacity
- `rate_changed`: Boolean flag
- `capacity_changed`: Boolean flag

#### `rate_limit.wait`
**Level:** DEBUG
**Location:** `AsyncTokenBucket.wait` (via `log_rate_limit()`)
**Context:**
- `wait_ms`: Wait duration in milliseconds
- `tokens_requested`: Number of tokens requested

### Download Events (DataDownload)

#### `download.started`
**Level:** DEBUG
**Location:** `DataDownload.download`
**Context:**
- `url`: Target URL
- `override_kind`: Optional content kind override

#### `download.invalid_url`
**Level:** ERROR
**Location:** `DataDownload.download`
**Context:**
- `url`: Invalid URL value

#### `download.body_read`
**Level:** DEBUG
**Location:** `DataDownload.download`
**Context:**
- `url`: Target URL
- `raw_size_bytes`: Raw response body size

#### `download.decompression_failed`
**Level:** ERROR
**Location:** `DataDownload.download` (via `log_exception()`)
**Context:**
- `url`: Target URL
- `encoding`: Content-Encoding header value
- `error_type`: Exception class name
- `error_message`: Exception message
- `exc_info`: Exception object

#### `download.payload_too_large`
**Level:** ERROR
**Location:** `DataDownload.download`
**Context:**
- `url`: Target URL
- `actual_size`: Decompressed size in bytes
- `max_size`: Configured size limit

#### `download.http_error`
**Level:** ERROR
**Location:** `DataDownload.download`
**Context:**
- `url`: Target URL
- `status_code`: HTTP error status (4xx/5xx)
- `excerpt`: Response body excerpt (first 100 chars)

#### `download.completed`
**Level:** INFO
**Location:** `DataDownload.download`
**Context:**
- `url`: Target URL
- `status_code`: HTTP status code
- `kind`: Content classification (json, xml, html, sgml, atom, archive, binary, unknown)
- `size_bytes`: Decompressed content size
- `duration_ms`: Total duration
- `redirect_count`: Number of redirects

### Content Processing Events

#### `content.decompress`
**Level:** DEBUG
**Location:** `DataDownload.download` (via `log_content_processing()`)
**Context:**
- `operation`: "decompress"
- `content_type`: Content-Type header
- `size_bytes`: Decompressed size
- `compression`: Content-Encoding (gzip, deflate, br)
- `url`: Target URL

#### `content.classify`
**Level:** DEBUG
**Location:** `DataDownload.download` (via `log_content_processing()`)
**Context:**
- `operation`: "classify"
- `content_type`: Content-Type header
- `charset`: Detected charset
- `size_bytes`: Content size
- `kind`: Classification result
- `sniff_note`: Classification notes
- `url`: Target URL

#### `content.decode`
**Level:** DEBUG
**Location:** `DataDownload.download` (via `log_content_processing()`)
**Context:**
- `operation`: "decode"
- `content_type`: Content-Type header
- `charset`: Used charset
- `size_bytes`: Decoded text size
- `kind`: Content kind
- `url`: Target URL

### File Download Events (FileDownload)

#### `file_download.dir_initialized`
**Level:** DEBUG
**Location:** `FileDownload.__init__`
**Context:**
- `download_dir`: Download directory path

#### `file_download.started`
**Level:** DEBUG
**Location:** `FileDownload.download`
**Context:**
- `url`: Target URL
- `stream_to_disk`: Streaming mode flag
- `save_path`: Target file path (if specified)

#### `file_download.invalid_url`
**Level:** ERROR
**Location:** `FileDownload.download`
**Context:**
- `url`: Invalid URL value

#### `file_download.streaming_to_disk`
**Level:** DEBUG
**Location:** `FileDownload.download`
**Context:**
- `url`: Target URL
- `file_path`: Target file path

#### `file_download.stream_completed`
**Level:** DEBUG
**Location:** `FileDownload.download`
**Context:**
- `url`: Target URL
- `size_bytes`: Downloaded file size
- `file_path`: Saved file path

#### `file_download.loading_to_memory`
**Level:** DEBUG
**Location:** `FileDownload.download`
**Context:**
- `url`: Target URL

#### `file_download.memory_load_completed`
**Level:** DEBUG
**Location:** `FileDownload.download`
**Context:**
- `url`: Target URL
- `size_bytes`: Downloaded size

#### `file_download.completed`
**Level:** INFO
**Location:** `FileDownload.download`
**Context:**
- `url`: Target URL
- `saved_to_disk`: Boolean flag
- `size_bytes`: File size
- `duration_ms`: Total duration
- `content_type`: Content-Type header

## Integration Examples

### Production Monitoring with DataDog

```python
import datadog
from logging import LoggerAdapter
from httpdl.logging import configure_logging

def datadog_logger_factory(name: str, **context) -> LoggerAdapter:
    """Factory for DataDog APM integration."""

    class DataDogAdapter(LoggerAdapter):
        def __init__(self, logger, extra):
            self.logger = logger
            self.extra = extra or {}

        def _emit(self, level, msg, **kwargs):
            extra = kwargs.pop('extra', {})
            merged = {**self.extra, **extra}

            # Send to DataDog
            datadog.api.Event.create(
                title=msg,
                text=str(merged),
                tags=[f"{k}:{v}" for k, v in merged.items()],
                alert_type=level
            )

        def info(self, msg, *args, **kwargs):
            self._emit('info', msg, **kwargs)

        def error(self, msg, *args, **kwargs):
            self._emit('error', msg, **kwargs)

    logger = logging.getLogger(name)
    return DataDogAdapter(logger, context)

configure_logging(logger_factory=datadog_logger_factory)
```

### Application-Specific Context

```python
from httpdl import DataDownload, DownloadSettings
from httpdl.logging import get_httpdl_logger

async def download_sec_filing(cik: str, accession: str, user_id: str):
    """Download with enriched logging context."""

    logger = get_httpdl_logger(
        __name__,
        cik=cik,
        accession=accession,
        user_id=user_id,
        job_type="sec_filing_download"
    )

    settings = DownloadSettings(logger=logger)

    async with DataDownload(settings) as client:
        url = f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={cik}&accession_number={accession}"
        result = await client.download(url)

        # All logs include cik, accession, user_id context
        return result
```

### Error Tracking with Sentry

```python
import sentry_sdk
from logging import LoggerAdapter
from httpdl.logging import configure_logging

def sentry_logger_factory(name: str, **context) -> LoggerAdapter:
    """Factory for Sentry error tracking."""

    class SentryAdapter(LoggerAdapter):
        def __init__(self, logger, extra):
            self.logger = logger
            self.extra = extra or {}

        def error(self, msg, *args, **kwargs):
            extra = kwargs.pop('extra', {})
            exc_info = kwargs.pop('exc_info', None)

            merged = {**self.extra, **extra}

            # Capture in Sentry
            with sentry_sdk.push_scope() as scope:
                for key, value in merged.items():
                    scope.set_context(key, value)

                if exc_info:
                    sentry_sdk.capture_exception(exc_info)
                else:
                    sentry_sdk.capture_message(msg, level='error')

            # Also log normally
            self.logger.error(msg, extra=merged, exc_info=exc_info)

    logger = logging.getLogger(name)
    return SentryAdapter(logger, context)

configure_logging(logger_factory=sentry_logger_factory)
```

## Best Practices

### 1. Use Appropriate Log Levels

- **DEBUG**: Detailed HTTP operations, internal state changes
- **INFO**: Successful requests, downloads completed
- **WARNING**: Retries, recoverable errors
- **ERROR**: Fatal errors, exhausted retries

```python
# Production: INFO and above
logging.getLogger('httpdl').setLevel(logging.INFO)

# Development: DEBUG for troubleshooting
logging.getLogger('httpdl').setLevel(logging.DEBUG)
```

### 2. Add Application Context

Bind application-specific context for better observability:

```python
logger = get_httpdl_logger(
    __name__,
    tenant_id="acme",
    batch_id="20250115_001",
    environment="production"
)
```

### 3. Monitor Key Metrics

Track these events for production monitoring:

- `request.completed` → Success rate, latency percentiles
- `request.failed` → Error rate by `error_type`
- `request.retry` → Retry frequency by `reason`
- `rate_limit.wait` → Rate limiting effectiveness
- `download.payload_too_large` → Content size issues

### 4. Structure Error Handling

Use structured logging with exceptions:

```python
try:
    result = await client.download(url)
except DownloadError as e:
    logger.error(
        "download_failed",
        url=url,
        error_type=type(e).__name__,
        exc_info=e
    )
    raise
```

### 5. Aggregate Redirect Analytics

Track redirect patterns:

```python
result = await client.download(url)

if result.redirect_chain:
    logger.info(
        "redirects_followed",
        url=url,
        final_url=result.url,
        redirect_count=len(result.redirect_chain),
        redirect_chain=result.redirect_chain
    )
```

### 6. Performance Monitoring

Use timing context for custom operations:

```python
from httpdl.logging import log_timing

with log_timing(logger, "batch_download", batch_size=100):
    for url in urls:
        result = await client.download(url)
```

### 7. Avoid Log Spam

Rate limit debug logs in hot paths:

```python
# Bad: Logs every iteration
for i in range(10000):
    logger.debug("processing", index=i)

# Good: Periodic logging
for i in range(10000):
    if i % 1000 == 0:
        logger.info("progress", processed=i, total=10000)
```

## Comparison with Datura

`http-dl` logging follows the same architectural patterns as [datura](https://github.com/yourusername/datura):

| Feature | http-dl | datura |
|---------|---------|--------|
| **Architecture** | Dependency injection via LoggerAdapter | Same |
| **Default Backend** | Python stdlib logging | Same |
| **Injection Methods** | Settings field + global factory | Same |
| **Event Naming** | Dot notation (request.started) | Same |
| **Context Binding** | Via logger kwargs | Same |
| **Helper Functions** | log_timing, log_exception, etc. | Same |

**Key Differences:**

- **Domain**: HTTP transport operations vs. SEC document processing
- **Event Taxonomy**: Network-focused vs. document-focused
- **Context Fields**: URLs, status codes, retries vs. CIK, accession, document types

Both libraries can share the same logger factory in applications that use both:

```python
from httpdl.logging import configure_logging as configure_httpdl_logging
from datura.logging import configure_logging as configure_datura_logging

# Single logger factory for both libraries
configure_httpdl_logging(logger_factory=my_structlog_factory)
configure_datura_logging(logger_factory=my_structlog_factory)
```

## Troubleshooting

### Logs Not Appearing

```python
import logging

# Ensure basic configuration
logging.basicConfig(level=logging.DEBUG)

# Or configure specific handler
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
logging.getLogger('httpdl').addHandler(handler)
```

### Duplicate Logs

Disable propagation if seeing duplicates:

```python
logging.getLogger('httpdl').propagate = False
```

### Missing Context Fields

Ensure logger adapter passes `extra` dict:

```python
class MyAdapter(LoggerAdapter):
    def process(self, msg, kwargs):
        # Include 'extra' in kwargs
        kwargs.setdefault('extra', {}).update(self.extra)
        return msg, kwargs
```

### Performance Impact

Logging overhead is minimal (~1-2% for INFO level). For maximum performance:

```python
# Disable all httpdl logging
logging.getLogger('httpdl').disabled = True
```

## See Also

- [DownloadSettings](models.md#downloadsettings) - Configuration including logger field
- [Exceptions](exceptions.md) - Exception types logged by http-dl
- [Rate Limiting](limiting.md) - Rate limiter log events
