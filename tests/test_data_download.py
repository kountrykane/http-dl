"""
Test script for the synchronous download package
"""

from httpdl import DataDownload, DownloadSettings

def test_basic_download():
    """Test a basic download operation with DataDownload"""
    settings = DownloadSettings(
        requests_per_second=2,  # Slower rate for testing
        max_concurrency_per_host=2
    )
    
    # Using the synchronous context manager with DataDownload
    with DataDownload(settings) as client:
        # Test downloading a simple file from SEC EDGAR
        test_url = "https://www.sec.gov/Archives/edgar/data/1318605/000095017023001409/tsla-20221231.htm"
        
        print("Testing synchronous download...")
        print(f"URL: {test_url}")
        
        try:
            # Now this is synchronous - no await needed
            result = client.download(test_url)
            
            print(f"\nDownload successful!")
            print(f"Status Code: {result.status_code}")
            print(f"Content Type: {result.content_type}")
            print(f"Kind: {result.kind}")
            print(f"Size: {result.size_bytes} bytes")
            print(f"Duration: {result.duration_ms} ms")
            print(f"Charset: {result.charset}")
            
            if result.text:
                print(f"Text preview (first 200 chars): {result.text[:200]}...")
            elif result.bytes_:
                print(f"Binary data received: {len(result.bytes_)} bytes")
                
        except Exception as e:
            print(f"Error during download: {e}")

def test_multiple_downloads():
    """Test multiple downloads to verify rate limiting"""
    settings = DownloadSettings(
        requests_per_second=2,  # 2 requests per second max
        max_concurrency_per_host=2
    )
    
    with DataDownload(settings) as client:
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
                result = client.download(url)
                download_time = time.time() - download_start
                
                print(f"    Status: {result.status_code}")
                print(f"    Kind: {result.kind}")
                print(f"    Size: {result.size_bytes} bytes")
                print(f"    Download time: {download_time:.2f} seconds")
                
            except Exception as e:
                print(f"    Error: {e}")
        
        total_time = time.time() - start_time
        print(f"\nTotal time for {len(test_urls)} downloads: {total_time:.2f} seconds")
        print(f"Average rate: {len(test_urls)/total_time:.2f} requests/second")
        print("(Should be limited to ~2 requests/second)")

def test_error_handling():
    """Test error handling with invalid URL"""
    with DataDownload() as client:
        print("\nTesting error handling...")
        
        # Test with non-existent URL
        bad_url = "https://www.sec.gov/this-does-not-exist-404.html"
        
        try:
            result = client.download(bad_url)
            print(f"Unexpected success: {result.status_code}")
        except Exception as e:
            print(f"Expected error caught: {type(e).__name__}: {str(e)[:100]}...")

if __name__ == "__main__":
    print("=" * 60)
    print("DataDownload Test Suite")
    print("=" * 60)
    
    # Run basic test
    test_basic_download()
    
    # Test rate limiting
    test_multiple_downloads()
    
    # Test error handling
    test_error_handling()
    
    print("\n" + "=" * 60)
    print("All DataDownload tests completed!")
    print("=" * 60)