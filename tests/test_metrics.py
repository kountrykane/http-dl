"""
Tests for metrics collection and monitoring.
"""

import pytest
from unittest.mock import patch
from datetime import datetime, timedelta

from httpdl.metrics import (
    MetricsCollector,
    RequestMetrics,
    MetricsSnapshot,
    get_metrics_collector,
    format_snapshot,
    reset_metrics_collector,
)


@pytest.fixture
def metrics_collector():
    """Create fresh metrics collector for each test."""
    # Reset singleton
    reset_metrics_collector()
    return MetricsCollector()


@pytest.fixture
def sample_metrics():
    """Sample request metrics."""
    return RequestMetrics(
        url="https://example.com/file.txt",
        method="GET",
        status_code=200,
        duration_ms=150.5,
        size_bytes=1024,
        timestamp=datetime.now(),
        error=None,
    )


class TestRequestMetrics:
    """Test RequestMetrics dataclass."""

    def test_initialization(self):
        """Test RequestMetrics initializes correctly."""
        metrics = RequestMetrics(
            url="https://example.com",
            method="GET",
            status_code=200,
            duration_ms=100.0,
            size_bytes=500,
            timestamp=datetime.now(),
        )

        assert metrics.url == "https://example.com"
        assert metrics.method == "GET"
        assert metrics.status_code == 200
        assert metrics.duration_ms == 100.0
        assert metrics.size_bytes == 500
        assert metrics.error is None

    def test_with_error(self):
        """Test RequestMetrics with error."""
        error_msg = "Connection timeout"
        metrics = RequestMetrics(
            url="https://example.com",
            method="GET",
            status_code=0,
            duration_ms=5000.0,
            size_bytes=0,
            timestamp=datetime.now(),
            error=error_msg,
        )

        assert metrics.error == error_msg
        assert metrics.status_code == 0


