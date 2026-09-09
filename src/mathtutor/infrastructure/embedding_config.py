"""Persistent opt-in configuration and local model asset lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
from typing import Any

from mathtutor.infrastructure.embedding_runtime import (
    EmbeddingRuntime,
    LocalSentenceTransformerBackend,
    OpenAICompatibleEmbeddingBackend,
)
from mathtutor.infrastructure.secret_store import SecretStore

EMBEDDING_SECRET_KEY = "embedding.api_key"
CONFIG_VERSION = 1

LOCAL_MODELS: dict[str, dict[str, Any]] = {
    "bge-small-zh-v1.5": {
        "label": "BGE Small 中文 v1.5",
        "source": "ModelScope",
        "source_id": "AI-ModelScope/bge-small-zh-v1.5",
        "revision": "master",
        "dimension": 512,
        "size_label": "约 95 MB",
    },
}


def _defaults() -> dict[str, Any]:
    return {
        "config_version": CONFIG_VERSION,
        "enabled": False,
        "provider": "local",
        "local_model_id": "bge-small-zh-v1.5",
        "cloud_base_url": "",
        "cloud_model": "",
        "cloud_dimension": 0,
        "reindex_required": False,
    }


class EmbeddingConfigService:
    """Own settings JSON, secure-key reference and downloaded model state."""

    def __init__(
        self,
        *,
        data_dir: Path,
        secret_store: SecretStore,
        runtime: EmbeddingRuntime,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.config_path = self.data_dir / "config" / "embedding.json"
        self.models_dir = self.data_dir / "models" / "embedding"
        self.secret_store = secret_store
        self.runtime = runtime
        self._config = self._load()
        self._download_task: asyncio.Task[None] | None = None
        self._download_model_id = ""
        self._download_error = ""
        self._apply_local_sync()

    def _load(self) -> dict[str, Any]:
        values = _defaults()
        try:
            loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return values
        if not isinstance(loaded, dict):
            return values
        values["enabled"] = bool(loaded.get("enabled", False))
        provider = str(loaded.get("provider") or "local")
        values["provider"] = provider if provider in {"local", "cloud"} else "local"
        model_id = str(loaded.get("local_model_id") or values["local_model_id"])
        values["local_model_id"] = model_id if model_id in LOCAL_MODELS else "bge-small-zh-v1.5"
        values["cloud_base_url"] = str(loaded.get("cloud_base_url") or "")
        values["cloud_model"] = str(loaded.get("cloud_model") or "")
        values["cloud_dimension"] = max(0, int(loaded.get("cloud_dimension") or 0))
        values["reindex_required"] = bool(loaded.get("reindex_required", False))
        return values

    def _persist(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps(self._config, ensure_ascii=False, indent=2) + "\n"
        temporary = self.config_path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
        temporary.replace(self.config_path)

    def model_dir(self, model_id: str) -> Path:
        if model_id not in LOCAL_MODELS:
            raise ValueError("未知的本地 Embedding 模型。")
        return self.models_dir / model_id

    def local_ready(self, model_id: str) -> bool:
        directory = self.model_dir(model_id)
        has_weights = any(
            (directory / filename).exists()
            for filename in ("model.safetensors", "pytorch_model.bin")
        )
        return has_weights and (directory / "config.json").exists()

    def _local_backend(self) -> LocalSentenceTransformerBackend | None:
        model_id = str(self._config["local_model_id"])
        if not self.local_ready(model_id):
            return None
        spec = LOCAL_MODELS[model_id]
        return LocalSentenceTransformerBackend(
            model_path=self.model_dir(model_id),
            model_id=model_id,
            # The upstream branch name is mutable. The weight digest makes
            # the persisted index signature change when downloaded bytes do.
            model_version=self._asset_version(self.model_dir(model_id)),
            dimension=int(spec["dimension"]),
        )

    @staticmethod
    def _asset_version(directory: Path) -> str:
        weights = next(
            path
            for path in (directory / "model.safetensors", directory / "pytorch_model.bin")
            if path.exists()
        )
        digest = hashlib.sha256()
        with weights.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return f"sha256:{digest.hexdigest()[:16]}"

    def _apply_local_sync(self) -> None:
        if not self._config["enabled"]:
            self.runtime.configure(None, reason="Embedding 未启用，使用关键词检索。")
            return
        if self._config["provider"] != "local":
            self.runtime.configure(None, reason="云端 Embedding 等待安全密钥解析。")
            return
        current = self.runtime.backend()
        selected_model = str(self._config["local_model_id"])
        if (
            isinstance(current, LocalSentenceTransformerBackend)
            and current.describe().model_id == selected_model
            and self.local_ready(selected_model)
        ):
            return
        backend = self._local_backend()
        if backend is None:
            self.runtime.configure(None, reason="本地模型尚未下载，使用关键词检索。")
        elif importlib.util.find_spec("sentence_transformers") is None:
            self.runtime.configure(None, reason="本地 Embedding 运行组件未安装。")
        else:
            self.runtime.configure(backend)

    async def refresh_runtime(self) -> None:
        if not self._config["enabled"] or self._config["provider"] == "local":
            self._apply_local_sync()
            return
        base_url = str(self._config["cloud_base_url"]).strip().rstrip("/")
        model = str(self._config["cloud_model"]).strip()
        try:
            key = await self.secret_store.get(EMBEDDING_SECRET_KEY)
        except Exception:
            key = None
        if not base_url or not model or not key:
            self.runtime.configure(None, reason="云端 Embedding 配置不完整，使用关键词检索。")
            return
        self.runtime.configure(
            OpenAICompatibleEmbeddingBackend(
                base_url=base_url,
                api_key=key,
                model=model,
                dimension=int(self._config["cloud_dimension"] or 1),
                on_dimension=self._remember_cloud_dimension,
            )
        )

    def _remember_cloud_dimension(self, dimension: int) -> None:
        if dimension != self._config["cloud_dimension"]:
            self._config["cloud_dimension"] = dimension
            self._persist()

    async def public_settings(self) -> dict[str, Any]:
        try:
            key = await self.secret_store.get(EMBEDDING_SECRET_KEY)
        except Exception:
            key = None
        model_id = str(self._config["local_model_id"])
        download_status = "not_downloaded"
        if self._download_task is not None and not self._download_task.done():
            download_status = "downloading"
        elif self._download_error and self._download_model_id == model_id:
            download_status = "failed"
        elif self.local_ready(model_id):
            download_status = "ready"
        enabled = bool(self._config["enabled"])
        provider = str(self._config["provider"])
        cloud_complete = bool(
            self._config["cloud_base_url"] and self._config["cloud_model"] and key
        )
        if not enabled:
            badge = "disabled"
            label = "未启用 Embedding"
        elif provider == "local" and download_status == "ready" and self.runtime.status().available:
            badge = "local_ready"
            label = "本地模型就绪"
        elif provider == "cloud" and cloud_complete:
            badge = "cloud_configured"
            label = "云端已配置"
        else:
            badge = "incomplete"
            label = "配置不完整（回退关键词）"
        return {
            "enabled": enabled,
            "provider": provider,
            "local_model_id": model_id,
            "local_models": [
                {
                    "model_id": key_id,
                    "label": value["label"],
                    "dimension": value["dimension"],
                    "size_label": value["size_label"],
                    "source": value["source"],
                }
                for key_id, value in LOCAL_MODELS.items()
            ],
            "local_download_status": download_status,
            "local_download_error": self._download_error if download_status == "failed" else None,
            "cloud_base_url": str(self._config["cloud_base_url"]),
            "cloud_model": str(self._config["cloud_model"]),
            "cloud_has_api_key": bool(key),
            "cloud_key_masked": f"••••••••{key[-4:]}" if key else None,
            "status": badge,
            "status_label": label,
            "runtime_reason": self.runtime.status().reason or None,
            "reindex_required": bool(self._config["reindex_required"]),
        }

    async def update(
        self,
        *,
        enabled: bool,
        provider: str,
        local_model_id: str,
        cloud_base_url: str,
        cloud_model: str,
        cloud_api_key: str | None,
    ) -> dict[str, Any]:
        if provider not in {"local", "cloud"}:
            raise ValueError("请选择本地模型或云端模型。")
        if local_model_id not in LOCAL_MODELS:
            raise ValueError("未知的本地 Embedding 模型。")
        base_url = cloud_base_url.strip().rstrip("/")
        model = cloud_model.strip()
        if base_url and not base_url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("API Base URL 必须使用 HTTPS（或本机 loopback 地址）。")
        before = (
            self._config["enabled"],
            self._config["provider"],
            self._config["local_model_id"],
            self._config["cloud_base_url"],
            self._config["cloud_model"],
        )
        after = (enabled, provider, local_model_id, base_url, model)
        self._config.update(
            enabled=bool(enabled),
            provider=provider,
            local_model_id=local_model_id,
            cloud_base_url=base_url,
            cloud_model=model,
        )
        if before != after and bool(enabled):
            self._config["reindex_required"] = True
            if before[3:] != after[3:]:
                self._config["cloud_dimension"] = 0
        if cloud_api_key:
            await self.secret_store.put(EMBEDDING_SECRET_KEY, cloud_api_key)
        self._persist()
        await self.refresh_runtime()
        return await self.public_settings()

    async def remove_cloud_key(self) -> dict[str, Any]:
        await self.secret_store.delete(EMBEDDING_SECRET_KEY)
        await self.refresh_runtime()
        return await self.public_settings()

    async def test_cloud(self) -> dict[str, Any]:
        await self.refresh_runtime()
        if self._config["provider"] != "cloud" or not self.runtime.status().available:
            return {"ok": False, "message": "请先完整填写云端 Embedding 配置。"}
        try:
            vector = await self.runtime.embed_query("MathTutor Embedding 连接测试")
        except Exception:
            return {"ok": False, "message": "连接失败，请检查地址、密钥和模型名称。"}
        return {"ok": True, "message": f"连接成功，向量维度 {len(vector)}。"}

    async def start_download(self, model_id: str) -> dict[str, Any]:
        if model_id not in LOCAL_MODELS:
            raise ValueError("未知的本地 Embedding 模型。")
        if self._download_task is not None and not self._download_task.done():
            raise RuntimeError("已有模型正在下载。")
        self._download_model_id = model_id
        self._download_error = ""
        self._download_task = asyncio.create_task(self._download(model_id))
        return await self.public_settings()

    async def _download(self, model_id: str) -> None:
        target = self.model_dir(model_id)
        staging = target.with_name(f".{target.name}.downloading")
        try:
            if staging.exists():
                await asyncio.to_thread(shutil.rmtree, staging)
            staging.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            await asyncio.to_thread(self._download_snapshot_sync, model_id, staging)
            if not any((staging / name).exists() for name in ("model.safetensors", "pytorch_model.bin")):
                raise RuntimeError("下载内容缺少模型权重。")
            if target.exists():
                await asyncio.to_thread(shutil.rmtree, target)
            staging.replace(target)
            self._download_error = ""
            if self._config["enabled"] and self._config["provider"] == "local":
                self._config["reindex_required"] = True
                self._persist()
                await self.refresh_runtime()
        except Exception as error:
            if staging.exists():
                await asyncio.to_thread(shutil.rmtree, staging)
            message = str(error).strip()
            self._download_error = (
                "下载失败，请检查网络或稍后重试。"
                if not message
                else f"下载失败：{message[:180]}"
            )

    @staticmethod
    def _download_snapshot_sync(model_id: str, target: Path) -> None:
        try:
            from modelscope.hub.snapshot_download import snapshot_download
        except ImportError as error:
            raise RuntimeError("缺少 ModelScope 下载组件，请更新 MathTutor。") from error
        spec = LOCAL_MODELS[model_id]
        snapshot_download(
            spec["source_id"],
            revision=spec["revision"],
            local_dir=str(target),
            # The repository publishes duplicate PyTorch and Safetensors
            # weights. Keep the non-executable Safetensors copy only.
            ignore_patterns=["pytorch_model.bin"],
        )

    async def delete_local_model(self, model_id: str) -> dict[str, Any]:
        if self._download_task is not None and not self._download_task.done():
            raise RuntimeError("模型正在下载，请稍后再删除。")
        target = self.model_dir(model_id)
        if target.exists():
            await asyncio.to_thread(shutil.rmtree, target)
        self._download_error = ""
        await self.refresh_runtime()
        return await self.public_settings()

    def mark_reindexed(self) -> None:
        self._config["reindex_required"] = False
        self._persist()


__all__ = [
    "EMBEDDING_SECRET_KEY",
    "EmbeddingConfigService",
    "LOCAL_MODELS",
]
