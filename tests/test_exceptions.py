"""
Comprehensive demonstration of the download library's exception handling system.

This example showcases how to use the granular exception types for precise error handling
and demonstrates best practices for working with the SEC download library.
"""

import asyncio
import logging
from pathlib import Path

from httpdl import (
    DataDownload,
    DownloadSettings,
    # Validation exceptions
    InvalidURLError,
    PayloadSizeLimitError,
    # Network exceptions
    ConnectionError as DownloadConnectionError,
    TimeoutError as DownloadTimeoutError,
    DNSResolutionError,
    # HTTP exceptions
    NotFoundError,
    ForbiddenError,
    RateLimitError,
    ServerError,
    # Content exceptions
    DecompressionError,
    # Retry exceptions
    RetryAttemptsExceeded,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def example_1_basic_error_handling():
    """
    Example 1: Basic error handling with specific exception types.

    This demonstrates how to catch different HTTP errors and handle them appropriately.
    """
    print("\n" + "="*70)
    print("EXAMPLE 1: Basic Error Handling")
    print("="*70)

    async with DataDownload() as client:
        urls = [
            "https://www.sec.gov/files/company_tickers.json",  # Valid
            "https://www.sec.gov/nonexistent.json",           # 404
            "",                                                # Invalid
        ]

        for url in urls:
            try:
                result = await client.download(url)
                print(f"✓ Downloaded {url[:50]}... ({result.size_bytes:,} bytes)")

            except InvalidURLError as e:
                print(f"✗ Invalid URL: {e}")

            except NotFoundError as e:
                print(f"✗ Not found (404): {e.url}")
                logger.warning(f"Document not found: {e.url}")

            except ForbiddenError as e:
                print(f"✗ Forbidden (403): {e.url}")
                logger.error(f"Access denied - check User-Agent: {e.url}")

            except Exception as e:
                print(f"✗ Unexpected error: {type(e).__name__}: {e}")


async def example_2_rate_limit_handling():
    """
    Example 2: Smart rate limit handling with automatic retry.

    Shows how to handle rate limits by respecting the Retry-After header.
    """
    print("\n" + "="*70)
    print("EXAMPLE 2: Rate Limit Handling")
    print("="*70)

    async def download_with_retry(url: str, max_retries: int = 3) -> str:
        """Download with automatic rate limit retry."""
        for attempt in range(max_retries):
            try:
                async with DataDownload() as client:
                    result = await client.download(url)
                    return result.text or ""

            except RateLimitError as e:
                if attempt < max_retries - 1:
                    retry_after = min(e.retry_after, 60)  # Cap at 60s for demo
                    print(f"  Rate limited. Waiting {retry_after}s before retry {attempt+1}/{max_retries-1}...")
                    await asyncio.sleep(retry_after)
                else:
                    print(f"  Rate limit exceeded after {max_retries} attempts")
                    raise

        raise Exception("Should not reach here")

    try:
        url = "https://www.sec.gov/files/company_tickers.json"
        print(f"Downloading: {url}")
        content = await download_with_retry(url)
        print(f"✓ Successfully downloaded ({len(content):,} chars)")
    except Exception as e:
        print(f"✗ Failed: {type(e).__name__}: {e}")


async def example_3_network_error_handling():
    """
    Example 3: Handling network-level errors.

    Demonstrates how to distinguish between different network failure modes.
    """
    print("\n" + "="*70)
    print("EXAMPLE 3: Network Error Handling")
    print("="*70)

    # Configure with shorter timeouts for demo
    settings = DownloadSettings()
    settings.timeouts.connect = 5.0
    settings.timeouts.read = 10.0

    async with DataDownload(settings) as client:
        test_cases = [
            ("https://httpbin.org/delay/15", "Timeout test (will fail)"),
            ("https://invalid-host-12345.sec.gov/test", "DNS resolution test (will fail)"),
        ]

        for url, description in test_cases:
            print(f"\nTesting: {description}")
            try:
                result = await client.download(url)
                print(f"  ✓ Success: {result.status_code}")

            except DownloadTimeoutError as e:
                print(f"  ✗ Timeout: {e.timeout_type} timeout after {e.timeout_seconds}s")
                logger.warning(f"Request timed out: {e.url}")

            except DNSResolutionError as e:
                print(f"  ✗ DNS resolution failed for: {e.hostname}")
                logger.error(f"Cannot resolve hostname: {e.hostname}")

            except DownloadConnectionError as e:
                print(f"  ✗ Connection failed: {e.host}:{e.port}")
                logger.error(f"Cannot connect to {e.host}:{e.port}")

            except RetryAttemptsExceeded as e:
                print(f"  ✗ Retries exhausted: {e.attempts} attempts")
                logger.error(f"Failed after {e.attempts} retries")


async def example_4_content_error_handling():
    """
    Example 4: Handling content processing errors.

    Shows how to handle decompression and payload size errors.
    """
    print("\n" + "="*70)
    print("EXAMPLE 4: Content Error Handling")
    print("="*70)

    # Configure with very small payload limit for demo
    settings = DownloadSettings()
    settings.max_decompressed_size_mb = 1  # Only 1MB

    async with DataDownload(settings) as client:
        try:
            # Try to download a large file that exceeds the limit
            url = "https://www.sec.gov/files/company_tickers.json"
            print(f"Downloading with 1MB size limit: {url}")
            result = await client.download(url)
            print(f"✓ Downloaded: {result.size_bytes:,} bytes")

        except PayloadSizeLimitError as e:
            print(f"✗ Payload too large!")
            print(f"  - Actual size: {e.actual_size:,} bytes")
            print(f"  - Max allowed: {e.max_size:,} bytes")
            logger.warning(f"Payload exceeded size limit: {e.actual_size:,} > {e.max_size:,}")

        except DecompressionError as e:
            print(f"✗ Decompression failed: {e.encoding}")
            logger.error(f"Cannot decompress {e.encoding} encoding")


async def example_5_hierarchical_exception_catching():
    """
    Example 5: Using exception hierarchy for flexible error handling.

    Demonstrates how to catch groups of related exceptions.
    """
    print("\n" + "="*70)
    print("EXAMPLE 5: Hierarchical Exception Catching")
    print("="*70)

    from hybrid_sec_parser.sec.download import (
        NetworkError,
        HTTPError,
        ClientError,
    )

    async with DataDownload() as client:
        urls = [
            "https://www.sec.gov/files/company_tickers.json",
            "https://www.sec.gov/nonexistent.json",
            "https://invalid-host-12345.sec.gov/test",
        ]

        for url in urls:
            try:
                result = await client.download(url)
                print(f"✓ {url}: {result.status_code}")

            except ClientError as e:
                # Catches all 4xx errors (BadRequest, NotFound, Forbidden, etc.)
                print(f"✗ Client error ({e.status_code}): {url}")
                logger.info(f"Client error {e.status_code} - likely not retryable")

            except ServerError as e:
                # Catches all 5xx errors (InternalServerError, BadGateway, etc.)
                print(f"✗ Server error ({e.status_code}): {url}")
                logger.warning(f"Server error {e.status_code} - might be transient")

            except HTTPError as e:
                # Catches any other HTTP errors not covered above
                print(f"✗ HTTP error ({e.status_code}): {url}")

            except NetworkError as e:
                # Catches all network-level errors (Timeout, Connection, DNS)
                print(f"✗ Network error: {type(e).__name__}")
                logger.error(f"Network failure: {type(e).__name__}: {e.message}")


async def example_6_error_context_and_debugging():
    """
    Example 6: Using exception context for debugging.

    Shows how to access rich error context for logging and debugging.
    """
    print("\n" + "="*70)
    print("EXAMPLE 6: Error Context and Debugging")
    print("="*70)

    async with DataDownload() as client:
        try:
            result = await client.download("https://www.sec.gov/nonexistent-file.json")
        except NotFoundError as e:
            print("Exception details:")
            print(f"  - Type: {type(e).__name__}")
            print(f"  - Message: {e.message}")
            print(f"  - URL: {e.url}")
            print(f"  - Status: {e.status_code}")
            print(f"  - Response excerpt: {e.response_excerpt[:100]}...")
            if e.response:
                print(f"  - Headers: {dict(list(e.response.headers.items())[:3])}...")
            if e.cause:
                print(f"  - Root cause: {type(e.cause).__name__}: {e.cause}")

            # Custom __str__ method provides formatted output
            print(f"\nFormatted string: {e}")


async def main():
    """Run all examples."""
    print("\n" + "="*70)
    print("SEC DOWNLOAD LIBRARY - EXCEPTION HANDLING EXAMPLES")
    print("="*70)

    # Run examples in sequence
    await example_1_basic_error_handling()
    await example_2_rate_limit_handling()

    # Skip network error examples that would fail in CI
    # await example_3_network_error_handling()

    await example_4_content_error_handling()
    await example_5_hierarchical_exception_catching()
    await example_6_error_context_and_debugging()

    print("\n" + "="*70)
    print("ALL EXAMPLES COMPLETED")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
