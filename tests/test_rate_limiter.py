"""
Test just the async rate limiter without network requests
"""

import asyncio
import time

from httpdl.limiting import AsyncTokenBucket

"""
The variation in Request Rate/Frequency is just measurement noise from the OS + event loop. 

On Windows the timer granularity is roughly 15 ms, 
so reported intervals jump around by a few milliseconds even though the intended spacing is 0.5 s

If you ever need even tighter pacing—for example, benchmarking scenarios, 
you’d have to accept a busy wait or use a higher-resolution timer API,
but for production throttling this behaviour is correct and healthy.
"""

async def test_pure_rate_limiting() -> None:
    """Test rate limiting without network overhead"""
    limiter = AsyncTokenBucket(rate=2)  # 2 requests per second

    print("Testing pure rate limiting (2 requests/second)...")
    print("=" * 60)

    request_times = []
    num_requests = 6

    start_time = time.time()

    for i in range(num_requests):
        request_start = time.time()

        # This is where the rate limiting happens
        await limiter.wait()

        request_end = time.time()
        request_times.append(request_end)

        elapsed_from_start = request_end - start_time
        time_since_last = request_end - request_times[-2] if len(request_times) > 1 else 0

        print(f"Request {i+1}: Rate-limited")
        print(f"  Time from start: {elapsed_from_start:.3f}s")
        if time_since_last > 0:
            print(f"  Time since last: {time_since_last:.3f}s")
        print()

    total_time = time.time() - start_time
    actual_rate = (num_requests - 1) / total_time if total_time > 0 else 0

    print("=" * 60)
    print("Summary:")
    print(f"  Total requests: {num_requests}")
    print(f"  Total time: {total_time:.2f} seconds")
    print(f"  Actual rate: {actual_rate:.2f} requests/second")
    print(f"  Expected rate: 2.0 requests/second")
    print(f"  Rate limiting working: {'YES' if abs(actual_rate - 2.0) <= 0.1 else 'NO'}")

    if len(request_times) > 1:
        intervals = []
        for i in range(1, len(request_times)):
            intervals.append(request_times[i] - request_times[i - 1])
        avg_interval = sum(intervals) / len(intervals)
        print(f"  Average interval: {avg_interval:.3f} seconds")
        print(f"  Expected interval: ~0.5 seconds (for 2 req/sec)")


if __name__ == "__main__":
    asyncio.run(test_pure_rate_limiting())
