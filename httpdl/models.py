from __future__ import annotations
from dataclasses import dataclass, field
from typing import Mapping, Optional
from pathlib import Path

@dataclass
class DataDownloadResult:
    """Result from DataDownload - contains processed/decoded content."""
    url: str
    status_code: int
    headers: Mapping[str, str]
    content_type: Optional[str]
    kind: str                 # "json" | "xml" | "html" | "sgml" | "atom" | "binary" | "archive" | "unknown"
    text: Optional[str]       # decoded for text-like kinds
    bytes_: Optional[bytes]   # for archive/binary/unknown
    charset: Optional[str]
    duration_ms: int
    size_bytes: int
    sniff_note: Optional[str]
    redirect_chain: list[str] = field(default_factory=list)  # URLs visited during redirects

    # Should we have this as a common slice, or only in secdowloader, I think it should be in secdownloader + its logging


@dataclass
class FileDownloadResult:
    """
    Result from FileDownload - contains raw file data or file path.

    Note: This is a temporary implementation. In production, the file_path
    will be replaced with object store references (S3 key, Azure blob path, etc.)
    once the document store/object store SDK provider is decided.
    """
    url: str
    status_code: int
    headers: Mapping[str, str]
    content_type: Optional[str]      # Raw Content-Type header value
    content_encoding: Optional[str]  # Raw Content-Encoding (gzip, deflate, etc.)
    file_path: Optional[Path]        # Path where file was saved (if saved to disk)
    # TODO: Replace file_path with object_store_key once provider is selected
    # object_store_key: Optional[str]  # S3 key, Azure blob path, etc.
    bytes_: Optional[bytes]          # Raw bytes if not saved to disk
    duration_ms: int
    size_bytes: int                  # Size of raw downloaded bytes
    saved_to_disk: bool              # Whether the file was saved to disk
    redirect_chain: list[str] = field(default_factory=list)  # URLs visited during redirects