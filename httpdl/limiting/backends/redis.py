import time
from typing import TYPE_CHECKING

from .base import BaseLimiterBackend

if TYPE_CHECKING:
    import redis.asyncio as aioredis

class RedisBackend(BaseLimiterBackend):
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