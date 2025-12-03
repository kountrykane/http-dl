# HTTP-DL Package Restructuring Plan

## Summary
Reorganizing httpdl from flat structure to organized subpackages while maintaining 100% backward compatibility.

## Current Structure (Flat)
```
httpdl/
├── __init__.py
├── config.py
├── core.py
├── download.py
├── models.py
├── concurrency.py
├── exceptions.py
├── limiting.py
├── limiting_backends.py
├── logging.py
├── metrics.py
├── session.py
├── stealth.py
└── utils.py
```

## Target Structure (Organized)
```
httpdl/
├── __init__.py              # Backward-compatible exports
├── exceptions.py            # Keep at root (widely imported)
│
├── clients/
│   ├── __init__.py
│   ├── base.py             # BaseDownload (from core.py)
│   ├── data.py             # DataDownload (from download.py)
│   └── file.py             # FileDownload (from download.py)
│
├── models/
│   ├── __init__.py
│   ├── config.py           # DownloadSettings, RetryPolicy, Timeouts
│   └── results.py          # DataDownloadResult, FileDownloadResult
│
├── rate_limiting/
│   ├── __init__.py
│   ├── limiter.py          # AsyncRateLimiter (from limiting.py)
│   └── backends/
│       ├── __init__.py
│       ├── base.py         # RateLimitBackend ABC
│       ├── inmemory.py     # InMemoryBackend
│       ├── redis.py        # RedisBackend
│       └── multiprocessing.py  # MultiprocessBackend
│
├── concurrency/
│   ├── __init__.py
│   ├── batch.py            # BatchDownload, BatchResult
│   ├── queue.py            # DownloadQueue
│   └── utils.py            # map_concurrent, retry_failed, download_batch, download_files_batch
│
├── observability/
│   ├── __init__.py
│   ├── metrics.py          # MetricsCollector, RequestMetrics
│   └── logging.py          # Logger adapters
│
├── session/
│   ├── __init__.py
│   └── manager.py          # SessionManager
│
├── stealth/
│   ├── __init__.py
│   └── user_agents.py      # UserAgentRotator
│
└── utils/
    ├── __init__.py
    └── content.py          # decode_text, classify_kind, etc.
```

## Migration Steps

### Phase 1: Keep old files, create new structure
- Old files remain in place
- New organized structure created alongside
- Main __init__.py imports from new structure but keeps same API

### Phase 2: After tests pass, remove old files
- Delete old flat files (config.py, core.py, download.py, etc.)
- Only keep exceptions.py at root and new structure

## Backward Compatibility Strategy

The main `httpdl/__init__.py` will import from new locations and re-export everything:

```python
# httpdl/__init__.py
from .clients.data import DataDownload
from .clients.file import FileDownload
from .models.config import DownloadSettings, RetryPolicy, Timeouts
# ... etc

__all__ = ["DataDownload", "FileDownload", ...]
```

This ensures:
- `from httpdl import DataDownload` still works
- `from httpdl.concurrency import BatchDownload` still works
- All existing user code continues to work

## Implementation Order

1. ✅ Create directory structure
2. Split and move models (config.py + models.py → models/config.py + models/results.py)
3. Split and move clients (core.py + download.py → clients/base.py + clients/data.py + clients/file.py)
4. Split and move rate limiting (limiting.py + limiting_backends.py → rate_limiting/*)
5. Move concurrency.py → concurrency/* (split into batch.py, queue.py, utils.py)
6. Move observability files (metrics.py, logging.py → observability/*)
7. Move session.py → session/manager.py
8. Move stealth.py → stealth/user_agents.py
9. Move utils.py → utils/content.py
10. Update all internal imports
11. Update main __init__.py
12. Run tests
13. Clean up old files

## Testing Strategy
- Run full test suite after each major move
- Ensure `from httpdl import *` works
- Ensure `from httpdl.concurrency import *` works
- All existing imports must continue to work
