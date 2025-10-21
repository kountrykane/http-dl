
from __future__ import annotations
from typing import Optional, Tuple
import gzip, zlib
import brotli
import httpx

__all__ = [
    "classify_kind",
    "decode_text",
    "decompress_transfer",
    "normalize_content_type",
    "extract_charset",
    "is_gzip_magic",
]

def normalize_content_type(hdrs: httpx.Headers) -> Optional[str]:
        ct = hdrs.get("Content-Type")
        return ct.split(";")[0].strip().lower() if ct else None

def extract_charset(hdrs: httpx.Headers) -> Optional[str]:
        ct = hdrs.get("Content-Type", "")
        parts = ct.split(";")
        for p in parts[1:]:
            p = p.strip()
            if p.lower().startswith("charset="):
                return p.split("=", 1)[1].strip()
        return None

def is_gzip_magic(b: bytes) -> bool:
        return len(b) >= 2 and b[0] == 0x1F and b[1] == 0x8B

def decompress_transfer(body: bytes, content_encoding: Optional[str]) -> bytes:
        if not body:
            return body
        if not content_encoding:
            # some endpoints omit header; sniff gzip magic
            if is_gzip_magic(body):
                try:
                    return gzip.decompress(body)
                except Exception:
                    return body
            return body

        enc = content_encoding.lower()
        try:
            if "gzip" in enc:
                return gzip.decompress(body)
            if "deflate" in enc:
                return zlib.decompress(body, -zlib.MAX_WBITS)
            if "br" in enc:
                return brotli.decompress(body)  # type: ignore
        except Exception:
            return body
        return body

def classify_kind(content_type: Optional[str], data: bytes) -> Tuple[str, Optional[str]]:
        if content_type:
            ct = content_type
            if ct == "application/json":
                return "json", None
            if ct in ("application/xml", "text/xml", "application/atom+xml"):
                return "xml", None
            if ct in ("text/html", "application/xhtml+xml"):
                return "html", None
            if ct == "text/sgml":
                return "sgml", None
            if ct.startswith("text/"):
                return "sgml", "treated text/* as sgml/plain"
            if ct in ("application/gzip", "application/zip"):
                return "archive", None

        # fallback sniff
        head = data[:64].lstrip().lower()
        if head.startswith(b"{") or head.startswith(b"["):
            return "json", "sniffed json"
        if head.startswith(b"<?xml"):
            return "xml", "sniffed xml"
        if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
            return "html", "sniffed html"
        if len(data) >= 2 and data[0] == 0x1F and data[1] == 0x8B:
            return "archive", "sniffed gzip magic"
        return "unknown", "no reliable content-type; returned raw"

def decode_text(data: bytes, charset: Optional[str]) -> Tuple[str, Optional[str]]:
        tried = []
        if charset:
            try:
                return data.decode(charset, errors="replace"), None
            except Exception as e:
                tried.append(f"{charset}({e})")
        for ch in ("utf-8", "windows-1252", "latin-1"):
            try:
                return data.decode(ch, errors="replace"), None
            except Exception as e:
                tried.append(f"{ch}({e})")
        return data.decode("utf-8", errors="replace"), f"fallback utf-8; tried={tried}"