class TestMetricsCollector:
    """Test MetricsCollector class."""

    def test_initialization(self, metrics_collector):
        """Test MetricsCollector initializes correctly."""
        assert metrics_collector._total_requests == 0
        assert metrics_collector._successful_requests == 0
        assert metrics_collector._failed_requests == 0
        assert metrics_collector._total_bytes == 0
        assert len(metrics_collector._durations) == 0

    def test_record_successful_request(self, metrics_collector, sample_metrics):
        """Test recording successful request."""
        metrics_collector.record_request(sample_metrics)

        assert metrics_collector._total_requests == 1
        assert metrics_collector._successful_requests == 1
        assert metrics_collector._failed_requests == 0
        assert metrics_collector._total_bytes == 1024
        assert len(metrics_collector._durations) == 1
        assert metrics_collector._durations[0] == 150.5

    def test_record_failed_request(self, metrics_collector):
        """Test recording failed request."""
        error_metrics = RequestMetrics(
            url="https://example.com",
            method="GET",
            status_code=500,
            duration_ms=100.0,
            size_bytes=0,
            timestamp=datetime.now(),
            error="Server error",
        )

        metrics_collector.record_request(error_metrics)

        assert metrics_collector._total_requests == 1
        assert metrics_collector._successful_requests == 0
        assert metrics_collector._failed_requests == 1
        assert metrics_collector._total_bytes == 0

    def test_record_multiple_requests(self, metrics_collector):
        """Test recording multiple requests."""
        for i in range(10):
            metrics = RequestMetrics(
                url=f"https://example.com/{i}",
                method="GET",
                status_code=200 if i < 8 else 500,
                duration_ms=100.0 + i,
                size_bytes=1000 * (i + 1),
                timestamp=datetime.now(),
                error=None if i < 8 else "Error",
            )
            metrics_collector.record_request(metrics)

        assert metrics_collector._total_requests == 10
        assert metrics_collector._successful_requests == 8
        assert metrics_collector._failed_requests == 2
        assert len(metrics_collector._durations) == 10

    def test_get_snapshot(self, metrics_collector):
        """Test get_snapshot returns correct data."""
        # Record some requests
        for i in range(5):
            metrics = RequestMetrics(
                url=f"https://example.com/{i}",
                method="GET",
                status_code=200,
                duration_ms=100.0 * (i + 1),
                size_bytes=1000,
                timestamp=datetime.now(),
            )
            metrics_collector.record_request(metrics)

        snapshot = metrics_collector.get_snapshot()

        assert snapshot.total_requests == 5
        assert snapshot.successful_requests == 5
        assert snapshot.failed_requests == 0
        assert snapshot.success_rate == 1.0
        assert snapshot.total_bytes == 5000
        assert snapshot.avg_duration_ms == 300.0  # (100+200+300+400+500)/5

    def test_get_snapshot_with_failures(self, metrics_collector):
        """Test get_snapshot calculates success rate correctly."""
        # 7 successes, 3 failures
        for i in range(10):
            metrics = RequestMetrics(
                url=f"https://example.com/{i}",
                method="GET",
                status_code=200 if i < 7 else 500,
                duration_ms=100.0,
                size_bytes=1000 if i < 7 else 0,
                timestamp=datetime.now(),
                error=None if i < 7 else "Error",
            )
            metrics_collector.record_request(metrics)

        snapshot = metrics_collector.get_snapshot()

        assert snapshot.total_requests == 10
        assert snapshot.successful_requests == 7
        assert snapshot.failed_requests == 3
        assert snapshot.success_rate == 0.7

    def test_get_percentiles(self, metrics_collector):
        """Test get_percentiles calculates correctly."""
        # Add 100 requests with durations 1-100ms
        for i in range(1, 101):
            metrics = RequestMetrics(
                url=f"https://example.com/{i}",
                method="GET",
                status_code=200,
                duration_ms=float(i),
                size_bytes=1000,
                timestamp=datetime.now(),
            )
            metrics_collector.record_request(metrics)

        percentiles = metrics_collector.get_percentiles([0.5, 0.95, 0.99])

        assert 49 <= percentiles[0.5] <= 51  # p50 ~= 50
        assert 94 <= percentiles[0.95] <= 96  # p95 ~= 95
        assert 98 <= percentiles[0.99] <= 100  # p99 ~= 99

    def test_get_percentiles_empty(self, metrics_collector):
        """Test get_percentiles with no data."""
        percentiles = metrics_collector.get_percentiles([0.5, 0.95])

        assert percentiles[0.5] == 0.0
        assert percentiles[0.95] == 0.0

    def test_thread_safety(self, metrics_collector):
        """Test thread-safe access to metrics."""
        import threading

        def record_metrics():
            for _ in range(100):
                metrics = RequestMetrics(
                    url="https://example.com",
                    method="GET",
                    status_code=200,
                    duration_ms=100.0,
                    size_bytes=1000,
                    timestamp=datetime.now(),
                )
                metrics_collector.record_request(metrics)

        # Spawn 10 threads, each recording 100 requests
        threads = [threading.Thread(target=record_metrics) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snapshot = metrics_collector.get_snapshot()
        assert snapshot.total_requests == 1000

    def test_max_duration_stored(self, metrics_collector):
        """Test max 10000 durations stored."""
        # Record 15000 requests
        for i in range(15000):
            metrics = RequestMetrics(
                url=f"https://example.com/{i}",
                method="GET",
                status_code=200,
                duration_ms=100.0,
                size_bytes=1000,
                timestamp=datetime.now(),
            )
            metrics_collector.record_request(metrics)

        # Should only keep last 10000 durations
        assert len(metrics_collector._durations) == 10000
        assert metrics_collector._total_requests == 15000


class TestMetricsSnapshot:
    """Test MetricsSnapshot dataclass."""

    def test_initialization(self):
        """Test MetricsSnapshot initializes correctly."""
        snapshot = MetricsSnapshot(
            total_requests=100,
            successful_requests=95,
            failed_requests=5,
            success_rate=0.95,
            total_bytes=1024000,
            avg_duration_ms=150.5,
            min_duration_ms=50.0,
            max_duration_ms=500.0,
            p50_duration_ms=140.0,
            p95_duration_ms=450.0,
            p99_duration_ms=490.0,
        )

        assert snapshot.total_requests == 100
        assert snapshot.successful_requests == 95
        assert snapshot.failed_requests == 5
        assert snapshot.success_rate == 0.95


class TestFormatSnapshot:
    """Test format_snapshot utility."""

    def test_format_snapshot(self, metrics_collector):
        """Test format_snapshot produces readable output."""
        # Record some metrics
        for i in range(10):
            metrics = RequestMetrics(
                url=f"https://example.com/{i}",
                method="GET",
                status_code=200,
                duration_ms=100.0,
                size_bytes=1024,
                timestamp=datetime.now(),
            )
            metrics_collector.record_request(metrics)

        snapshot = metrics_collector.get_snapshot()
        output = format_snapshot(snapshot)

        assert "HTTP Metrics Snapshot" in output
        assert "Total Requests: 10" in output
        assert "Successful: 10" in output
        assert "Failed: 0" in output
        assert "Success Rate: 100.00%" in output
        assert "Total Bytes: 10.0 KB" in output

    def test_format_snapshot_with_failures(self, metrics_collector):
        """Test format_snapshot with failures."""
        # 7 successes, 3 failures
        for i in range(10):
            metrics = RequestMetrics(
                url=f"https://example.com/{i}",
                method="GET",
                status_code=200 if i < 7 else 500,
                duration_ms=100.0,
                size_bytes=1000 if i < 7 else 0,
                timestamp=datetime.now(),
                error=None if i < 7 else "Error",
            )
            metrics_collector.record_request(metrics)

        snapshot = metrics_collector.get_snapshot()
        output = format_snapshot(snapshot)

        assert "Successful: 7" in output
        assert "Failed: 3" in output
        assert "Success Rate: 70.00%" in output


class TestSingletonPattern:
    """Test singleton metrics collector."""

    def test_get_metrics_collector_singleton(self):
        """Test get_metrics_collector returns singleton."""
        collector1 = get_metrics_collector()
        collector2 = get_metrics_collector()

        assert collector1 is collector2

    def test_reset_metrics_collector(self):
        """Test reset_metrics_collector creates new instance."""
        collector1 = get_metrics_collector()

        # Record some data
        metrics = RequestMetrics(
            url="https://example.com",
            method="GET",
            status_code=200,
            duration_ms=100.0,
            size_bytes=1000,
            timestamp=datetime.now(),
        )
        collector1.record_request(metrics)

        # Reset and get new instance
        reset_metrics_collector()
        collector2 = get_metrics_collector()

        assert collector2 is not collector1
        assert collector2._total_requests == 0
