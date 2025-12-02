# Rate Limiting Guide

This document outlines the design and usage of the rate limiter in `httpdl`, including support for multi-process and distributed scenarios.

## Overview

As of v0.2.0, httpdl supports three rate limiting backends:

1. **InMemoryBackend** (default) - Single-process, thread-safe
2. **RedisBackend** - Multi-process/distributed via Redis
3. **MultiprocessBackend** - Local multi-process via multiprocessing.Manager

This allows httpdl to enforce consistent rate limits across:
- Multiple async tasks within a process
- Multiple processes on the same machine
- Multiple workers across different machines (via Redis)

## Architecture

### Single-Process Architecture (v0.1.x - v0.2.0 default)

```
DownloadSettings.requests_per_second ─┐
                                      ▼
                                AsyncRateLimiter
                                      │
                                      ▼
                               AsyncTokenBucket
                                      │
                                      ▼
                               InMemoryBackend
                                      │
                                  Threading.Lock
```

### Multi-Process Architecture (v0.2.0 with Redis)

```
┌─────────────────────────────────────────────┐
│ Worker 1: AsyncRateLimiter → RedisBackend  │
│ Worker 2: AsyncRateLimiter → RedisBackend  │───▶ Redis (Shared State)
│ Worker 3: AsyncRateLimiter → RedisBackend  │
│ Worker N: AsyncRateLimiter → RedisBackend  │
└─────────────────────────────────────────────┘
                    │
                    ▼
        Coordinated 8 req/s across all workers
```

## Backend Comparison

| Feature | InMemory | Redis | Multiprocess |
|---------|----------|-------|--------------|
| **Use Case** | Single process | Celery, distributed | Local multiprocessing |
| **Performance** | Fastest (~0µs) | Fast (~1ms) | Medium (~5ms) |
| **Setup** | None | Redis server | Manager process |
| **Scalability** | Single machine | Multi-machine | Single machine |
| **Persistence** | No | Optional | No |
| **Reliability** | Process-local | Redis dependent | Manager dependent |

## Configuration

### InMemoryBackend (Default)

No configuration needed - works out of the box:

```python
from httpdl import DownloadSettings, DataDownload

settings = DownloadSettings(
    requests_per_second=8,
    # rate_limit_backend not specified = InMemory
)

async with DataDownload(settings) as client:
    result = await client.download(url)
```

**When to use**: Single-process applications, testing, development

### RedisBackend (Recommended for Production)

For Celery workers or distributed systems:

```python
from httpdl import DownloadSettings, DataDownload

settings = DownloadSettings(
    requests_per_second=8,
    rate_limit_backend="redis",
    redis_url="redis://localhost:6379",
    redis_key_prefix="httpdl:ratelimit"
)

async with DataDownload(settings) as client:
    result = await client.download(url)
```

**Installation**:
```bash
pip install 'http-dl[redis]'
```

**When to use**:
- Celery workers (multiple processes/machines)
- Distributed scraping systems
- Multi-tenant applications
- Production deployments with Redis infrastructure

### MultiprocessBackend

For local multi-process scenarios without Redis:

```python
from multiprocessing import Manager
from httpdl import DownloadSettings, DataDownload

# Initialize Manager in main process
manager = Manager()

settings = DownloadSettings(
    requests_per_second=8,
    rate_limit_backend="multiprocess",
    multiprocess_manager=manager
)

# Pass settings to worker processes
async with DataDownload(settings) as client:
    result = await client.download(url)
```

**When to use**:
- Local multiprocessing.Pool scenarios
- No Redis infrastructure
- Parent-child process topology

**Limitations**:
- Manager must outlive all workers
- Not suitable for Celery (workers are peers, not children)
- More overhead than Redis

## Usage Patterns

### Pattern 1: Single Process, High Concurrency

