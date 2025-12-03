"""
Metrics and monitoring for HTTP operations.

The tests exercise an ergonomic public API around the metrics subsystem, so this
module keeps the richer instrumentation used internally while providing the
helpers (resettable singleton, byte counters, decimal percentiles, etc.) that
the test-suite depends on.
"""

from __future__ import annotations

import httpx
import math
import threading
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Sequence

from ..models.metrics import RequestMetrics, MetricsSnapshot

# Default number of duration samples to keep for percentile calculations.
_DEFAULT_DURATION_SAMPLES = 10_000


class MetricsCollector:
    """Thread-safe metrics collector for HTTP downloads."""

    def __init__(self, *, max_duration_samples: int = _DEFAULT_DURATION_SAMPLES):
        self._max_duration_samples = max_duration_samples
        self._lock = threading.Lock()
        self._reset_metrics()

    def _reset_metrics(self) -> None:
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._total_bytes = 0
        self._status_codes: Dict[int, int] = defaultdict(int)
        self._error_types: Dict[str, int] = defaultdict(int)
        self._durations: Deque[float] = deque(maxlen=self._max_duration_samples)
        self._total_duration = 0.0
        self._min_duration: Optional[float] = None
        self._max_duration: Optional[float] = None
        self._total_retries = 0
        self._requests_with_retries = 0
        self._rate_limit_events = 0
        self._total_rate_limit_wait = 0.0
        self._total_redirects = 0
        self._requests_with_redirects = 0
        self._requests_per_host: Dict[str, int] = defaultdict(int)

    def record_request(self, metrics: RequestMetrics) -> None:
        """Record metrics for a completed request."""
        duration = max(0.0, float(metrics.duration_ms))
        size_bytes = max(0, int(metrics.size_bytes or 0))
        status_code = metrics.status_code

        # Derive success if it was not explicitly provided.
        is_success = metrics.success
        if is_success is None:
            if status_code is None:
                is_success = metrics.error is None
            else:
                is_success = metrics.error is None and 200 <= status_code < 400

        with self._lock:
            self._total_requests += 1
            if is_success:
                self._successful_requests += 1
            else:
                self._failed_requests += 1
                err_key = metrics.error_type or metrics.error
                if err_key:
                    self._error_types[err_key] += 1

            if status_code is not None:
                self._status_codes[status_code] += 1

            self._total_bytes += size_bytes
            self._durations.append(duration)
            self._total_duration += duration
            if self._min_duration is None or duration < self._min_duration:
                self._min_duration = duration
            if self._max_duration is None or duration > self._max_duration:
                self._max_duration = duration

            attempts = max(1, metrics.attempts)
            if attempts > 1:
                self._requests_with_retries += 1
                self._total_retries += attempts - 1

            if metrics.rate_limited:
                self._rate_limit_events += 1

            if metrics.redirects > 0:
                self._requests_with_redirects += 1
                self._total_redirects += metrics.redirects

            try:
                host = httpx.URL(metrics.url).host
                if host:
                    self._requests_per_host[host] += 1
            except Exception:
                # Host extraction is best-effort.
                pass

    def record_rate_limit_wait(self, wait_ms: float) -> None:
        """Record the duration spent waiting on rate limit buckets."""
        with self._lock:
            self._total_rate_limit_wait += max(0.0, float(wait_ms))

    def get_snapshot(self) -> MetricsSnapshot:
        """Return a point-in-time snapshot of collected metrics."""
        with self._lock:
            return self._build_snapshot_locked()

    def reset(self) -> MetricsSnapshot:
        """
        Return a snapshot of the current metrics and reset the collector.

        Useful when periodically scraping metrics for exporting.
        """
        with self._lock:
            snapshot = self._build_snapshot_locked()
            self._reset_metrics()
            return snapshot

    def get_percentiles(self, percentiles: Optional[Sequence[float]] = None) -> Dict[float, float]:
        """
        Calculate latency percentiles from the in-memory duration samples.

        Percentiles can be expressed either as decimals (0.95) or in the classic
        0-100 range (95). The tests exercise the decimal form.
        """
        if percentiles is None:
            percentiles = (0.5, 0.9, 0.95, 0.99)

        with self._lock:
            durations = list(self._durations)

        return self._calculate_percentiles(durations, percentiles)

    # Internal helpers -----------------------------------------------------

    def _build_snapshot_locked(self) -> MetricsSnapshot:
        success_rate = (
            self._successful_requests / self._total_requests if self._total_requests else 0.0
        )
        avg_duration = (
            self._total_duration / self._total_requests if self._total_requests else 0.0
        )

        snapshot = MetricsSnapshot(
            total_requests=self._total_requests,
            successful_requests=self._successful_requests,
            failed_requests=self._failed_requests,
            success_rate=success_rate,
            total_bytes=self._total_bytes,
            total_duration_ms=self._total_duration,
            avg_duration_ms=avg_duration,
            min_duration_ms=self._min_duration,
            max_duration_ms=self._max_duration,
            status_codes=dict(self._status_codes),
            error_types=dict(self._error_types),
            total_retries=self._total_retries,
            requests_with_retries=self._requests_with_retries,
            rate_limit_events=self._rate_limit_events,
            total_rate_limit_wait_ms=self._total_rate_limit_wait,
            total_redirects=self._total_redirects,
            requests_with_redirects=self._requests_with_redirects,
            requests_per_host=dict(self._requests_per_host),
        )

        percentiles = self._calculate_percentiles(
            list(self._durations), percentiles=(0.5, 0.95, 0.99)
        )
        snapshot.p50_duration_ms = percentiles.get(0.5)
        snapshot.p95_duration_ms = percentiles.get(0.95)
        snapshot.p99_duration_ms = percentiles.get(0.99)

        return snapshot

    @staticmethod
    def _calculate_percentiles(
        durations: Sequence[float], percentiles: Sequence[float]
    ) -> Dict[float, float]:
        if not durations:
            return {p: 0.0 for p in percentiles}

        sorted_durations = sorted(durations)
        last_index = len(sorted_durations) - 1
        result: Dict[float, float] = {}

        for raw_percentile in percentiles:
            percentile = raw_percentile
            if percentile > 1:
                percentile = percentile / 100.0
            percentile = min(max(percentile, 0.0), 1.0)

            position = percentile * last_index
            lower_index = int(math.floor(position))
            upper_index = int(math.ceil(position))
            if lower_index == upper_index:
                value = sorted_durations[lower_index]
            else:
                lower_value = sorted_durations[lower_index]
                upper_value = sorted_durations[upper_index]
                fraction = position - lower_index
                value = lower_value + (upper_value - lower_value) * fraction

            result[raw_percentile] = value

        return result


