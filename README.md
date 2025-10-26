# http-dl

An asynchronous download toolkit for HTTP and SEC EDGAR workloads. The library wraps `httpx` with process-wide rate limiting, resilient retry logic, and content-aware response handling so application code can focus on business logic instead of transport client concerns.The package offers two primary download modes:

- **DataDownload**: Processes and decodes content (text decoding, decompression, classification)
- **FileDownload**: Downloads raw files without processing (preserves the original encoding)


## Features

- **Global Throttling** - every client instance shares the same token bucket limiter, preventing accidental rate-limit violations.
- **Typed Configuration Models** - `DownloadSettings`, `RetryPolicy`, and `Timeouts` provide predictable knobs for tuning throughput, retries, and headers.
- **Download Modes** - `DataDownload` decodes and classifies content, whereas `FileDownload` streams raw bytes to disk or memory.
- **Redirect Handling** - configurable redirect following with loop detection, chain tracking, and configurable limits (up to 20 redirects by default).
- **Rich Exception Hierarchy** - 20+ purpose-built errors surface actionable metadata for metrics, retry loops, and logging.
- **Async-first design** - built on `httpx.AsyncClient`, built to be thread-safe ready for high concurrency workloads.

## Quickstart

### DataDownload Usage
```python
import asyncio
from httpdl import DataDownload, DownloadSettings, RetryPolicy, Timeouts

settings = DownloadSettings(
    user_agent="MyApp/1.0 (ops@example.com)",
    requests_per_second=6,
    retry=RetryPolicy(attempts=3),
    timeouts=Timeouts(read=60.0),
    follow_redirects=True,  # Enable redirect following (default: True)
    max_redirects=20,       # Maximum redirect chain length (default: 20)
)

async def main() -> None:
    async with DataDownload(settings) as client:
        result = await client.download("https://www.sec.gov/files/company_tickers.json")
        print(result.kind, result.size_bytes)

        # Check if URL was redirected
        if result.redirect_chain:
            print(f"Redirected through: {' -> '.join(result.redirect_chain)}")

asyncio.run(main())
```

### File Download Usage

```python
import asyncio
from pathlib import Path
from httpdl import FileDownload

async def main() -> None:
    async with FileDownload(download_dir=Path("downloads")) as client:
        filing = await client.download(
            "https://www.sec.gov/Archives/edgar/data/1318605/000095017023001409/tsla-20221231.htm"
        )
        print("Saved:", filing.file_path, "bytes:", filing.size_bytes)

asyncio.run(main())
```

## Architecture Overview

```
httpdl/
|-- __init__.py          # Export surface
|-- core.py              # BaseDownload (lifecycle, retries, semaphores)
|-- download.py          # DataDownload / FileDownload implementations
|-- exceptions.py        # Exception hierarchy and helpers
|-- limiting.py          # Process-wide token bucket limiter
|-- utils.py             # Content sniffing / decoding helpers
`-- models/
    |-- config.py        # DownloadSettings, RetryPolicy, Timeouts
    `-- result.py        # DataDownloadResult, FileDownloadResult
```

Supplementary documentation lives under `docs/`:

- [Download Clients](docs/download.md)
- [Rate Limiting](docs/limiting.md)
- [Exceptions](docs/exceptions.md)
- [Models](docs/models.md)

## Key Concepts

### Rate Limiting

- A singleton `AsyncTokenBucket` enforces the strictest
  `requests_per_second` requested by any `DownloadSettings`.
- `BaseDownload._apply_rate_limit()` is called before every network request.
- For tuning guidance and implementation details, see
  [docs/limiting.md](docs/limiting.md).

### Configuration Models

- `DownloadSettings` aggregates HTTP headers, rate/concurrency controls, retry
  behavior, timeouts, and safety limits.
- Nested dataclasses (`RetryPolicy`, `Timeouts`) use `default_factory` to avoid
  shared mutable state.
- Field-by-field documentation is available in [docs/models.md](docs/models.md).

### Download Clients

- `DataDownload` is optimized for structured content: it decompresses transfer
  encodings, classifies media types, and decodes to text where possible.
- `FileDownload` streams raw responses to disk (or memory) without altering the
  payload.
- Both clients inherit from `BaseDownload`, gaining retry logic, redirect
  handling, per-host semaphores, and lifecycle management. A deeper walkthrough
  is in [docs/download.md](docs/download.md).

### Redirect Handling

- Automatically follows HTTP redirects (301, 302, 303, 307, 308) when
  `follow_redirects=True` (default).
- Tracks the complete redirect chain in result objects (`redirect_chain` field).
- Detects and prevents infinite redirect loops with `RedirectLoopError`.
- Enforces configurable limits with `max_redirects` (default: 20).
- Properly handles relative redirect URLs and HTTP method conversion (303 → GET).
- Can be disabled by setting `follow_redirects=False` in `DownloadSettings`.

### Exceptions

- All errors inherit from `DownloadError` so callers can both catch broadly and
  target specific failure domains (validation, networking, HTTP status,
  content, retry budget).
- Utility helpers such as `retry_after_from_response` and
  `classify_http_error` keep error handling consistent across the codebase.
- Consult [docs/exceptions.md](docs/exceptions.md) for hierarchy diagrams and
  recipes.

## Testing

```bash
pytest
```

Useful focused test cases:

- `tests/test_data_download.py`
- `tests/test_file_download.py`
- `tests/test_rate_limiter.py`
- `tests/test_exceptions.py`

## Roadmap

- Object-store integration for `FileDownload` (S3, Azure Blob, ...)
- Pluggable caching layer for frequently accessed filings
- Download progress reporting hooks

## Contributing

- Open an issue describing the proposed change or bug fix.
- Ensure new code paths include tests and, where applicable, documentation
  updates under `docs/`.
- Run `pytest` locally before opening a pull request.