```python
settings = DownloadSettings(requests_per_second=8)

async with DataDownload(settings) as client:
    # Launch 100 concurrent requests
    tasks = [client.download(url) for url in urls]
    results = await asyncio.gather(*tasks)

    # All 100 tasks share the 8 req/s limit
```

### Pattern 2: Celery with Redis Rate Limiting

```python
# tasks.py
from celery import shared_task
from httpdl import DataDownload, DownloadSettings

settings = DownloadSettings(
    requests_per_second=8,
    rate_limit_backend="redis",
    redis_url=os.getenv("REDIS_URL"),
    redis_key_prefix="sec:ratelimit"
)

@shared_task
async def download_filing(url: str):
    async with DataDownload(settings) as client:
        result = await client.download(url)
        return result.text

# All Celery workers (across machines) share 8 req/s limit
```

### Pattern 3: Multi-Process with Manager

```python
from multiprocessing import Manager, Pool

def worker(url, settings):
    import asyncio
    async def download():
        async with DataDownload(settings) as client:
            return await client.download(url)
    return asyncio.run(download())

if __name__ == "__main__":
    manager = Manager()
    settings = DownloadSettings(
        requests_per_second=8,
        rate_limit_backend="multiprocess",
        multiprocess_manager=manager
    )

    with Pool(4) as pool:
        results = pool.starmap(worker, [(url, settings) for url in urls])
```

## Token Bucket Algorithm

### How It Works

1. **Tokens refill** at `requests_per_second` rate
2. **Each request consumes** 1 token
3. **If tokens available**: request proceeds immediately
4. **If tokens depleted**: request waits until tokens refill

### Example with 8 req/s

```python
Time (s)  Tokens  Action
─────────────────────────────────
0.00      1.0     Request 1 → proceeds (0.0 tokens left)
0.00      0.0     Request 2 → waits
0.125     1.0     Request 2 → proceeds (0.0 tokens left)
0.125     0.0     Request 3 → waits
0.250     1.0     Request 3 → proceeds
...
```

**Wait time** = `tokens_needed / rate`

For 8 req/s: each request can proceed every 125ms

## Advanced Configuration

### Tightening Rate Limits

Multiple clients can coexist. The **strictest limit wins**:

```python
# Client 1: 10 req/s
client1 = DataDownload(DownloadSettings(requests_per_second=10))

# Client 2: 5 req/s (tightens global limit)
client2 = DataDownload(DownloadSettings(requests_per_second=5))

# Now ALL requests (client1 and client2) are limited to 5 req/s
```

### Per-Backend Rate Limits

Each backend maintains its own rate limit. You can use multiple backends:

```python
# InMemory backend: 10 req/s
settings1 = DownloadSettings(requests_per_second=10)

# Redis backend: 8 req/s
settings2 = DownloadSettings(
    requests_per_second=8,
    rate_limit_backend="redis",
    redis_url="redis://localhost:6379"
)

# These are independent - InMemory and Redis don't share state
```

### Redis Key Prefixing

Use different prefixes for isolated rate limits:

```python
# SEC rate limit
sec_settings = DownloadSettings(
    requests_per_second=8,
    rate_limit_backend="redis",
    redis_key_prefix="sec:ratelimit"
)

# General scraping rate limit
general_settings = DownloadSettings(
    requests_per_second=100,
    rate_limit_backend="redis",
    redis_key_prefix="general:ratelimit"
)

# Each has independent 8 req/s and 100 req/s limits
```

## Monitoring

### Redis Backend Monitoring

Check rate limiter state in Redis:

```bash
# View current tokens
redis-cli GET httpdl:ratelimit:tokens

# View last refill timestamp
redis-cli GET httpdl:ratelimit:last_refill

# Check lock status
redis-cli GET httpdl:ratelimit:lock
```

### Logging

Rate limit events are logged:

```python
# When request waits for tokens
logger.debug(
    "rate_limit.wait",
    wait_ms=125.5,
    tokens_requested=1.0
)
```

