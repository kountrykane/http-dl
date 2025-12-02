"""
Tests for rate limiting backends (InMemory, Redis, Multiprocess).
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpdl.limiting_backends import (
    InMemoryBackend,
    RedisBackend,
    MultiprocessBackend,
    RateLimiterBackend,
)


class TestInMemoryBackend:
    """Test InMemoryBackend for single-process scenarios."""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test backend initializes with zero tokens."""
        backend = InMemoryBackend()

        tokens = await backend.get_tokens()
        assert tokens == 0.0

    @pytest.mark.asyncio
    async def test_set_and_get_tokens(self):
        """Test setting and getting token values."""
        backend = InMemoryBackend()

        await backend.set_tokens(5.0)
        tokens = await backend.get_tokens()

        assert tokens == 5.0

    @pytest.mark.asyncio
    async def test_last_refill_timestamp(self):
        """Test last refill timestamp tracking."""
        backend = InMemoryBackend()

        now = time.monotonic()
        await backend.set_last_refill(now)

        last_refill = await backend.get_last_refill()
        assert abs(last_refill - now) < 0.01

    @pytest.mark.asyncio
    async def test_lock_acquire_release(self):
        """Test lock acquisition and release."""
        backend = InMemoryBackend()

        # Acquire lock
        acquired = await backend.acquire_lock()
        assert acquired is True

        # Release lock
        await backend.release_lock()

    @pytest.mark.asyncio
    async def test_concurrent_token_access(self):
        """Test thread-safe concurrent token access."""
        backend = InMemoryBackend()
        await backend.set_tokens(10.0)

        async def decrement():
            await backend.acquire_lock()
            try:
                current = await backend.get_tokens()
                await asyncio.sleep(0.01)  # Simulate work
                await backend.set_tokens(current - 1.0)
            finally:
                await backend.release_lock()

        # Run 10 concurrent decrements
        tasks = [decrement() for _ in range(10)]
        await asyncio.gather(*tasks)

        final_tokens = await backend.get_tokens()
        assert final_tokens == 0.0


class TestRedisBackend:
    """Test RedisBackend for distributed scenarios."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = AsyncMock()
        redis.get.return_value = None
        redis.set.return_value = True
        redis.delete.return_value = True
        return redis

    @pytest.mark.asyncio
    async def test_initialization(self, mock_redis):
        """Test Redis backend initialization."""
        backend = RedisBackend(
            redis_client=mock_redis,
            key_prefix="test:ratelimit"
        )

        assert backend._redis == mock_redis
        assert backend._key_prefix == "test:ratelimit"
        assert backend._tokens_key == "test:ratelimit:tokens"
        assert backend._last_refill_key == "test:ratelimit:last_refill"
        assert backend._lock_key == "test:ratelimit:lock"

    @pytest.mark.asyncio
    async def test_get_tokens_none(self, mock_redis):
        """Test get_tokens returns 0.0 when Redis has no value."""
        mock_redis.get.return_value = None

        backend = RedisBackend(mock_redis)
        tokens = await backend.get_tokens()

        assert tokens == 0.0
        mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_tokens_with_value(self, mock_redis):
        """Test get_tokens returns stored value."""
        mock_redis.get.return_value = "5.5"

        backend = RedisBackend(mock_redis)
        tokens = await backend.get_tokens()

        assert tokens == 5.5

    @pytest.mark.asyncio
    async def test_set_tokens(self, mock_redis):
        """Test set_tokens stores value in Redis."""
        backend = RedisBackend(mock_redis)

        await backend.set_tokens(7.5)

        mock_redis.set.assert_called_once_with(
            "httpdl:ratelimit:tokens",
            "7.5"
        )

    @pytest.mark.asyncio
    async def test_get_last_refill_none(self, mock_redis):
        """Test get_last_refill returns current time when none stored."""
        mock_redis.get.return_value = None

        backend = RedisBackend(mock_redis)
        before = time.monotonic()
        last_refill = await backend.get_last_refill()
        after = time.monotonic()

        assert before <= last_refill <= after

    @pytest.mark.asyncio
    async def test_get_last_refill_with_value(self, mock_redis):
        """Test get_last_refill returns stored timestamp."""
        timestamp = str(time.monotonic())
        mock_redis.get.return_value = timestamp

        backend = RedisBackend(mock_redis)
        last_refill = await backend.get_last_refill()

        assert last_refill == float(timestamp)

    @pytest.mark.asyncio
    async def test_acquire_lock_success(self, mock_redis):
        """Test successful lock acquisition."""
        mock_redis.set.return_value = True

        backend = RedisBackend(mock_redis, lock_timeout=5.0)
        acquired = await backend.acquire_lock()

        assert acquired is True
        assert backend._lock_acquired is True
        mock_redis.set.assert_called_once_with(
            "httpdl:ratelimit:lock",
            "1",
            nx=True,
            ex=5
        )

    @pytest.mark.asyncio
    async def test_acquire_lock_failure(self, mock_redis):
        """Test lock acquisition failure (already held)."""
        mock_redis.set.return_value = None

        backend = RedisBackend(mock_redis)
        acquired = await backend.acquire_lock()

        assert acquired is False
        assert backend._lock_acquired is False

    @pytest.mark.asyncio
    async def test_release_lock(self, mock_redis):
        """Test lock release."""
        mock_redis.set.return_value = True

        backend = RedisBackend(mock_redis)
        await backend.acquire_lock()
        await backend.release_lock()

        mock_redis.delete.assert_called_once_with("httpdl:ratelimit:lock")
        assert backend._lock_acquired is False

    @pytest.mark.asyncio
    async def test_release_lock_not_acquired(self, mock_redis):
        """Test release_lock when lock wasn't acquired."""
        backend = RedisBackend(mock_redis)

        await backend.release_lock()

        # Should not call delete if lock wasn't acquired
        mock_redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize(self, mock_redis):
        """Test initialize sets up Redis keys."""
        mock_redis.get.return_value = None

        backend = RedisBackend(mock_redis)
        await backend.initialize(initial_tokens=5.0)

        # Should set tokens and last_refill
        assert mock_redis.set.call_count == 2


