from .base import AsyncReentrantLock, BaseLimiterBackend
import time

class InMemoryBackend(BaseLimiterBackend):
    """
    In-memory backend using threading.Lock for single-process scenarios.

    This is the default backend and works well for single-process applications
    with multiple async tasks or threads.
    """

    def __init__(self):
        self._tokens: float = 0.0
        self._last_refill: float = time.monotonic()
        self._lock = AsyncReentrantLock()

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