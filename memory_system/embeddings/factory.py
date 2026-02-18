from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import List, Literal, Optional

from memory_system.paths import default_models_cache_dir

from .embedder import Embedder, EmbeddingResult
from .hash_embedder import HashEmbedder


BackendName = Literal["hash", "fastembed"]

# OpenClaw's embedding cache location
OPENCLAW_DB_PATH = Path("~/.openclaw/memory/main.sqlite").expanduser()

# Embedding daemon socket
DAEMON_SOCKET_PATH = Path("~/.openclaw/embed.sock").expanduser()


def default_cache_dir() -> str:
    return str(default_models_cache_dir())


def get_cached_embedding(text: str) -> Optional[List[float]]:
    """Query OpenClaw's embedding_cache for a cached embedding.

    OpenClaw stores embeddings indexed by SHA-256 hash of text.
    Returns None if not found or cache unavailable.
    """
    if not OPENCLAW_DB_PATH.exists():
        return None

    try:
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        conn = sqlite3.connect(str(OPENCLAW_DB_PATH), timeout=1.0)
        try:
            row = conn.execute(
                "SELECT embedding FROM embedding_cache WHERE hash = ?", (text_hash,)
            ).fetchone()
            if row and row[0]:
                return json.loads(row[0])
        finally:
            conn.close()
    except (sqlite3.Error, json.JSONDecodeError):
        pass

    return None


def embed_via_daemon(texts: List[str], timeout: float = 10.0) -> Optional[EmbeddingResult]:
    """Try to embed texts via the daemon.

    Returns EmbeddingResult on success, None if daemon unavailable.
    """
    if not DAEMON_SOCKET_PATH.exists():
        return None

    try:
        from .daemon import embed_via_daemon as _daemon_embed
        result = _daemon_embed(texts, DAEMON_SOCKET_PATH, timeout)
        if result and "vectors" in result:
            return EmbeddingResult(
                model=result.get("model", "daemon"),
                dim=result.get("dim", len(result["vectors"][0]) if result["vectors"] else 0),
                vectors=result["vectors"],
            )
    except Exception:
        pass

    return None


class DaemonEmbedder:
    """Embedder that tries daemon first, falls back to local model.

    The daemon keeps the model loaded in memory for fast inference.
    """

    def __init__(self, inner: Embedder, timeout: float = 10.0):
        self._inner = inner
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    @property
    def dim(self) -> int:
        return self._inner.dim

    def embed_texts(self, texts: List[str]) -> EmbeddingResult:
        """Embed texts, trying daemon first."""
        result = embed_via_daemon(texts, self._timeout)
        if result is not None:
            return result
        return self._inner.embed_texts(texts)


class CachingEmbedder:
    """Wrapper that checks OpenClaw's cache before computing embeddings.

    Falls back to the underlying embedder for cache misses.
    """

    def __init__(self, inner: Embedder):
        self._inner = inner

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    @property
    def dim(self) -> int:
        return self._inner.dim

    def embed_texts(self, texts: List[str]) -> EmbeddingResult:
        """Embed texts, checking cache first for each."""
        vectors: List[List[float]] = []
        texts_to_compute: List[str] = []
        cache_hits: List[int] = []  # indices where we got cache hits

        # Check cache for each text
        for i, text in enumerate(texts):
            cached = get_cached_embedding(text)
            if cached is not None:
                vectors.append(cached)
                cache_hits.append(i)
            else:
                vectors.append([])  # placeholder
                texts_to_compute.append(text)

        # Compute embeddings for cache misses
        if texts_to_compute:
            result = self._inner.embed_texts(texts_to_compute)
            computed_idx = 0
            for i in range(len(texts)):
                if i not in cache_hits:
                    vectors[i] = result.vectors[computed_idx]
                    computed_idx += 1

        return EmbeddingResult(
            model=self._inner.model_name,
            dim=self._inner.dim,
            vectors=vectors,
        )


def get_embedder(
    name: BackendName,
    *,
    dim: int = 96,
    model: Optional[str] = None,
    cache_dir: Optional[str] = None,
    allow_download: bool = False,
    use_cache: bool = True,
    use_daemon: bool = True,
) -> Embedder:
    """Get an embedder instance.

    Args:
        name: Backend name ("hash" or "fastembed")
        dim: Embedding dimension (hash backend only)
        model: Model name (fastembed backend)
        cache_dir: Model cache directory
        allow_download: Allow one-time model download
        use_cache: Check OpenClaw's embedding cache first (default: True)
        use_daemon: Try embedding daemon first for fast inference (default: True)

    Returns:
        Embedder instance, optionally wrapped with caching/daemon layers

    Layer order (outer to inner):
        1. CachingEmbedder - checks OpenClaw's sqlite cache
        2. DaemonEmbedder - tries persistent daemon for fast inference
        3. Inner embedder - actual model loading (cold start)
    """
    if name == "hash":
        inner = HashEmbedder(dim=dim)
    elif name == "fastembed":
        from .fastembed_embedder import FastEmbedEmbedder

        inner = FastEmbedEmbedder(
            model_name=model or FastEmbedEmbedder.DEFAULT_MODEL,
            cache_dir=cache_dir or default_cache_dir(),
            allow_download=allow_download,
        )
    else:
        raise ValueError(f"Unknown embedder backend: {name}")

    # Wrap with daemon layer if requested and socket exists
    if use_daemon and DAEMON_SOCKET_PATH.exists():
        inner = DaemonEmbedder(inner)

    # Wrap with caching layer if requested and cache is available
    if use_cache and OPENCLAW_DB_PATH.exists():
        return CachingEmbedder(inner)

    return inner
