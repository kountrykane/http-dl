"""
Test script for the async download package
"""

import asyncio
from httpdl import DataDownload, DownloadSettings

async def test_basic_download():
    """Test a basic download operation with DataDownload"""
    settings = DownloadSettings(
        requests_per_second=2,  # Slower rate for testing
        max_concurrency_per_host=2,
        follow_redirects=True,
    )

    # Using the async context manager with DataDownload
    async with DataDownload(settings) as client:
        # Test downloading a simple file from SEC EDGAR
        test_url = "https://www.sec.gov/Archives/edgar/data/1318605/000095017023001409/tsla-20221231.htm"

        print("Testing async download...")
        print(f"URL: {test_url}")

        try:
            # Await the async download call
            result = await client.download(test_url)

            print(f"\nDownload successful!")
            print(f"Status Code: {result.status_code}")
            print(f"Content Type: {result.content_type}")
            print(f"Kind: {result.kind}")
            print(f"Size: {result.size_bytes} bytes")
            print(f"Duration: {result.duration_ms} ms")
            print(f"Charset: {result.charset}")

            # Check for redirects
            if result.redirect_chain:
                print(f"Redirects: {' -> '.join(result.redirect_chain)}")
            else:
                print("No redirects")

            if result.text:
                print(f"Text preview (first 200 chars): {result.text[:200]}...")
            elif result.bytes_:
                print(f"Binary data received: {len(result.bytes_)} bytes")

        except Exception as e:
            print(f"Error during download: {e}")

async def test_multiple_downloads():
    """Test multiple downloads to verify rate limiting"""
    settings = DownloadSettings(
        requests_per_second=2,  # 2 requests per second max
        max_concurrency_per_host=2,
        follow_redirects=True,
    )

    async with DataDownload(settings) as client:
        # Test URLs (using smaller files for speed)
        test_urls = [
            "https://www.sec.gov/files/company_tickers.json",
            "https://www.sec.gov/Archives/edgar/data/789019/000156459021002316/msft-10k_20200630.htm",
            "https://www.sec.gov/Archives/edgar/data/320193/000032019321000065/aapl-20210327.htm"
        ]

        print("\nTesting rate limiting with multiple downloads...")

        import time
        start_time = time.time()

        for i, url in enumerate(test_urls, 1):
            try:
                print(f"\n[{i}] Downloading: {url.split('/')[-1]}")

                download_start = time.time()
                result = await client.download(url)
                download_time = time.time() - download_start

                print(f"    Status: {result.status_code}")
                print(f"    Kind: {result.kind}")
                print(f"    Size: {result.size_bytes} bytes")
                print(f"    Download time: {download_time:.2f} seconds")

                # Show redirect info
                if result.redirect_chain:
                    print(f"    Redirects: {len(result.redirect_chain)} hop(s)")

            except Exception as e:
                print(f"    Error: {e}")

        total_time = time.time() - start_time
        print(f"\nTotal time for {len(test_urls)} downloads: {total_time:.2f} seconds")
        print(f"Average rate: {len(test_urls)/total_time:.2f} requests/second")
        print("(Should be limited to ~2 requests/second)")

async def test_error_handling():
    """Test error handling with invalid URL"""
    async with DataDownload() as client:
        print("\nTesting error handling...")

        # Test with non-existent URL
        bad_url = "https://www.sec.gov/this-does-not-exist-404.html"

        try:
            result = await client.download(bad_url)
            print(f"Unexpected success: {result.status_code}")
        except Exception as e:
            print(f"Expected error caught: {type(e).__name__}: {str(e)[:100]}...")


async def test_redirect_handling():
    """Test redirect handling"""
    settings = DownloadSettings(
        requests_per_second=2,
        follow_redirects=True,
        max_redirects=20,
    )

    async with DataDownload(settings) as client:
        print("\nTesting redirect handling...")

        # This URL often has redirects
        test_url = "http://sec.gov/files/company_tickers.json"  # http -> https redirect

        try:
            result = await client.download(test_url)
            print(f"Status: {result.status_code}")
            print(f"Final URL: {result.url}")
            if result.redirect_chain:
                print(f"Redirect chain ({len(result.redirect_chain)} hops):")
                for i, redirect_url in enumerate(result.redirect_chain, 1):
                    print(f"  {i}. {redirect_url}")
            else:
                print("No redirects occurred")

        except Exception as e:
            print(f"Error: {type(e).__name__}: {e}")


async def main():
    """Main test runner"""
    print("=" * 60)
    print("DataDownload Test Suite")
    print("=" * 60)

    # Run basic test
    await test_basic_download()

    # Test rate limiting
    await test_multiple_downloads()

    # Test error handling
    await test_error_handling()

    # Test redirect handling
    await test_redirect_handling()

    print("\n" + "=" * 60)
    print("All DataDownload tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())