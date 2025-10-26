# Exceptions Guide

This document describes the exception model used throughout `httpdl`. The goal is
to make error handling predictable without requiring every consumer to inspect
`httpdl/exceptions.py`.

## Design Overview

- A single root type, `DownloadError`, carries rich context (`url`, `response`,
  wrapped `cause`, `context` dict) and backs every other exception.
- Subclasses are grouped by failure domain: validation, network, HTTP status,
  content processing, and retry control.
- Exceptions are raised from `BaseDownload` and its subclasses (`DataDownload`,
  `FileDownload`) so that consumers can target only the categories they need.

```
DownloadError
├─ ValidationError
│  ├─ InvalidURLError
│  └─ InvalidSettingsError
├─ PayloadSizeLimitError
├─ NetworkError
│  ├─ ConnectionError
│  ├─ TimeoutError
│  └─ DNSResolutionError
├─ HTTPError
│  ├─ ClientError (4xx)
│  │  ├─ BadRequestError
│  │  ├─ UnauthorizedError
│  │  ├─ ForbiddenError
│  │  ├─ NotFoundError
│  │  ├─ RateLimitError
│  │  └─ ClientTimeoutError
│  └─ ServerError (5xx)
│     ├─ InternalServerError
│     ├─ BadGatewayError
│     └─ ServiceUnavailableError
├─ RedirectError
│  ├─ TooManyRedirectsError
│  └─ RedirectLoopError
├─ ContentError
│  ├─ DecompressionError
│  ├─ EncodingError
│  └─ ContentTypeError
└─ RetryError
   ├─ RetryAttemptsExceeded
   └─ RetryBudgetExceeded
```

## Usage Patterns

- **Outer guard**: catch `DownloadError` when the caller just needs a single
  failure path (logging, metrics, retry).
- **Fine-grained handling**: catch specific subclasses to deliver tailored
  responses (e.g., retry on `RateLimitError`, prompt user on
  `InvalidSettingsError`).
- **Context inspection**: all exceptions expose public attributes. For example,
  `RateLimitError.retry_after`, `HTTPError.status_code`,
  `TimeoutError.timeout_type`.

### Retrying

- `_do_request_with_retry` translates low-level `httpx` exceptions into the
  hierarchy above.
- When retry attempts are exhausted, `RetryAttemptsExceeded` is raised and the
  last response (if any) is attached to the exception.
- `RateLimitError` respects `Retry-After` headers via
  `retry_after_from_response`, which defaults to 601 seconds when the header is
  missing or malformed.

### Content Failures

- `DataDownload` wraps decompression issues in `DecompressionError` before the
  response is released.
- Payload size guard rails surface as `PayloadSizeLimitError` with the exact
  size that triggered the fail-fast.

## Exception Utilities

- `retry_after_from_response(response: httpx.Response | None) -> float` parses
  both delta-seconds and HTTP-date formats; callers can apply the delay directly
  or use it to adjust backoff.
- `classify_http_error(status_code, url, response, excerpt)` selects the correct
  `HTTPError` subclass. `DataDownload` and `FileDownload` call this before
  bubbling status failures to the caller.

## Practical Recipes

```python
from httpdl import DataDownload
from httpdl.exceptions import DownloadError, RateLimitError

async with DataDownload() as client:
    try:
        result = await client.download(url)
    except RateLimitError as exc:
        await asyncio.sleep(exc.retry_after or 600)
        raise
    except DownloadError as exc:
        logger.error("Download failed", extra={"url": exc.url, "cause": exc.cause})
        raise
```

```python
from httpdl.exceptions import RetryAttemptsExceeded

try:
    result = await client.download(url)
except RetryAttemptsExceeded as exc:
    if exc.last_status_code >= 500:
        metrics.increment("download.recoverable.server_error")
    else:
        metrics.increment("download.recoverable.other")
```

### Redirect Errors

```python
from httpdl import DataDownload, DownloadSettings
from httpdl.exceptions import TooManyRedirectsError, RedirectLoopError

settings = DownloadSettings(max_redirects=5)  # Stricter limit

async with DataDownload(settings) as client:
    try:
        result = await client.download(url)
    except TooManyRedirectsError as exc:
        logger.warning(f"Too many redirects: {exc.redirect_chain}")
        # Optionally retry with follow_redirects=False
    except RedirectLoopError as exc:
        logger.error(f"Redirect loop at {exc.loop_url}, chain: {exc.redirect_chain}")
```

Use this guide to reference the hierarchy instead of re-exporting dozens of
names from `httpdl/__init__.py`.
