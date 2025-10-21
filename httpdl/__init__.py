"""
SEC Download Package - Async Implementation

This package provides async functionality for downloading SEC documents
with rate limiting, retry logic, and proper content handling.

Two download modes are available:
- DataDownload: Processes and decodes content (text decoding, decompression, classification)
- FileDownload: Downloads raw files without processing (preserves original encoding)

All download operations are now async and must be awaited.
"""

from .download import DataDownload, FileDownload
from .config import DownloadSettings, RetryPolicy, Timeouts



__all__ = [
    # Primary download classes
    "DataDownload",
    "FileDownload",

    # Configuration
    "DownloadSettings",
    "RetryPolicy",
    "Timeouts",
]
