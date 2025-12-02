"""
Tests for the FileDownload client.

The previous version of this module executed real HTTP downloads inside the
test-suite, which stalled pytest.  These tests stub the httpx streaming layer so
we can verify the high-level behaviour (streaming to disk vs memory, error
handling) without network access.
"""

from __future__ import annotations

from typing import Iterable

import httpx
import pytest

from httpdl import DownloadSettings, FileDownload
from httpdl.exceptions import InvalidURLError


class DummyStreamResponse:
    """Async context manager that mimics httpx's streaming interface."""

    def __init__(self, chunks: Iterable[bytes], headers: dict[str, str] | None = None) -> None:
        self._chunks = list(chunks)
        self.headers = httpx.Headers(headers or {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    async def aiter_raw(self, chunk_size: int = 8192):
        for chunk in self._chunks:
            yield chunk


@pytest.fixture(autouse=True)
def disable_rate_limit(monkeypatch):
    """Disable rate limiting for deterministic tests."""

    async def _noop(self):
        return None

    monkeypatch.setattr(FileDownload, "_apply_rate_limit", _noop)


@pytest.fixture
async def file_client(tmp_path):
    async with FileDownload(DownloadSettings(), download_dir=tmp_path) as client:
        yield client


@pytest.mark.asyncio
async def test_download_streams_file_to_disk(file_client, tmp_path, monkeypatch):
    chunks = [b"hello ", b"world"]
    headers = {"Content-Type": "text/plain"}

    def fake_stream(method: str, url: str):
        assert method == "GET"
        return DummyStreamResponse(chunks, headers)

    monkeypatch.setattr(file_client._client, "stream", fake_stream)

    result = await file_client.download("https://example.com/report.txt", stream_to_disk=True)

    assert result.saved_to_disk is True
    assert result.file_path is not None
    assert result.bytes_ is None
    assert result.size_bytes == sum(len(c) for c in chunks)
    assert result.file_path.exists()
    assert result.file_path.read_bytes() == b"".join(chunks)
    assert result.file_path.parent == tmp_path


@pytest.mark.asyncio
async def test_download_to_memory_returns_bytes(file_client, monkeypatch):
    chunks = [b"alpha", b"beta"]

    def fake_stream(method: str, url: str):
        return DummyStreamResponse(chunks, {"Content-Type": "application/octet-stream"})

    monkeypatch.setattr(file_client._client, "stream", fake_stream)

    result = await file_client.download(
        "https://example.com/blob.bin",
        stream_to_disk=False,
    )

    assert result.saved_to_disk is False
    assert result.file_path is None
    assert result.bytes_ == b"alphabeta"
    assert result.size_bytes == len(b"alphabeta")


@pytest.mark.asyncio
async def test_download_rejects_empty_url(file_client):
    with pytest.raises(InvalidURLError):
        await file_client.download("   ")
