"""Embedding runtime and concrete infrastructure adapters.

The product default remains an empty runtime.  A real backend is installed
only after the user explicitly enables and completes either the downloaded
local-model flow or the OpenAI-compatible cloud flow.  Every adapter maps
operational failures to :class:`EmbeddingUnavailableError`, preserving the
lexical-only product path.

``FakeEmbeddingBackend`` remains test-only and is never selected by product
settings.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Sequence

import httpx

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
LOCAL_RUNTIME_VERSION = "sentence-transformers-1"
REMOTE_RUNTIME_VERSION = "openai-compatible-1"


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


class LocalSentenceTransformerBackend:
    """A downloaded SentenceTransformers model loaded without remote code."""

    def __init__(
        self,
        *,
        model_path: Path,
        model_id: str,
        model_version: str,
        dimension: int,
        query_instruction: str = "为这个句子生成表示以用于检索相关文章：",
    ) -> None:
        self._model_path = Path(model_path)
        self._query_instruction = query_instruction
        self._model = None
        identity = hashlib.sha256(
            f"{model_id}|{model_version}".encode("utf-8")
        ).hexdigest()[:16]
        self._descriptor = EmbeddingDescriptor(
            backend_id=f"local-st:{identity}",
            model_id=model_id,
            model_version=model_version,
            dimension=dimension,
            normalization="l2",
            runtime_version=LOCAL_RUNTIME_VERSION,
        )

    def describe(self) -> EmbeddingDescriptor:
        return self._descriptor

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                str(self._model_path),
                device="cpu",
                trust_remote_code=False,
            )
        except Exception as error:
            raise EmbeddingUnavailableError(
                "本地 Embedding 模型加载失败，请删除后重新下载。"
            ) from error
        return self._model

    def _encode(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]:
        try:
            model = self._load()
            values = model.encode(
                list(texts),
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            vectors = [tuple(float(value) for value in row) for row in values]
        except EmbeddingUnavailableError:
            raise
        except Exception as error:
            raise EmbeddingUnavailableError(
                "本地 Embedding 推理失败，已回退关键词检索。"
            ) from error
        if any(len(vector) != self._descriptor.dimension for vector in vectors):
            raise EmbeddingUnavailableError(
                "本地模型向量维度与配置不一致，请重新下载模型。"
            )
        return vectors

    async def embed_texts(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]:
        import asyncio

        return await asyncio.to_thread(self._encode, texts)

    async def embed_query(self, text: str) -> EmbeddingVector:
        vectors = await self.embed_texts([self._query_instruction + text])
        return vectors[0]


class OpenAICompatibleEmbeddingBackend:
    """Minimal OpenAI-compatible ``/embeddings`` client.

    The credential is held only in this process object.  It is resolved from
    ``SecretStore`` by ProductState and is never persisted here or included in
    exceptions. Unknown model dimensions are learned from the first response;
    the callback lets the settings service persist that non-sensitive value.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimension: int = 1,
        model_version: str = "provider-managed",
        timeout_seconds: float = 20.0,
        http: httpx.AsyncClient | None = None,
        on_dimension: Callable[[int], None] | None = None,
    ) -> None:
        identity = hashlib.sha256(
            f"{base_url.rstrip('/')}|{model}".encode("utf-8")
        ).hexdigest()[:16]
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._dimension = max(1, int(dimension))
        self._model_version = model_version
        self._timeout_seconds = timeout_seconds
        self._http = http
        self._on_dimension = on_dimension
        self._backend_id = f"openai-compatible:{identity}"

    def describe(self) -> EmbeddingDescriptor:
        return EmbeddingDescriptor(
            backend_id=self._backend_id,
            model_id=self._model,
            model_version=self._model_version,
            dimension=self._dimension,
            normalization="l2",
            runtime_version=REMOTE_RUNTIME_VERSION,
        )

    async def _request(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]:
        client = self._http or httpx.AsyncClient(timeout=self._timeout_seconds)
        owns_client = self._http is None
        try:
            response = await client.post(
                f"{self._base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "input": list(texts), "encoding_format": "float"},
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or len(rows) != len(texts):
                raise ValueError("invalid embeddings response")
            ordered = sorted(rows, key=lambda row: int(row.get("index", 0)))
            vectors = [tuple(float(value) for value in row["embedding"]) for row in ordered]
            dimension = len(vectors[0]) if vectors else self._dimension
            if dimension < 1 or any(len(vector) != dimension for vector in vectors):
                raise ValueError("inconsistent embedding dimension")
            if dimension != self._dimension:
                self._dimension = dimension
                if self._on_dimension is not None:
                    self._on_dimension(dimension)
            return vectors
        except Exception as error:
            raise EmbeddingUnavailableError(
                "云端 Embedding 服务不可用，已回退关键词检索。"
            ) from error
        finally:
            if owns_client:
                await client.aclose()

    async def embed_texts(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]:
        return await self._request(texts)

    async def embed_query(self, text: str) -> EmbeddingVector:
        return (await self._request([text]))[0]


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

    def __init__(self, backend: EmbeddingBackend | None = None, *, reason: str = "") -> None:
        self._backend = backend
        self._reason = reason or "Embedding 未启用，使用关键词检索。"

    def configure(self, backend: EmbeddingBackend | None, *, reason: str = "") -> None:
        """Atomically replace the active adapter after a settings change."""
        self._backend = backend
        self._reason = reason or "Embedding 未启用，使用关键词检索。"

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
    "LocalSentenceTransformerBackend",
    "OpenAICompatibleEmbeddingBackend",
    "build_fake_embedding_runtime",
]
