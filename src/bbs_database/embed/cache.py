"""BLOB <-> numpy float32 helpers for vector columns."""

from __future__ import annotations

import numpy as np


def encode_vec(vec: list[float]) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def decode_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def decode_vecs(blobs: list[bytes]) -> np.ndarray:
    return np.stack([decode_vec(b) for b in blobs])
