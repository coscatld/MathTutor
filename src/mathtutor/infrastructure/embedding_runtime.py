"""EmbeddingRuntime — infrastructure-side resolution of the embedding backend.

Embedding Distribution Strategy = DEFERRED. The final backend may become
any of (bundled with the installer / first-run download / optional
resource pack / user-selected local model / other local asset management).
None of those is decided — and none is hard-coded into domain/application
contracts. Upper layers depend ONLY on ``EmbeddingBackend`` (domain
protocol); this module wires whatever backend exists at runtime and
degrades gracefully when there is none.

Today's only concrete backend is :class:`FakeEmbeddingBackend`: a fully
deterministic, dependency-free test/dev backend (fixed input → fixed
vector). It exists so chunk indexing, retrieval, index versioning,
rebuild and owner-isolation are testable with NO model weights, NO
network and NO GPU. It is explicitly NOT a product embedding model.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Sequence

from mathtutor.domain.embedding import (
    EmbeddingBackend,
    EmbeddingDescriptor,
    EmbeddingUnavailableError,
    EmbeddingVector,
)

FAKE_BACKEND_ID = "fake-deterministic"
FAKE_MODEL_ID = "fake-hash-v1"
FAKE_MODEL_VERSION = "1"
FAKE_DIMENSION = 64
FAKE_RUNTIME_VERSION = "mt-fake-1"


class FakeEmbeddingBackend:
    """Deterministic hash-based vectors (test/dev ONLY, never production).

    Construction: sha256 the text (with a namespace prefix), expand the
    digest into ``dimension`` floats in [-1, 1], then L2-normalize. The
    same input always yields the byte-identical vector — the property the
    index-lifecycle tests rely on.
    """

    def __init__(
        self,
        *,
        dimension: int = FAKE_DIMENSION,
        backend_id: str = FAKE_BACKEND_ID,
        model_id: str = FAKE_MODEL_ID,
        model_version: str = FAKE_MODEL_VERSION,
    ) -> None:
        self._descriptor = EmbeddingDescriptor(
            backend_id=backend_id,
            model_id=model_id,
            model_version=model_version,
            dimension=dimension,
            normalization="l2",
            runtime_version=FAKE_RUNTIME_VERSION,
        )

    def describe(self) -> EmbeddingDescriptor:
        return self._descriptor

    def _vector(self, text: str) -> EmbeddingVector:
        dimension = self._descriptor.dimension
        raw = hashlib.sha256(("mt-embed:" + text).encode("utf-8")).digest()
        # Expand the 32-byte digest across `dimension` floats deterministically.
        values: list[float] = []
        for index in range(dimension):
            seed = (index % len(raw)) ^ (raw[(index * 7 + 3) % len(raw)])
            base = raw[(index * 3) % len(raw)]
            values.append(((seed * 256 + base) % 2000) / 1000.0 - 1.0)
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return tuple(v / norm for v in values)

    async def embed_texts(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> EmbeddingVector:
        return self._vector("query:" + text)


@dataclass(frozen=True, slots=True)
class EmbeddingStatus:
    """Availability snapshot: available backend + reason when not."""

    available: bool
    descriptor: EmbeddingDescriptor | None = None
    reason: str = ""


class EmbeddingRuntime:
    """Process-wide resolver: one backend (or none) for the whole product.

    Constructed with ``None`` (the default) the runtime is UNAVAILABLE and
    every vector demand raises :class:`EmbeddingUnavailableError` — the
    documented degradation path. MathTutor core startup never depends on
    a backend being present.
    """

    def __init__(self, backend: EmbeddingBackend | None = None) -> None:
        self._backend = backend
        self._reason = "no embedding backend provisioned (distribution strategy DEFERRED)"

    def status(self) -> EmbeddingStatus:
        if self._backend is None:
            return EmbeddingStatus(available=False, reason=self._reason)
        return EmbeddingStatus(available=True, descriptor=self._backend.describe())

    def backend(self) -> EmbeddingBackend | None:
        return self._backend

    async def embed_texts(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]:
        if self._backend is None:
            raise EmbeddingUnavailableError(self._reason)
        return await self._backend.embed_texts(texts)

    async def embed_query(self, text: str) -> EmbeddingVector:
        if self._backend is None:
            raise EmbeddingUnavailableError(self._reason)
        return await self._backend.embed_query(text)


def build_fake_embedding_runtime(**kwargs) -> EmbeddingRuntime:
    """Convenience for tests/dev: a runtime over the deterministic backend."""
    return EmbeddingRuntime(FakeEmbeddingBackend(**kwargs))


__all__ = [
    "FAKE_BACKEND_ID",
    "FAKE_DIMENSION",
    "FAKE_MODEL_ID",
    "FAKE_MODEL_VERSION",
    "EmbeddingRuntime",
    "EmbeddingStatus",
    "FakeEmbeddingBackend",
    "build_fake_embedding_runtime",
]
