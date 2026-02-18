from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol


@dataclass(frozen=True)
class EmbeddingResult:
    model: str
    dim: int
    vectors: List[List[float]]  # list of float vectors


class Embedder(Protocol):
    """Local embedder interface.

    Must be purely local (no network).
    """

    @property
    def model_name(self) -> str: ...

    @property
    def dim(self) -> int: ...

    def embed_texts(self, texts: List[str]) -> EmbeddingResult: ...
