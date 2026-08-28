"""Embedding abstraction — the ONLY contract upper layers may depend on.

Embedding is an internal infrastructure capability of MathTutor (user
documents / personal memory / curriculum retrieval). It is strictly
separated from the GENERATIVE model surface: generative calls always travel
through the user-configured OpenAI-compatible gateway, while embedding is
provisioned by the product itself.

Embedding Distribution Strategy = DEFERRED (see the development log,
"Embedding / Retrieval Infrastructure" section). The final model, runtime
format, packaging (bundled / first-run download / resource pack /
user-selected local model) and license evaluation are NOT decided here.
This module only freezes the interface + versioning contract so any future
distribution can be swapped in WITHOUT touching domain/application code.

Degradation semantics (design requirement): the MathTutor core must start
and solve/verify/teach even when NO embedding backend is available.
Semantic document RAG degrades or disables; lexical retrieval stays.
Nothing in ``domain/`` or ``application/`` imports a concrete embedding
library — adapters live in ``infrastructure/`` only.
"""

from __future__ import annotations

from typing import Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field

# A fixed-dimension float vector (dimension is declared by the descriptor).
EmbeddingVector = tuple[float, ...]

NormalizationKind = Literal["none", "l2"]


class EmbeddingDescriptor(BaseModel):
    """Versioned identity of one embedding backend + model.

    The descriptor is the index-lifecycle contract: any change to
    ``backend_id`` / ``model_id`` / ``model_version`` / ``dimension`` marks
    existing vector indexes as stale and triggers a rebuild. The descriptor
    is stored alongside every persisted vector index so a rebuild decision
    is always deterministic (never inferred from filenames or guesses).
    """

    model_config = ConfigDict(frozen=True)

    backend_id: str
    model_id: str
    model_version: str
    dimension: int = Field(ge=1)
    normalization: NormalizationKind = "l2"
    runtime_version: str = ""

    def index_signature(self) -> str:
        """Stable signature string used for index build comparison."""
        return "|".join(
            (
                self.backend_id,
                self.model_id,
                self.model_version,
                str(self.dimension),
                self.normalization,
            )
        )


class EmbeddingBackend(Protocol):
    """Minimal embedding capability contract (async, like every repository).

    Implementations live in ``infrastructure/`` only: today the
    deterministic test backend; in the future potentially
    ``BundledEmbeddingBackend`` / ``DownloadedEmbeddingBackend`` /
    ``LocalPathEmbeddingBackend`` — none of which may be imported from
    domain/application code.
    """

    def describe(self) -> EmbeddingDescriptor: ...

    async def embed_texts(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]: ...

    async def embed_query(self, text: str) -> EmbeddingVector: ...


class EmbeddingUnavailableError(RuntimeError):
    """Raised when a caller demands vectors but no backend is provisioned.

    Callers that CAN degrade (retrieval falls back to lexical) catch this;
    callers that cannot (none in the current design) must fail closed.
    The application core never fails to START because of this error.
    """


def validate_vector(descriptor: EmbeddingDescriptor, vector: EmbeddingVector) -> None:
    """Dimension + finiteness check; raises ValueError on any mismatch.

    This is the same fail-closed discipline as the verifier: a vector from
    a backend that does not match the declared descriptor never silently
    enters an index.
    """
    if len(vector) != descriptor.dimension:
        raise ValueError(
            f"embedding dimension mismatch: descriptor={descriptor.dimension}, "
            f"vector={len(vector)} (backend {descriptor.backend_id})"
        )
    for value in vector:
        if not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
            raise ValueError(
                f"embedding vector contains a non-finite value from backend "
                f"{descriptor.backend_id}"
            )


__all__ = [
    "EmbeddingBackend",
    "EmbeddingDescriptor",
    "EmbeddingUnavailableError",
    "EmbeddingVector",
    "NormalizationKind",
    "validate_vector",
]
