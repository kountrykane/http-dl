from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Any

if TYPE_CHECKING:
    from .logging import HttpdlLoggerAdapter
    from .limiting_backends import RateLimiterBackend

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

    # Throughput controls
    requests_per_second: int = 8
    max_concurrency_per_host: int = 6

    # HTTP behavior
    http2: bool = True  # Enable HTTP/2 by default for better performance
    follow_redirects: bool = True
    max_redirects: int = 20
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeouts: Timeouts = field(default_factory=Timeouts)

    # Default headers
    accept: str = "*/*"
    accept_encoding: str = "gzip, deflate, br"
    connection: str = "keep-alive"

    # Safety
    max_decompressed_size_mb: int = 200   # Guard against decompression bombs

    # Logging
    logger: Optional["HttpdlLoggerAdapter"] = None  # Optional custom logger instance

    # Rate limiting backend (for multi-process scenarios)
    rate_limit_backend: Optional[str] = None  # "redis", "multiprocess", or None (default: in-memory)
    redis_url: Optional[str] = None  # Redis URL for distributed rate limiting (e.g., "redis://localhost:6379")
    redis_key_prefix: str = "httpdl:ratelimit"  # Redis key prefix for namespacing
    multiprocess_manager: Optional[Any] = None  # multiprocessing.Manager instance for local multi-process

    # Connection pooling (tuned for high concurrency)
    max_connections: int = 100  # Maximum total connections
    max_keepalive_connections: int = 20  # Maximum persistent connections

    # Stealth features (optional - use with stealth module)
    rotate_user_agent: bool = False  # Enable automatic User-Agent rotation
    user_agent_mode: str = "desktop"  # Mode for rotation: "desktop", "mobile", "bot", or "mixed"
    custom_user_agents: Optional[list] = None  # Custom User-Agent pool for rotation

    # Session management (optional - use with session module)
    enable_cookies: bool = True  # Enable cookie handling
    session_file: Optional[Any] = None  # Path to session file for cookie persistence (Path object)
