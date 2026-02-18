from __future__ import annotations

"""FastEmbed local embedder backend.

Design goals:
- Fully local at runtime.
- Optional one-time model download during setup.

Policy:
- If allow_download=False and the model isn't present in cache_dir, fail fast.
"""

import os
from pathlib import Path
from typing import List

from .embedder import EmbeddingResult


class FastEmbedEmbedder:
    DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

    def __init__(self, model_name: str, cache_dir: str, allow_download: bool = False):
        self._model_name = model_name
        self._cache_dir = str(Path(cache_dir).expanduser())
        self._allow_download = bool(allow_download)

    @property
    def model_name(self) -> str:
        return f"fastembed:{self._model_name}"

    @property
    def dim(self) -> int:
        # FastEmbed determines dim from model; we'll infer on first call.
        return 0

    def _assert_model_present(self) -> None:
        # Heuristic: require some files exist in cache_dir. FastEmbed will create subfolders.
        p = Path(self._cache_dir)
        if not p.exists():
            if self._allow_download:
                return
            raise RuntimeError(
                f"FastEmbed model cache dir missing: {p}. Run embed_index.py with --allow-download to fetch the model locally."
            )
        # If cache dir exists but empty, treat as missing
        if not any(p.rglob("*")):
            if self._allow_download:
                return
            raise RuntimeError(
                f"FastEmbed model cache dir is empty: {p}. Run embed_index.py with --allow-download to fetch the model locally."
            )

    def embed_texts(self, texts: List[str]) -> EmbeddingResult:
        # Ensure deterministic local cache location
        os.environ.setdefault("FASTEMBED_CACHE_PATH", self._cache_dir)

        # Fail-fast guard if downloads are disallowed
        self._assert_model_present()

        from fastembed import TextEmbedding  # type: ignore

        emb = TextEmbedding(model_name=self._model_name, cache_dir=self._cache_dir)

        vecs: List[List[float]] = []
        for v in emb.embed(texts):
            # v is typically a numpy array
            vecs.append([float(x) for x in v])

        dim = len(vecs[0]) if vecs else 0
        return EmbeddingResult(model=self.model_name, dim=dim, vectors=vecs)
