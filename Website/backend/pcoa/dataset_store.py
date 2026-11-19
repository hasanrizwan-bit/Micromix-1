"""
In-memory registry of parsed PCoA matrices.

Ported from ``ClusteredHeatmap2/backend/dataset_store.py`` (only the import of
``ParsedMatrix``/``DEFAULT_METRIC`` was changed to a relative import so the
module lives inside the ``pcoa`` package). The bounds, the eviction policy and
the cache-miss contract are otherwise unchanged.

Why this module exists
----------------------
``POST /api/pcoa`` is stateless per request: every request carries either a
fresh upload or an opaque handle to a previous one, and nothing but the
matrices themselves survive between requests. Interactive point selection
needs a SECOND calculation over the SAME uploaded matrix ("rerun the PCoA
using only these 14 samples"), which creates two requirements a fully
stateless design cannot meet:

  1. The original feature matrix must still be available after the first run,
     so a subset can be filtered *out of it* rather than re-derived from the
     PCoA coordinates that were sent to the browser.
  2. The server — not the client — must own the feature values. If the client
     re-posted the matrix for every subset it would be the authority on the
     data, so a tampered second upload could silently change the numbers behind
     an apparently "filtered" plot. Subset requests therefore carry only an
     opaque dataset id plus the selected SAMPLE IDS; coordinates and feature
     values never travel back to the server.

Bounds
------
A parsed matrix is a dense float64 array, so an unbounded cache would be a
memory leak. Entries are evicted when any of these is exceeded, least-recently
used first:

  * ``ttl_seconds``  — an idle dataset expires (default 2 hours)
  * ``max_datasets`` — number of retained uploads (default 6)
  * ``max_cells``    — total ``n_samples * n_features`` across all entries
    (default 12M cells ~= 96 MB of float64)

Caveats
-------
The store is process-local and not shared between workers, so it is a cache and
never the only copy of anything: a lookup can legitimately miss (server
restart, eviction, a different worker). Callers must treat a miss as a normal,
recoverable condition — the route reports it with the ``dataset_unavailable``
error code and the frontend transparently re-uploads the file it still holds.

This in-memory cache is a deliberate, documented parity choice for this
iteration (see the PCoA porting plan): Micromix persists session dataframes in
MongoDB elsewhere, but the reference PCoA's "rerun on selection" workflow is
ported as-is here rather than redesigned around Mongo, so behavior matches the
proven implementation exactly. Replacing this with Mongo-backed storage is
left for a later iteration.

Nothing here imports Flask, so the store is directly unit testable (see
``backend/pcoa/tests/test_service.py``).
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .service import DEFAULT_METRIC, ParsedMatrix

#: An idle dataset is dropped after this many seconds.
DEFAULT_TTL_SECONDS = 2 * 60 * 60

#: Maximum number of uploads retained at once.
DEFAULT_MAX_DATASETS = 6

#: Maximum total cell count across all retained uploads (~96 MB of float64).
DEFAULT_MAX_CELLS = 12_000_000


@dataclass
class StoredDataset:
    """One parsed upload plus the bookkeeping the store needs."""

    dataset_id: str
    matrix: ParsedMatrix
    filename: str | None = None
    metric: str = DEFAULT_METRIC
    created_at: float = 0.0
    last_used_at: float = 0.0

    @property
    def n_cells(self) -> int:
        return int(self.matrix.n_samples) * int(self.matrix.n_features)


@dataclass
class DatasetStore:
    """Bounded, thread-safe, least-recently-used store of parsed matrices.

    ``clock`` is injectable so the TTL can be tested without sleeping.
    """

    ttl_seconds: float = DEFAULT_TTL_SECONDS
    max_datasets: int = DEFAULT_MAX_DATASETS
    max_cells: int = DEFAULT_MAX_CELLS
    clock: Callable[[], float] = time.monotonic
    _entries: dict[str, StoredDataset] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # -- public API ---------------------------------------------------------

    def put(
        self,
        matrix: ParsedMatrix,
        filename: str | None = None,
        metric: str = DEFAULT_METRIC,
    ) -> str:
        """Store ``matrix`` and return its opaque dataset id.

        The id is generated with :mod:`secrets`, so it is not guessable and
        cannot be used to enumerate other users' uploads.
        """
        now = self.clock()
        dataset_id = secrets.token_urlsafe(16)
        entry = StoredDataset(
            dataset_id=dataset_id,
            matrix=matrix,
            filename=filename,
            metric=metric,
            created_at=now,
            last_used_at=now,
        )
        with self._lock:
            self._expire_locked(now)
            self._entries[dataset_id] = entry
            self._enforce_bounds_locked()
        return dataset_id

    def get(self, dataset_id: str | None) -> StoredDataset | None:
        """Return the stored dataset, or ``None`` when it is unknown/expired.

        A successful lookup refreshes the entry's recency so an actively used
        dataset is never evicted in favour of an idle one.
        """
        if not dataset_id or not isinstance(dataset_id, str):
            return None
        now = self.clock()
        with self._lock:
            self._expire_locked(now)
            entry = self._entries.get(dataset_id)
            if entry is None:
                return None
            entry.last_used_at = now
            # Re-insert so ``_entries`` stays ordered oldest-use-first, which is
            # what the LRU eviction below relies on.
            del self._entries[dataset_id]
            self._entries[dataset_id] = entry
            return entry

    def remove(self, dataset_id: str) -> bool:
        """Drop one dataset. Returns ``True`` when something was removed."""
        with self._lock:
            return self._entries.pop(dataset_id, None) is not None

    def clear(self) -> None:
        """Drop every dataset (used by tests and by ``/api/pcoa`` resets)."""
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict:
        """Small diagnostic snapshot (also handy from the test suite)."""
        with self._lock:
            return {
                "datasets": len(self._entries),
                "cells": sum(e.n_cells for e in self._entries.values()),
                "max_datasets": self.max_datasets,
                "max_cells": self.max_cells,
                "ttl_seconds": self.ttl_seconds,
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, dataset_id: object) -> bool:
        return self.get(dataset_id if isinstance(dataset_id, str) else None) is not None

    # -- internals (call with the lock held) --------------------------------

    def _expire_locked(self, now: float) -> None:
        if self.ttl_seconds <= 0:
            return
        stale = [
            key
            for key, entry in self._entries.items()
            if now - entry.last_used_at > self.ttl_seconds
        ]
        for key in stale:
            del self._entries[key]

    def _enforce_bounds_locked(self) -> None:
        # ``_entries`` is ordered least-recently-used first (``get`` re-inserts
        # on hit and ``put`` appends), so evicting from the front is LRU.
        while len(self._entries) > max(1, self.max_datasets):
            self._entries.pop(next(iter(self._entries)))
        while (
            len(self._entries) > 1
            and sum(e.n_cells for e in self._entries.values()) > self.max_cells
        ):
            self._entries.pop(next(iter(self._entries)))