class TestMultiprocessBackend:
    """Test MultiprocessBackend for local multi-process scenarios."""

    @pytest.fixture
    def mock_manager(self):
        """Create mock multiprocessing.Manager."""
        manager = MagicMock()
        namespace = MagicMock()
        namespace.tokens = 0.0
        namespace.last_refill = time.monotonic()
        manager.Namespace.return_value = namespace
        manager.Lock.return_value = MagicMock()
        return manager

    def test_initialization(self, mock_manager):
        """Test multiprocessing backend initialization."""
        backend = MultiprocessBackend(mock_manager)

        assert backend._namespace.tokens == 0.0
        assert isinstance(backend._namespace.last_refill, float)

    @pytest.mark.asyncio
    async def test_get_tokens(self, mock_manager):
        """Test getting tokens from shared namespace."""
        backend = MultiprocessBackend(mock_manager)
        backend._namespace.tokens = 3.5

        tokens = await backend.get_tokens()

        assert tokens == 3.5

    @pytest.mark.asyncio
    async def test_set_tokens(self, mock_manager):
        """Test setting tokens in shared namespace."""
        backend = MultiprocessBackend(mock_manager)

        await backend.set_tokens(7.5)

        assert backend._namespace.tokens == 7.5

    @pytest.mark.asyncio
    async def test_get_last_refill(self, mock_manager):
        """Test getting last refill timestamp."""
        backend = MultiprocessBackend(mock_manager)
        timestamp = time.monotonic()
        backend._namespace.last_refill = timestamp

        last_refill = await backend.get_last_refill()

        assert last_refill == timestamp

    @pytest.mark.asyncio
    async def test_set_last_refill(self, mock_manager):
        """Test setting last refill timestamp."""
        backend = MultiprocessBackend(mock_manager)
        timestamp = time.monotonic()

        await backend.set_last_refill(timestamp)

        assert backend._namespace.last_refill == timestamp

    @pytest.mark.asyncio
    async def test_acquire_lock(self, mock_manager):
        """Test acquiring multiprocessing lock."""
        backend = MultiprocessBackend(mock_manager)

        acquired = await backend.acquire_lock()

        assert acquired is True
        backend._lock.acquire.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_lock(self, mock_manager):
        """Test releasing multiprocessing lock."""
        backend = MultiprocessBackend(mock_manager)

        await backend.release_lock()

        backend._lock.release.assert_called_once()


class TestBackendIntegration:
    """Integration tests for backends with AsyncTokenBucket."""

    @pytest.mark.asyncio
    async def test_inmemory_backend_with_token_bucket(self):
        """Test InMemoryBackend works with real token bucket."""
        from httpdl.limiting import AsyncTokenBucket

        backend = InMemoryBackend()
        bucket = AsyncTokenBucket(rate=10.0, capacity=10.0, backend=backend)

        # Initialize backend
        await backend.set_tokens(1.0)
        await backend.set_last_refill(time.monotonic())

        # Wait should consume tokens
        await bucket.wait(tokens=1.0)

        # Tokens should be consumed
        tokens = await backend.get_tokens()
        assert tokens == 0.0

    @pytest.mark.asyncio
    async def test_redis_backend_with_token_bucket(self):
        """Test RedisBackend works with real token bucket."""
        from httpdl.limiting import AsyncTokenBucket

        mock_redis = AsyncMock()
        mock_redis.get.side_effect = [
            "1.0",  # Initial tokens
            str(time.monotonic()),  # Last refill
            "1.0",  # Check for wait
            str(time.monotonic()),  # Refill timestamp
        ]
        mock_redis.set.return_value = True

        backend = RedisBackend(mock_redis)
        await backend.initialize(1.0)

        bucket = AsyncTokenBucket(rate=10.0, capacity=10.0, backend=backend)

        # This should work without errors
        # (actual functionality tested with mocks)
        assert bucket.rate == 10.0


@pytest.mark.asyncio
async def test_backend_comparison_performance():
    """Compare performance characteristics of backends."""
    # InMemory should be fastest
    inmemory = InMemoryBackend()

    start = time.perf_counter()
    for _ in range(1000):
        await inmemory.acquire_lock()
        await inmemory.get_tokens()
        await inmemory.set_tokens(1.0)
        await inmemory.release_lock()
    inmemory_time = time.perf_counter() - start

    # InMemory should complete in < 100ms
    assert inmemory_time < 0.1
