# http-dl

[![PyPI version](https://badge.fury.io/py/http-dl.svg)](https://badge.fury.io/py/http-dl)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Production-ready async HTTP client for data-intensive workloads**

Built for SEC EDGAR scraping and enterprise data pipelines, http-dl provides industrial-strength HTTP operations with multi-process rate limiting, HTTP/2 support, resumable downloads, and comprehensive observability.

## Features

### 🚀 Performance & Scalability
- **HTTP/2 by default** - Multiplexed connections, better TLS performance
- **Multi-process rate limiting** - Redis or multiprocessing.Manager backends
- **Optimized connection pooling** - 100 max connections, 20 keepalive
- **Async-first** - Built on httpx.AsyncClient for high concurrency

### 💪 Reliability
- **Resumable downloads** - ETag validation, Range header support
- **Checksum validation** - MD5, SHA256, SHA512 verification
- **Automatic retries** - Exponential backoff with jitter
- **Comprehensive exceptions** - 20+ typed errors for precise handling

### 📊 Observability
- **Built-in metrics** - Request counts, latency percentiles, error rates
- **Structured logging** - Dependency-injectable logger adapters
- **Progress callbacks** - Real-time download progress tracking

### 🛠️ Enterprise Features
- **Session persistence** - Cookie jar management with disk storage
- **Stealth mode** - User-Agent rotation, browser fingerprinting
- **Batch operations** - Concurrent downloads with semaphore control
- **Flexible backends** - In-memory, Redis, or multiprocessing

## Installation

```bash
# Basic installation
pip install http-dl

# With Redis support for distributed rate limiting
pip install 'http-dl[redis]'

# All optional dependencies
pip install 'http-dl[all]'
```

## Quick Start

### Basic Usage

```python
import asyncio
from httpdl import DataDownload, DownloadSettings

async def main():
    settings = DownloadSettings(
        user_agent="MyApp/1.0 (contact@example.com)",
        requests_per_second=10,
        http2=True,  # Enabled by default
    )

    async with DataDownload(settings) as client:
        result = await client.download("https://www.sec.gov/files/company_tickers.json")
        print(f"Downloaded {result.size_bytes} bytes")
        print(f"Content type: {result.kind}")

asyncio.run(main())
```

### Multi-Process Rate Limiting (Celery, multiprocessing)

```python
from httpdl import DataDownload, DownloadSettings

# Redis backend (recommended for Celery workers)
settings = DownloadSettings(
    user_agent="DataPipeline/1.0",
    requests_per_second=8,
    rate_limit_backend="redis",
    redis_url="redis://localhost:6379",
    redis_key_prefix="sec:ratelimit"
)

# All workers now share the same rate limit
async with DataDownload(settings) as client:
    result = await client.download(url)
```

### Resumable Downloads with Checksum Validation

```python
from pathlib import Path
from httpdl.streaming import StreamingDownload

async with StreamingDownload() as client:
    result = await client.download(
        url="https://example.com/large-file.zip",
        file_path=Path("downloads/file.zip"),
        checksum_type="sha256",
        expected_checksum="abc123...",
        resume=True,  # Automatically resumes if interrupted
        progress_callback=lambda curr, total: print(f"{curr}/{total}")
    )
```

### Batch Downloads

```python
from httpdl.concurrency import download_batch

urls = [
    "https://www.sec.gov/files/company_tickers.json",
    "https://www.sec.gov/files/company_tickers_exchange.json",
    # ... more URLs
]

result = await download_batch(
    urls=urls,
    max_concurrent=10,
    on_success=lambda r: print(f"✓ {r.url}"),
    on_error=lambda url, e: print(f"✗ {url}: {e}")
)

print(f"Success rate: {result.success_rate:.1f}%")
```

### Metrics & Monitoring

```python
from httpdl.metrics import get_metrics_collector, format_snapshot

collector = get_metrics_collector()

# Make requests...
async with DataDownload() as client:
    for url in urls:
        await client.download(url)

# Get metrics snapshot
snapshot = collector.get_snapshot()
print(format_snapshot(snapshot))

# Output:
# === HTTP Metrics Snapshot ===
# Total Requests: 1000
#   Successful: 987
#   Failed: 13
#   Success Rate: 98.70%
```

### Stealth Mode (User-Agent Rotation)

```python
from httpdl.stealth import UserAgentRotator

rotator = UserAgentRotator(mode="desktop")

settings = DownloadSettings(
    user_agent=rotator.get_random_user_agent(),
    rotate_user_agent=True
)

async with DataDownload(settings) as client:
    result = await client.download(url)
```

### Session Persistence

```python
from pathlib import Path
from httpdl.session import SessionManager

session_mgr = SessionManager(session_file=Path("session.json"))

async with DataDownload() as client:
    # Load saved session
    await session_mgr.load_session(client._client)

    # Make authenticated requests
    await client.download("https://example.com/protected")

    # Save session for next run
    await session_mgr.save_session(client._client)
```

## Documentation

- [Download Clients](docs/download.md) - DataDownload vs FileDownload
- [Rate Limiting](docs/limiting.md) - Multi-process backends
- [Streaming Downloads](docs/streaming.md) - Resumable downloads
- [Metrics](docs/metrics.md) - Monitoring and observability
- [Concurrency](docs/concurrency.md) - Batch operations
- [Stealth Mode](docs/stealth.md) - User-Agent rotation
- [Session Management](docs/session.md) - Cookie persistence
- [Logging](docs/logging.md) - Structured logging
- [Exceptions](docs/exceptions.md) - Error handling
- [Models](docs/models.md) - Configuration and results

## Migration from 0.1.x to 0.2.0

### HTTP/2 Now Enabled by Default
```python
# Old (0.1.x): HTTP/2 disabled by default
settings = DownloadSettings()  # http2=False

# New (0.2.0): HTTP/2 enabled by default
settings = DownloadSettings()  # http2=True

# To disable HTTP/2:
settings = DownloadSettings(http2=False)
```

### Multi-Process Rate Limiting
```python
# Old (0.1.x): Only in-memory rate limiting
settings = DownloadSettings(requests_per_second=8)

# New (0.2.0): Redis backend for distributed workers
settings = DownloadSettings(
    requests_per_second=8,
    rate_limit_backend="redis",
    redis_url="redis://localhost:6379"
)
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=httpdl --cov-report=html

# Run specific test file
pytest tests/test_streaming.py
```

## License

MIT License - see LICENSE file for details.

## Credits

Built by [retnah](https://retnah.com) for production SEC EDGAR data pipelines.

Powered by:
- [httpx](https://www.python-httpx.org/) - HTTP/2 support
- [aiofiles](https://github.com/Tinche/aiofiles) - Async file I/O
- [redis](https://github.com/redis/redis-py) (optional) - Distributed rate limiting
