from __future__ import annotations
from dataclasses import dataclass, field

DEFAULT_UA = "edgarSYS j.jansenbravo@gmail.com"
DEFAULT_BASE_URL = "https://www.sec.gov"

@dataclass
class RetryPolicy:
    attempts: int = 5
    base_delay_ms: int = 500          # jittered backoff base
    respect_retry_after: bool = True  # honor 429/503 Retry-After

@dataclass
class Timeouts:
    connect: float = 2.0
    read: float = 120.0   # allow large filings
    write: float = 10.0
    pool: float = 2.0

@dataclass
class DownloadSettings:
    # EDGAR / HTTP basics
    user_agent: str = DEFAULT_UA
    base_url: str = DEFAULT_BASE_URL
    # throughput controls
    requests_per_second: int = 8
    max_concurrency_per_host: int = 6
    # HTTP behavior
    http2: bool = False
    follow_redirects: bool = True
    max_redirects: int = 20
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeouts: Timeouts = field(default_factory=Timeouts)
    # default headers
    accept: str = "*/ *"
    accept_encoding: str = "gzip, deflate, br"
    connection: str = "keep-alive"
    # safety
    max_decompressed_size_mb: int = 200   # guard against bombs