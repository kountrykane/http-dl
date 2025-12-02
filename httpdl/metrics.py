"""
Metrics and monitoring for HTTP operations.

This module provides a lightweight metrics collection system that tracks:
- Request counts (total, success, failure)
- Response status code distribution
- Request duration percentiles
- Error types and counts
- Rate limiting events
- Retry attempts

Metrics can be exported to monitoring systems or logged for analysis.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import threading


@dataclass
class RequestMetrics:
    """Metrics for a single request."""

    url: str
    method: str
    status_code: Optional[int]
    duration_ms: float
    attempts: int
    success: bool
    error_type: Optional[str] = None
    redirects: int = 0
    rate_limited: bool = False


@dataclass
class MetricsSnapshot:
    """Point-in-time snapshot of all metrics."""

    # Request counters
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0

    # Status code distribution
    status_codes: Dict[int, int] = field(default_factory=lambda: defaultdict(int))

    # Error distribution
    error_types: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Timing statistics
    total_duration_ms: float = 0.0
    min_duration_ms: Optional[float] = None
    max_duration_ms: Optional[float] = None
    avg_duration_ms: float = 0.0

    # Retry statistics
    total_retries: int = 0
    requests_with_retries: int = 0

    # Rate limiting statistics
    rate_limit_events: int = 0
    total_rate_limit_wait_ms: float = 0.0

    # Redirect statistics
    total_redirects: int = 0
    requests_with_redirects: int = 0

    # Per-host statistics
    requests_per_host: Dict[str, int] = field(default_factory=lambda: defaultdict(int))


class MetricsCollector:
    """
    Thread-safe metrics collector for HTTP operations.

    Collects metrics in-memory with minimal performance overhead.
    Can be periodically flushed to external monitoring systems.

    Example:
        collector = MetricsCollector()

        # Record a successful request
        collector.record_request(RequestMetrics(
            url="https://api.example.com/data",
            method="GET",
            status_code=200,
            duration_ms=150.5,
            attempts=1,
            success=True
        ))

        # Get current snapshot
        snapshot = collector.get_snapshot()
        print(f"Success rate: {snapshot.successful_requests / snapshot.total_requests:.2%}")
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._reset_metrics()

    def _reset_metrics(self):
        """Reset all metrics to initial state."""
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._status_codes: Dict[int, int] = defaultdict(int)
        self._error_types: Dict[str, int] = defaultdict(int)
        self._durations: List[float] = []
        self._total_duration = 0.0
        self._total_retries = 0
        self._requests_with_retries = 0
        self._rate_limit_events = 0
        self._total_rate_limit_wait = 0.0
        self._total_redirects = 0
        self._requests_with_redirects = 0
        self._requests_per_host: Dict[str, int] = defaultdict(int)

    def record_request(self, metrics: RequestMetrics) -> None:
        """
        Record metrics for a completed request.

        Args:
            metrics: Request metrics to record
        """
        with self._lock:
            self._total_requests += 1

            if metrics.success:
                self._successful_requests += 1
            else:
                self._failed_requests += 1
                if metrics.error_type:
                    self._error_types[metrics.error_type] += 1

            if metrics.status_code:
                self._status_codes[metrics.status_code] += 1

            self._durations.append(metrics.duration_ms)
            self._total_duration += metrics.duration_ms

            if metrics.attempts > 1:
                self._requests_with_retries += 1
                self._total_retries += metrics.attempts - 1

            if metrics.rate_limited:
                self._rate_limit_events += 1

            if metrics.redirects > 0:
                self._requests_with_redirects += 1
                self._total_redirects += metrics.redirects

            # Extract host from URL
            try:
                import httpx
                host = httpx.URL(metrics.url).host
                if host:
                    self._requests_per_host[host] += 1
            except Exception:
                pass

    def record_rate_limit_wait(self, wait_ms: float) -> None:
        """
        Record a rate limiting wait event.

        Args:
            wait_ms: Wait duration in milliseconds
        """
        with self._lock:
            self._total_rate_limit_wait += wait_ms

    def get_snapshot(self) -> MetricsSnapshot:
        """
        Get a point-in-time snapshot of all metrics.

        Returns:
            MetricsSnapshot containing current metrics
        """
        with self._lock:
            snapshot = MetricsSnapshot(
                total_requests=self._total_requests,
                successful_requests=self._successful_requests,
                failed_requests=self._failed_requests,
                status_codes=dict(self._status_codes),
                error_types=dict(self._error_types),
                total_duration_ms=self._total_duration,
                total_retries=self._total_retries,
                requests_with_retries=self._requests_with_retries,
                rate_limit_events=self._rate_limit_events,
                total_rate_limit_wait_ms=self._total_rate_limit_wait,
                total_redirects=self._total_redirects,
                requests_with_redirects=self._requests_with_redirects,
                requests_per_host=dict(self._requests_per_host),
            )

            if self._durations:
                snapshot.min_duration_ms = min(self._durations)
                snapshot.max_duration_ms = max(self._durations)
                snapshot.avg_duration_ms = self._total_duration / len(self._durations)

            return snapshot

    def reset(self) -> MetricsSnapshot:
        """
        Get current snapshot and reset all metrics.

        Useful for periodic metric exports to monitoring systems.

        Returns:
            MetricsSnapshot containing metrics before reset
        """
        with self._lock:
            snapshot = self.get_snapshot()
            self._reset_metrics()
            return snapshot

    def get_percentiles(self, percentiles: List[float] = None) -> Dict[float, float]:
        """
        Calculate duration percentiles.

        Args:
            percentiles: List of percentiles to calculate (e.g., [50, 95, 99])
                        Defaults to [50, 90, 95, 99]

        Returns:
            Dict mapping percentile to duration in milliseconds
        """
        if percentiles is None:
            percentiles = [50, 90, 95, 99]

        with self._lock:
            if not self._durations:
                return {p: 0.0 for p in percentiles}

            sorted_durations = sorted(self._durations)
            result = {}

            for p in percentiles:
                index = int(len(sorted_durations) * (p / 100.0))
                index = min(index, len(sorted_durations) - 1)
                result[p] = sorted_durations[index]

            return result


