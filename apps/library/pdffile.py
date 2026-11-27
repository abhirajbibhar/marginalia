"""
PDF file access: a bounded, seekable file-like over BookStorage.

pypdf needs ``read``/``seek``/``tell``; R2 (and large local files) must not be
slurped into Worker memory wholesale. RangeReader fetches only requested
windows and caps both the number of fetches and total bytes per instance, so
metadata extraction is bounded in size and I/O on both targets.
"""
from __future__ import annotations

from apps.library.storage import BookStorage


class RangeReader:
    """Minimal seekable binary file object backed by ranged storage reads."""

    CHUNK = 256 * 1024          # fetch window
    MAX_TOTAL_BYTES = 24 * 1024 * 1024   # hard budget per instance
    MAX_FETCHES = 128           # hard budget on request count

    def __init__(self, storage: BookStorage, key: str, size: int):
        self._storage = storage
        self._key = key
        self._size = size
        self._pos = 0
        self._fetched = 0
        self._total = 0

    # -- file-like protocol -------------------------------------------------
    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self._pos = offset
        elif whence == 1:
            self._pos += offset
        elif whence == 2:
            self._pos = self._size + offset
        self._pos = max(0, min(self._pos, self._size))
        return self._pos

    @property
    def size(self) -> int:
        return self._size

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self._size - self._pos
        n = max(0, min(n, self._size - self._pos))
        if n == 0:
            return b""
        end = self._pos + n - 1
        # Chunked fetch to respect budgets.
        out = bytearray()
        while len(out) < n:
            step = min(self.CHUNK, n - len(out))
            chunk_start = self._pos + len(out)
            chunk_end = chunk_start + step - 1
            self._guard(chunk_end - chunk_start + 1)
            out += self._storage.open_range(self._key, chunk_start, chunk_end)
        self._pos += n
        return bytes(out)

    # -- budgets ------------------------------------------------------------
    def _guard(self, nbytes: int) -> None:
        self._fetched += 1
        self._total += nbytes
        if self._fetched > self.MAX_FETCHES or self._total > self.MAX_TOTAL_BYTES:
            raise BudgetExceeded(
                f"RangeReader budget exceeded ({self._fetched} fetches, {self._total} bytes)"
            )


class BudgetExceeded(RuntimeError):
    """Raised when a bounded read crosses its budget (treat as invalid PDF)."""


def reader_for(storage: BookStorage, key: str) -> RangeReader:
    return RangeReader(storage, key, storage.size(key))