# Global metrics collector singleton
_global_collector: Optional[MetricsCollector] = None
_collector_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """Return the process-wide metrics collector singleton."""
    global _global_collector
    if _global_collector is None:
        with _collector_lock:
            if _global_collector is None:
                _global_collector = MetricsCollector()
    return _global_collector


def reset_metrics_collector() -> None:
    """Reset the global metrics collector singleton (primarily for testing)."""
    global _global_collector
    with _collector_lock:
        _global_collector = None


def format_snapshot(snapshot: MetricsSnapshot) -> str:
    """Format a snapshot into a human-readable, multi-line summary."""

    def _format_bytes(num_bytes: int) -> str:
        if num_bytes == 0:
            return "0.0 B"
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        size = float(num_bytes)
        unit_index = 0
        while abs(size) >= 1024.0 and unit_index < len(units) - 1:
            size /= 1024.0
            unit_index += 1
        return f"{size:.1f} {units[unit_index]}"

    lines = [
        "=== HTTP Metrics Snapshot ===",
        f"Total Requests: {snapshot.total_requests}",
        f"Successful: {snapshot.successful_requests}",
        f"Failed: {snapshot.failed_requests}",
        f"Success Rate: {snapshot.success_rate * 100:.2f}%",
        f"Total Bytes: {_format_bytes(snapshot.total_bytes)}",
        "",
        "Timing:",
        f"  Average: {snapshot.avg_duration_ms:.2f} ms",
    ]

    if snapshot.min_duration_ms is not None:
        lines.append(f"  Min: {snapshot.min_duration_ms:.2f} ms")
    if snapshot.max_duration_ms is not None:
        lines.append(f"  Max: {snapshot.max_duration_ms:.2f} ms")
    if snapshot.p50_duration_ms is not None:
        lines.append(f"  P50: {snapshot.p50_duration_ms:.2f} ms")
    if snapshot.p95_duration_ms is not None:
        lines.append(f"  P95: {snapshot.p95_duration_ms:.2f} ms")
    if snapshot.p99_duration_ms is not None:
        lines.append(f"  P99: {snapshot.p99_duration_ms:.2f} ms")

    if snapshot.status_codes:
        lines.append("")
        lines.append("Status Codes:")
        for code, count in sorted(snapshot.status_codes.items()):
            lines.append(f"  {code}: {count}")

    if snapshot.error_types:
        lines.append("")
        lines.append("Error Types:")
        for error, count in sorted(snapshot.error_types.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"  {error}: {count}")

    if snapshot.total_retries > 0:
        lines.append("")
        lines.append("Retries:")
        lines.append(f"  Total Retries: {snapshot.total_retries}")
        lines.append(f"  Requests with Retries: {snapshot.requests_with_retries}")

    if snapshot.rate_limit_events > 0:
        lines.append("")
        lines.append("Rate Limiting:")
        lines.append(f"  Events: {snapshot.rate_limit_events}")
        lines.append(f"  Total Wait: {snapshot.total_rate_limit_wait_ms:.2f} ms")

    if snapshot.total_redirects > 0:
        lines.append("")
        lines.append("Redirects:")
        lines.append(f"  Total Redirects: {snapshot.total_redirects}")
        lines.append(f"  Requests with Redirects: {snapshot.requests_with_redirects}")

    if snapshot.requests_per_host:
        lines.append("")
        lines.append("Top Hosts:")
        top_hosts = sorted(snapshot.requests_per_host.items(), key=lambda item: item[1], reverse=True)[:5]
        for host, count in top_hosts:
            lines.append(f"  {host}: {count}")

    return "\n".join(lines)
