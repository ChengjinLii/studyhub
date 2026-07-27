"""Stable pseudo-random values derived from a snapshot seed and action data."""

from __future__ import annotations

import hashlib

from app.agentic_platform.domain.hashing import canonical_json


class DeterministicRandomSource:
    """Hash-based random source independent of process/global RNG state.

    It is intentionally addressed by a caller-provided namespace rather than a
    mutable draw counter.  Thus an extra legal action cannot perturb the random
    outcome of a later action with a different deterministic key.
    """

    def __init__(self, seed: int) -> None:
        if seed < 0:
            raise ValueError("random seed must be non-negative")
        self.seed = seed

    def uint64(self, *parts: object) -> int:
        payload = canonical_json({"seed": self.seed, "parts": list(parts)}, exclude_fields=()).encode("utf-8")
        return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big", signed=False)

    def unit_interval(self, *parts: object) -> float:
        return self.uint64(*parts) / float(2**64)

    def rank_key(self, *parts: object) -> tuple[int, str]:
        """A deterministic sort key that is safe for IDs of any supported type."""

        return self.uint64(*parts), canonical_json(parts, exclude_fields=())
