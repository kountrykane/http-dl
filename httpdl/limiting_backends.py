"""
Rate limiting backends for multi-process and distributed scenarios.

This module provides different backend implementations for the rate limiter:
- InMemoryBackend: Single-process, thread-safe (original implementation)
- RedisBackend: Multi-process and distributed, using Redis as shared state
- MultiprocessBackend: Multi-process using multiprocessing.Manager

Backends implement a common interface for token bucket operations.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as aioredis


class _AsyncReentrantLock:
    """Re-entrant asyncio-compatible lock keyed by current task."""

    def __init__(self) -> None:
        self._lock: Optional[asyncio.Lock] = None
        self._owner: Optional[asyncio.Task] = None
        self._depth = 0
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _ensure_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:
            self._lock = asyncio.Lock()
            self._loop = loop
        return self._lock

    async def acquire(self) -> None:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Async lock requires a running task")

        if self._owner is task:
            self._depth += 1
            return

        lock = self._ensure_lock()
        await lock.acquire()
        self._owner = task
        self._depth = 1

    def release(self) -> None:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Async lock requires a running task")
        if self._owner is not task:
            raise RuntimeError("Lock can only be released by the owning task")

        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            assert self._lock is not None
            self._lock.release()

    async def __aenter__(self) -> "_AsyncReentrantLock":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.release()


class RateLimiterBackend(ABC):
    """Abstract base class for rate limiter backends."""

    @abstractmethod
    async def get_tokens(self) -> float:
        """Get current token count."""
        pass

    @abstractmethod
    async def set_tokens(self, tokens: float) -> None:
        """Set token count."""
        pass

    @abstractmethod
    async def get_last_refill(self) -> float:
        """Get last refill timestamp."""
        pass

    @abstractmethod
    async def set_last_refill(self, timestamp: float) -> None:
        """Set last refill timestamp."""
        pass

    @abstractmethod
    async def acquire_lock(self) -> bool:
        """Acquire distributed lock. Returns True if acquired."""
        pass

    @abstractmethod
    async def release_lock(self) -> None:
        """Release distributed lock."""
        pass


class InMemoryBackend(RateLimiterBackend):
    """
    In-memory backend using threading.Lock for single-process scenarios.

    This is the default backend and works well for single-process applications
    with multiple async tasks or threads.
    """

    def __init__(self):
        self._tokens: float = 0.0
        self._last_refill: float = time.monotonic()
        self._lock = _AsyncReentrantLock()

    async def get_tokens(self) -> float:
        async with self._lock:
            return self._tokens

    async def set_tokens(self, tokens: float) -> None:
        async with self._lock:
            self._tokens = tokens

    async def get_last_refill(self) -> float:
        async with self._lock:
            return self._last_refill

    async def set_last_refill(self, timestamp: float) -> None:
        async with self._lock:
            self._last_refill = timestamp

    async def acquire_lock(self) -> bool:
        await self._lock.acquire()
        return True

    async def release_lock(self) -> None:
        self._lock.release()


class RedisBackend(RateLimiterBackend):
    """
    Redis-based backend for multi-process and distributed rate limiting.

    Uses Redis for shared state and distributed locking via SETNX.
    Requires redis[asyncio] package to be installed.

    Example:
        import redis.asyncio as aioredis

        redis_client = await aioredis.from_url("redis://localhost:6379")
        backend = RedisBackend(redis_client, key_prefix="httpdl:ratelimit")
    """

    def __init__(
        self,
        redis_client: "aioredis.Redis",
        key_prefix: str = "httpdl:ratelimit",
        lock_timeout: float = 10.0,
    ):
        """
        Initialize Redis backend.

        Args:
            redis_client: Async Redis client instance
            key_prefix: Prefix for Redis keys
            lock_timeout: Lock timeout in seconds (prevents deadlocks)
        """
        self._redis = redis_client
        self._key_prefix = key_prefix
        self._lock_timeout = lock_timeout
        self._lock_acquired = False

        # Redis keys
        self._tokens_key = f"{key_prefix}:tokens"
        self._last_refill_key = f"{key_prefix}:last_refill"
        self._lock_key = f"{key_prefix}:lock"

    async def get_tokens(self) -> float:
        value = await self._redis.get(self._tokens_key)
        if value is None:
            return 0.0
        return float(value)

    async def set_tokens(self, tokens: float) -> None:
        await self._redis.set(self._tokens_key, str(tokens))

    async def get_last_refill(self) -> float:
        value = await self._redis.get(self._last_refill_key)
        if value is None:
            return time.monotonic()
        return float(value)

    async def set_last_refill(self, timestamp: float) -> None:
        await self._redis.set(self._last_refill_key, str(timestamp))

    async def acquire_lock(self) -> bool:
        """
        Acquire distributed lock using Redis SETNX with expiration.

        Returns True if lock was acquired, False otherwise.
        """
        # Try to acquire lock with timeout
        acquired = await self._redis.set(
            self._lock_key,
            "1",
            nx=True,  # Only set if not exists
            ex=int(self._lock_timeout),  # Expiration in seconds
        )
        self._lock_acquired = bool(acquired)
        return self._lock_acquired

    async def release_lock(self) -> None:
        """Release distributed lock."""
        if self._lock_acquired:
            await self._redis.delete(self._lock_key)
            self._lock_acquired = False

    async def initialize(self, initial_tokens: float) -> None:
        """
        Initialize Redis state if not exists.

        Should be called once when setting up the rate limiter.
        """
        # Initialize tokens if not set
        if await self._redis.get(self._tokens_key) is None:
            await self.set_tokens(initial_tokens)

        # Initialize last refill timestamp
        if await self._redis.get(self._last_refill_key) is None:
            await self.set_last_refill(time.monotonic())

    async def close(self) -> None:
        """Clean up Redis connection."""
        await self._redis.close()


class MultiprocessBackend(RateLimiterBackend):
    """
    Multiprocessing-based backend for multi-process scenarios without Redis.

    Uses multiprocessing.Manager for shared state across processes.
    Suitable for local multi-process applications where a parent process
    spawns worker processes.

    Note: This backend requires manual initialization of the Manager
    in the main process before forking. Not suitable for Celery-style
    distributed workers (use RedisBackend instead).

    Example:
        from multiprocessing import Manager

        manager = Manager()
        backend = MultiprocessBackend(manager)
    """

    def __init__(self, manager):
        """
        Initialize multiprocessing backend.

        Args:
            manager: multiprocessing.Manager instance
        """
        self._namespace = manager.Namespace()
        self._namespace.tokens = 0.0
        self._namespace.last_refill = time.monotonic()
        self._lock = manager.Lock()

    async def get_tokens(self) -> float:
        return float(self._namespace.tokens)

    async def set_tokens(self, tokens: float) -> None:
        self._namespace.tokens = tokens

    async def get_last_refill(self) -> float:
        return float(self._namespace.last_refill)

    async def set_last_refill(self, timestamp: float) -> None:
        self._namespace.last_refill = timestamp

    async def acquire_lock(self) -> bool:
        """Acquire multiprocessing lock."""
        # Run in executor since Lock.acquire() is synchronous
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._lock.acquire)
        return True

    async def release_lock(self) -> None:
        """Release multiprocessing lock."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._lock.release)
