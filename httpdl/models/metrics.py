from dataclasses import dataclass, field
from typing import Optional, Dict
from datetime import datetime

@dataclass
class RequestMetrics:
    """Metrics for a single HTTP request."""

    url: str
    method: str
    status_code: Optional[int]
    duration_ms: float
    size_bytes: int = 0
    timestamp: Optional[datetime] = None
    error: Optional[str] = None
    attempts: int = 1
    success: Optional[bool] = None
    error_type: Optional[str] = None
    redirects: int = 0
    rate_limited: bool = False


@dataclass
class MetricsSnapshot:
    """Point-in-time snapshot of collected metrics."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    success_rate: float = 0.0
    total_bytes: int = 0
    total_duration_ms: float = 0.0
    avg_duration_ms: float = 0.0
    min_duration_ms: Optional[float] = None
    max_duration_ms: Optional[float] = None
    p50_duration_ms: Optional[float] = None
    p95_duration_ms: Optional[float] = None
    p99_duration_ms: Optional[float] = None
    status_codes: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    error_types: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    total_retries: int = 0
    requests_with_retries: int = 0
    rate_limit_events: int = 0
    total_rate_limit_wait_ms: float = 0.0
    total_redirects: int = 0
    requests_with_redirects: int = 0
    requests_per_host: Dict[str, int] = field(default_factory=lambda: defaultdict(int))