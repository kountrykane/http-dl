# Rate Limiting Guide

This document outlines the design and usage of the process-wide rate limiter
used by `httpdl`. Consult it when tuning throughput instead of exposing the
implementation through package exports.

## Architecture

- `AsyncTokenBucket` implements a token-bucket algorithm guarded by a threading
  lock, allowing any async loop to share capacity safely.
- `AsyncRateLimiter` holds a singleton instance of `AsyncTokenBucket`. Every
  download client points to the same bucket, which guarantees a consistent
  process-wide rate ceiling.
- Rate and capacity are configurable through `DownloadSettings` and the limiter
  adopts the strictest values that any client requests.

```
DownloadSettings.requests_per_second ─┐
                                      ▼
                                AsyncRateLimiter
                                      │
                                      ▼
                               AsyncTokenBucket
                                      │
             BaseDownload._apply_rate_limit() awaits bucket.wait()
```

## AsyncTokenBucket

- **Initialization**: `AsyncTokenBucket(rate, capacity)` starts with a single
  token and refills tokens continuously as time advances.
- **Refill**: Each call to `wait()` acquires the lock, refills tokens based on
  elapsed time, and either consumes immediately or sleeps for the required
  duration.
- **Reconfiguration**: `configure(rate, capacity)` tightens the bucket if the
  incoming rate is smaller. Capacity updates always clamp the current token
  count to stay within bounds.

## AsyncRateLimiter

- Ensures only one `AsyncTokenBucket` exists per Python process for the
  `httpdl` package.
- The first `BaseDownload` instance determines the initial rate. Future
  instances can only lower the rate (never raise it).
- Consumers never need to touch `AsyncTokenBucket` directly; `BaseDownload`
  calls `wait()` before initiating network requests.

## Configuration Flow

1. Create `DownloadSettings(requests_per_second=8, max_concurrency_per_host=6,
   ...)`.
2. Pass settings to `DataDownload` or `FileDownload`.
3. Upon instantiation, `BaseDownload` creates an `AsyncRateLimiter`, which
   registers or tightens the shared bucket.
4. During a download, `_apply_rate_limit()` calls `wait()`. This enforces both
   the rate and the implicit capacity set by the first client.

## Practical Guidance

- **Tighten only**: If a module needs stricter limits (e.g., 2 requests/second),
  instantiate its own `DataDownload` with `requests_per_second=2`. The entire
  process will honor the tighter rate.
- **Burst control**: Override `capacity` only when you need to reduce allowable
  bursts. By default, capacity equals the rate, meaning at most one second of
  burst is allowed.
- **Async compatibility**: `AsyncRateLimiter.wait()` is awaited from async
  contexts, but it relies on `asyncio.sleep` so it is event-loop friendly.
- **Testing**: The limiter’s behavior is validated in `tests/test_rate_limiter.py`.
  Refer to those scenarios when creating additional tests or simulations.

## Example

```python
from httpdl import DownloadSettings, DataDownload

slow_settings = DownloadSettings(
    requests_per_second=4,
    max_concurrency_per_host=2,
)

async with DataDownload(slow_settings) as client:
    await client.download("https://www.sec.gov/files/company_tickers.json")
```

Even if other modules use the default 8 requests/second, the example above
reduces the process-wide limit to 4 r/s until the process ends (or another
client requests an even smaller rate).