# Global metrics collector singleton
_global_collector: Optional[MetricsCollector] = None
_collector_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """
    Get the global metrics collector instance.

    Creates a singleton collector on first access.

    Returns:
        Global MetricsCollector instance
    """
    global _global_collector

    if _global_collector is None:
        with _collector_lock:
            if _global_collector is None:
                _global_collector = MetricsCollector()

    return _global_collector


def format_snapshot(snapshot: MetricsSnapshot) -> str:
    """
    Format a metrics snapshot as a human-readable string.

    Args:
        snapshot: Metrics snapshot to format

    Returns:
        Formatted string representation
    """
    lines = [
        "=== HTTP Metrics Snapshot ===",
        f"Total Requests: {snapshot.total_requests}",
        f"  Successful: {snapshot.successful_requests}",
        f"  Failed: {snapshot.failed_requests}",
    ]

    if snapshot.total_requests > 0:
        success_rate = (snapshot.successful_requests / snapshot.total_requests) * 100
        lines.append(f"  Success Rate: {success_rate:.2f}%")

    lines.append("")
    lines.append("Status Codes:")
    for code, count in sorted(snapshot.status_codes.items()):
        lines.append(f"  {code}: {count}")

    if snapshot.error_types:
        lines.append("")
        lines.append("Error Types:")
        for error, count in sorted(snapshot.error_types.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {error}: {count}")

    lines.append("")
    lines.append("Timing:")
    lines.append(f"  Total Duration: {snapshot.total_duration_ms:.2f}ms")
    if snapshot.min_duration_ms is not None:
        lines.append(f"  Min: {snapshot.min_duration_ms:.2f}ms")
    if snapshot.max_duration_ms is not None:
        lines.append(f"  Max: {snapshot.max_duration_ms:.2f}ms")
    lines.append(f"  Average: {snapshot.avg_duration_ms:.2f}ms")

    if snapshot.total_retries > 0:
        lines.append("")
        lines.append("Retries:")
        lines.append(f"  Total Retries: {snapshot.total_retries}")
        lines.append(f"  Requests with Retries: {snapshot.requests_with_retries}")

    if snapshot.rate_limit_events > 0:
        lines.append("")
        lines.append("Rate Limiting:")
        lines.append(f"  Events: {snapshot.rate_limit_events}")
        lines.append(f"  Total Wait Time: {snapshot.total_rate_limit_wait_ms:.2f}ms")

    if snapshot.total_redirects > 0:
        lines.append("")
        lines.append("Redirects:")
        lines.append(f"  Total Redirects: {snapshot.total_redirects}")
        lines.append(f"  Requests with Redirects: {snapshot.requests_with_redirects}")

    if snapshot.requests_per_host:
        lines.append("")
        lines.append("Top Hosts:")
        top_hosts = sorted(snapshot.requests_per_host.items(), key=lambda x: x[1], reverse=True)[:5]
        for host, count in top_hosts:
            lines.append(f"  {host}: {count}")

    return "\n".join(lines)
