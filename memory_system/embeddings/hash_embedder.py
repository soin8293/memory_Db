from __future__ import annotations

"""Deterministic stub embedder.

This is NOT a semantic embedding. It's a deterministic numeric fingerprint.
We use it to prove the pipeline end-to-end without installing heavy deps.

Upgrade path: swap in a real local embedder backend later.
"""

import hashlib
from typing import List

from .embedder import EmbeddingResult


class HashEmbedder:
    def __init__(self, dim: int = 96, model_name: str = "hash-v0"):
        self._dim = int(dim)
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dim(self) -> int:
        return self._dim

    def embed_texts(self, texts: List[str]) -> EmbeddingResult:
        vecs: List[List[float]] = []
        for t in texts:
            h = hashlib.sha256((t or "").encode("utf-8", errors="ignore")).digest()
            # Expand digest to dim floats in [-1,1]
            out: List[float] = []
            i = 0
            while len(out) < self._dim:
                b = h[i % len(h)]
                # map 0..255 -> -1..1
                out.append((b / 127.5) - 1.0)
                i += 1
            vecs.append(out)
        return EmbeddingResult(model=self.model_name, dim=self.dim, vectors=vecs)