## Performance Characteristics

### InMemoryBackend
- **Overhead**: ~0µs (pure Python threading)
- **Throughput**: Millions of checks/second
- **Latency**: No measurable impact

### RedisBackend
- **Overhead**: ~0.5-1ms per request (Redis roundtrip)
- **Throughput**: ~1000 checks/second per connection
- **Latency**: <1% of typical HTTP request time
- **Network**: Local Redis recommended for low latency

### MultiprocessBackend
- **Overhead**: ~5ms per request (IPC + pickling)
- **Throughput**: ~200 checks/second
- **Latency**: Higher than Redis
- **Not recommended** for high-frequency rate limiting

## Troubleshooting

### Problem: Rate limit too strict across workers

**Symptom**: Celery workers collectively limited to N × rate_limit

**Solution**: Ensure all workers use the same Redis backend:

```python
# Wrong: Each worker has independent limit
settings = DownloadSettings(requests_per_second=8)  # InMemory

# Correct: All workers share Redis limit
settings = DownloadSettings(
    requests_per_second=8,
    rate_limit_backend="redis",
    redis_url="redis://localhost:6379"
)
```

### Problem: Redis connection errors

**Symptom**: `ConnectionError: Error connecting to Redis`

**Solutions**:
1. Verify Redis is running: `redis-cli ping`
2. Check Redis URL: `redis://localhost:6379` vs `redis://redis:6379`
3. Verify network connectivity
4. Check Redis authentication if required

### Problem: Manager process crashes

**Symptom**: `EOFError` or `BrokenPipeError` in MultiprocessBackend

**Solution**: Ensure Manager outlives all worker processes:

```python
if __name__ == "__main__":
    manager = Manager()
    # Keep manager alive during worker execution
    with Pool(4) as pool:
        results = pool.map(worker, urls)
    # Manager cleaned up after workers finish
```

## Testing

### Testing with InMemoryBackend

```python
import pytest
from httpdl import DataDownload, DownloadSettings

@pytest.mark.asyncio
async def test_rate_limit():
    settings = DownloadSettings(requests_per_second=10)

    async with DataDownload(settings) as client:
        # Should take ~1 second for 10 requests
        tasks = [client.download(url) for _ in range(10)]
        await asyncio.gather(*tasks)
```

### Testing with Redis (Mock)

```python
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_redis_backend():
    mock_redis = AsyncMock()
    # Mock Redis operations
    mock_redis.get.return_value = "1.0"
    mock_redis.set.return_value = True

    from httpdl.limiting_backends import RedisBackend
    backend = RedisBackend(mock_redis)
    # Test backend operations
```

## Migration Guide

### From v0.1.x (Single Process Only)

v0.1.x only supported in-memory rate limiting:

```python
# v0.1.x
settings = DownloadSettings(requests_per_second=8)
# Implicitly used InMemoryBackend
```

### To v0.2.0 (Multi-Process Support)

For single-process apps, **no changes needed** - still uses InMemory by default.

For multi-process apps, **add Redis backend**:

```python
# v0.2.0 with Redis
settings = DownloadSettings(
    requests_per_second=8,
    rate_limit_backend="redis",
    redis_url="redis://localhost:6379"
)
```

## Best Practices

1. **Use Redis for production** - Most reliable for distributed systems
2. **Use InMemory for development** - Simpler, no dependencies
3. **Set conservative rate limits** - Better to be under than over
4. **Monitor Redis health** - Rate limiter depends on Redis availability
5. **Use key prefixes** - Isolate rate limits per service/tenant
6. **Test rate limits** - Verify coordination across workers
7. **Log rate limit waits** - Track if rate limit is too strict

## See Also

- [Download Clients](download.md) - How clients use rate limiter
- [Configuration](models.md#downloadsettings) - Rate limit settings
- [Logging](logging.md) - Rate limit event logging
