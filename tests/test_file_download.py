"""
Test script for the FileDownload functionality

TODO:
- Instead of saving to directory, it should be used to stream bytes to save in document/object store (Undecided)
"""


import tempfile
from pathlib import Path
import shutil

from httpdl import FileDownload, DownloadSettings


def test_file_download_to_disk():
    """Test downloading a file to disk without processing"""
    settings = DownloadSettings(
        requests_per_second=2,
        max_concurrency_per_host=2
    )
    
    # Create a temporary directory for downloads
    temp_dir = Path(tempfile.mkdtemp("tempdownload"))
    
    try:
        with FileDownload(settings, download_dir=temp_dir) as client:
            # Test downloading a JSON file (which would normally be processed)
            test_url = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000073/aapl-20250628.htm"
            
            print("Testing FileDownload with streaming to disk...")
            print(f"URL: {test_url}")
            print(f"Download directory: {temp_dir}")
            
            # Download the file
            result = client.download(test_url, stream_to_disk=True)
            
            print(f"\nDownload successful!")
            print(f"Status Code: {result.status_code}")
            print(f"Content Type: {result.content_type}")
            print(f"Content Encoding: {result.content_encoding}")
            print(f"File saved to: {result.file_path}")
            print(f"File size: {result.size_bytes} bytes")
            print(f"Duration: {result.duration_ms} ms")
            print(f"Saved to disk: {result.saved_to_disk}")
            
            # Verify the file exists
            assert result.file_path is not None
            assert result.file_path.exists()
            assert result.file_path.stat().st_size == result.size_bytes
            assert result.saved_to_disk is True
            assert result.bytes_ is None  # No bytes in memory when saved to disk
            
            print(f"File verification passed!")
            
    finally:
        # Cleanup
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
            print(f"Cleaned up temporary directory: {temp_dir}")


def test_file_download_to_memory():
    """Test downloading a file to memory without saving to disk"""
    settings = DownloadSettings(
        requests_per_second=2,
        max_concurrency_per_host=2
    )
    
    with FileDownload(settings) as client:
        # Use a smaller file for memory test
        test_url = "https://www.sec.gov/robots.txt"
        
        print("\nTesting FileDownload with in-memory storage...")
        print(f"URL: {test_url}")
        
        # Download the file to memory
        result = client.download(test_url, stream_to_disk=False)
        
        print(f"\nDownload successful!")
        print(f"Status Code: {result.status_code}")
        print(f"Content Type: {result.content_type}")
        print(f"Bytes in memory: {len(result.bytes_)} bytes")
        print(f"Duration: {result.duration_ms} ms")
        print(f"Saved to disk: {result.saved_to_disk}")
        
        # Verify the result
        assert result.bytes_ is not None
        assert len(result.bytes_) == result.size_bytes
        assert result.saved_to_disk is False
        assert result.file_path is None
        
        # Check that content is raw (not decoded)
        content_preview = result.bytes_[:100]
        print(f"Raw content preview: {content_preview[:50]}...")
        
        print("Memory download verification passed!")


def test_file_download_compressed():
    """Test that FileDownload keeps compressed content as-is"""
    settings = DownloadSettings(
        requests_per_second=2,
        max_concurrency_per_host=2
    )
    
    with FileDownload(settings) as client:
        # Many SEC files are served with gzip compression
        # FileDownload should keep them compressed
        test_url = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000073/aapl-20250628.htm"
        
        print("\nTesting FileDownload preserves compression...")
        print(f"URL: {test_url}")
        
        # Download to memory to check content
        result = client.download(test_url, stream_to_disk=False)
        
        print(f"\nDownload successful!")
        print(f"Status Code: {result.status_code}")
        print(f"Content Type: {result.content_type}")
        print(f"Content Encoding: {result.content_encoding}")
        print(f"Size (raw): {result.size_bytes} bytes")
        
        # If content-encoding indicates compression, the bytes should be compressed
        if result.content_encoding and 'gzip' in result.content_encoding.lower():
            # Check for gzip magic numbers
            assert result.bytes_[:2] == b'\x1f\x8b', "Content should be gzip compressed"
            print("Verified: Content is still gzip compressed (not decompressed)")
        else:
            print("Content was not compressed by server")
        
        print("Compression preservation test passed!")


def test_file_download_error_handling():
    """Test error handling for FileDownload"""
    with FileDownload() as client:
        print("\nTesting FileDownload error handling...")
        
        # Test with non-existent URL
        bad_url = "https://www.sec.gov/this-does-not-exist-404.html"
        
        try:
            result = client.download(bad_url)
            print(f"Unexpected success: {result.status_code}")
        except Exception as e:
            print(f"Expected error caught: {type(e).__name__}: {str(e)[:100]}...")
            assert "404" in str(e) or "HTTP" in str(e)
            print("Error handling verification passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("FileDownload Test Suite")
    print("=" * 60)
    
    # Test file download to disk
    test_file_download_to_disk()
    
    # Test file download to memory
    test_file_download_to_memory()
    
    # Test compression preservation
    test_file_download_compressed()
    
    # Test error handling
    test_file_download_error_handling()
    
    print("\n" + "=" * 60)
    print("All FileDownload tests completed!")
    print("=" * 60)