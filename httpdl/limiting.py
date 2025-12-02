"""
Rate limiting with pluggable backends for single-process and multi-process scenarios.

This module provides a token bucket rate limiter that supports different backends:
- InMemoryBackend (default): Single-process, thread-safe
- RedisBackend: Multi-process/distributed via Redis
- MultiprocessBackend: Multi-process via multiprocessing.Manager

The rate limiter maintains a singleton bucket per backend to ensure process-wide
or distributed rate limiting.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional, TYPE_CHECKING

from .logging import get_httpdl_logger, log_rate_limit

if TYPE_CHECKING:
    from .limiting_backends import RateLimiterBackend


class AsyncTokenBucket:
    """
    Async token bucket with pluggable backend support.

    Uses a backend for state storage (in-memory, Redis, or multiprocessing.Manager).
    The backend handles locking and state persistence across processes if needed.
    """

    _min_sleep = 0.005

    def __init__(
        self,
        rate: float,
        capacity: Optional[float] = None,
        backend: Optional["RateLimiterBackend"] = None,
    ):
        """
        Initialize token bucket with pluggable backend.

        Args:
            rate: Tokens per second (requests per second)
            capacity: Maximum token capacity (burst size)
            backend: Backend for state storage (defaults to InMemoryBackend)
        """
        if rate <= 0:
            raise ValueError("rate must be positive")
        capacity = float(capacity) if capacity is not None else float(rate)
        if capacity <= 0:
            raise ValueError("capacity must be positive")

        self._rate = float(rate)
        self._capacity = capacity
        self._logger = get_httpdl_logger(__name__)

        # Initialize backend
        if backend is None:
            from .limiting_backends import InMemoryBackend
            backend = InMemoryBackend()

        self._backend = backend

        # Initialize backend state
        asyncio.create_task(self._initialize_backend())

        self._logger.debug(
            "token_bucket.initialized",
            rate=self._rate,
            capacity=self._capacity,
            backend=type(backend).__name__,
        )

    async def _initialize_backend(self) -> None:
        """Initialize backend with starting tokens."""
        current_tokens = await self._backend.get_tokens()
        if current_tokens == 0.0:
            # First initialization
            await self._backend.set_tokens(min(1.0, self._capacity))
            await self._backend.set_last_refill(time.monotonic())

    async def _refill(self) -> None:
        """Refill tokens based on elapsed time (must be called with lock held)."""
        now = time.monotonic()
        last_refill = await self._backend.get_last_refill()
        elapsed = now - last_refill

        if elapsed > 0:
            current_tokens = await self._backend.get_tokens()
            new_tokens = min(self._capacity, current_tokens + elapsed * self._rate)
            await self._backend.set_tokens(new_tokens)
            await self._backend.set_last_refill(now)

    async def configure(self, rate: float, capacity: Optional[float] = None) -> None:
        """
        Adopt stricter rate/capacity settings if a client requests them.

        This allows multiple clients to share the bucket while respecting
        the strictest rate limit requested by any client.
        """
        new_rate = float(rate)
        new_capacity = float(capacity) if capacity is not None else new_rate
        if new_rate <= 0 or new_capacity <= 0:
            raise ValueError("rate and capacity must be positive")

        # Acquire lock for configuration
        await self._backend.acquire_lock()
        try:
            await self._refill()
            rate_changed = False
            capacity_changed = False

            if new_rate < self._rate:
                self._rate = new_rate
                rate_changed = True

            if new_capacity != self._capacity:
                self._capacity = new_capacity
                # Clamp current tokens to new capacity
                current_tokens = await self._backend.get_tokens()
                if current_tokens > self._capacity:
                    await self._backend.set_tokens(self._capacity)
                capacity_changed = True

            if rate_changed or capacity_changed:
                self._logger.info(
                    "token_bucket.reconfigured",
                    new_rate=self._rate,
                    new_capacity=self._capacity,
                    rate_changed=rate_changed,
                    capacity_changed=capacity_changed,
                )
        finally:
            await self._backend.release_lock()

    async def wait(self, tokens: float = 1.0) -> None:
        """
        Wait until sufficient tokens are available and consume them.

        Args:
            tokens: Number of tokens to consume (default: 1.0)
        """
        if tokens <= 0:
            return

        wait_start = time.monotonic()
        total_wait = 0.0

        while True:
            # Acquire lock
            await self._backend.acquire_lock()
            try:
                # Refill tokens
                await self._refill()

                # Check if we have enough tokens
                current_tokens = await self._backend.get_tokens()
                if current_tokens >= tokens:
                    # Consume tokens and clamp tiny negatives due to floating point jitter
                    remaining = current_tokens - tokens
                    if remaining <= 1e-3:
                        remaining = 0.0
                    await self._backend.set_tokens(remaining)

                    if total_wait > 0:
                        log_rate_limit(
                            self._logger,
                            wait_ms=total_wait * 1000,
                            tokens_requested=tokens,
                        )
                    return

                # Calculate wait time
                deficit = tokens - current_tokens
                wait_time = max(deficit / self._rate, self._min_sleep)
            finally:
                await self._backend.release_lock()

            # Sleep without holding the lock
            await asyncio.sleep(wait_time)
            total_wait = time.monotonic() - wait_start

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def capacity(self) -> float:
        return self._capacity


class AsyncRateLimiter:
    """
    Process-wide or distributed rate limiter with pluggable backend support.

    Maintains a singleton AsyncTokenBucket per backend to ensure consistent
    rate limiting across all clients in a process (or across processes with
    Redis backend).
    """

    _shared_buckets: dict[str, AsyncTokenBucket] = {}
    _bucket_guard = asyncio.Lock()

    def __init__(
        self,
        rate: int,
        capacity: Optional[int] = None,
        backend: Optional["RateLimiterBackend"] = None,
    ):
        """
        Initialize rate limiter with pluggable backend.

        Args:
            rate: Requests per second
            capacity: Maximum burst capacity
            backend: Backend for state storage (defaults to InMemoryBackend)
        """
        # Create bucket key based on backend type
        backend_key = type(backend).__name__ if backend else "InMemoryBackend"

        # Ensure bucket exists (will be created on first access)
        self._backend_key = backend_key
        self._rate = float(rate)
        self._capacity = float(capacity) if capacity is not None else self._rate
        self._backend = backend

    async def _ensure_bucket(self) -> AsyncTokenBucket:
        """Ensure the shared bucket exists for this backend."""
        async with AsyncRateLimiter._bucket_guard:
            if self._backend_key not in AsyncRateLimiter._shared_buckets:
                # Create new bucket
                bucket = AsyncTokenBucket(
                    rate=self._rate,
                    capacity=self._capacity,
                    backend=self._backend,
                )
                AsyncRateLimiter._shared_buckets[self._backend_key] = bucket
            else:
                # Configure existing bucket with stricter settings
                bucket = AsyncRateLimiter._shared_buckets[self._backend_key]
                await bucket.configure(rate=self._rate, capacity=self._capacity)

            return bucket

    async def wait(self, tokens: float = 1.0) -> None:
        """
        Wait until tokens are available.

        Args:
            tokens: Number of tokens to consume
        """
        bucket = await self._ensure_bucket()
        await bucket.wait(tokens)

    @property
    async def rate(self) -> float:
        """Get current rate limit."""
        bucket = await self._ensure_bucket()
        return bucket.rate

    @property
    async def capacity(self) -> float:
        """Get current capacity."""
        bucket = await self._ensure_bucket()
        return bucket.capacity
