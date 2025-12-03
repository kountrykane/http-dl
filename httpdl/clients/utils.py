import inspect
from typing import Iterable

# Helper functions for streaming support
async def maybe_await(result):
    """Await value if it is awaitable, otherwise return as-is."""
    if inspect.isawaitable(result):
        return await result
    return result


async def ensure_async_iterator(candidate):
    """
    Convert various iterable/coroutine shapes into an async iterator.

    Testing utilities often rely on AsyncMock or plain lists; this helper keeps
    the production code resilient to those stubs while continuing to accept the
    real httpx streaming interfaces.
    """
    if inspect.isawaitable(candidate):
        candidate = await candidate

    if hasattr(candidate, "__aiter__"):
        return candidate

    if isinstance(candidate, Iterable):
        async def _generator():
            for chunk in candidate:
                yield chunk
        return _generator()

    raise TypeError("streaming response did not provide an async iterator")
