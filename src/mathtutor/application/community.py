"""Owner-scoped community directories, explicit downloads and personal copies.

The directory contains verifiable packages, not invented social statistics.
Refreshing metadata never downloads a referenced package or installs anything.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from mathtutor.application.knowledge import KnowledgeError
from mathtutor.application.question_packs import MAX_UPLOAD_BYTES, QUESTION_FORMAT, QuestionPackService, parse_pack

CATALOG_FORMAT = "mathtutor.community-catalog.v1"
RESOURCE_FORMAT = "mathtutor.community-resource.v1"
MAX_CATALOG_BYTES = 8 * 1024 * 1024
MAX_SHARE_BYTES = 32 * 1024 * 1024
MAX_OWNER_BYTES = 64 * 1024 * 1024
ASSETS = Path(__file__).resolve().parents[1] / "community_assets"
_VERSION = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*))?$"


class CommunityError(KnowledgeError):
    pass


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResourceMetadata(Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,79}$")
    version: str = Field(pattern=_VERSION, max_length=40)
    type: str = Field(pattern=r"^(question-pack|plugin)$")
    name: str = Field(min_length=1, max_length=120)
    author: str = Field(min_length=1, max_length=200)
    license: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=32)
    grades: list[int] = Field(default_factory=list, max_length=12)
    readme: str = Field(default="", max_length=16000)
    changelog: str = Field(default="", max_length=12000)
    package_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    permissions: list[str] = Field(default_factory=list, max_length=32)
    project_example: bool = False
    project_url: str | None = None
    issues_url: str | None = None
    discussions_url: str | None = None

    @model_validator(mode="after")
    def bounded_metadata(self):
        if any(not value.strip() for value in (self.name, self.author, self.license, self.description)):
            raise ValueError("Empty metadata")
        if any(not tag.strip() or len(tag) > 64 for tag in self.tags + self.permissions):
            raise ValueError("Invalid tags or permissions")
        if any(grade < 1 or grade > 12 for grade in self.grades) or len(set(self.grades)) != len(self.grades):
            raise ValueError("Invalid grades")
        for name in ("project_url", "issues_url", "discussions_url"):
            if getattr(self, name) is not None:
                setattr(self, name, _public_url(getattr(self, name)))
        return self


class PackageReference(Strict):
    filename: str = Field(min_length=1, max_length=160)
    media_type: str = Field(pattern=r"^application/(json|zip)$")
    data: dict | None = None
    data_base64: str | None = Field(default=None, max_length=28 * 1024 * 1024)
    bundled_path: str | None = Field(default=None, max_length=160)
    download_url: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode="after")
    def one_source(self):
        if sum(value is not None for value in (self.data, self.data_base64, self.bundled_path, self.download_url)) != 1:
            raise ValueError("Exactly one package source required")
        if "/" in self.filename or "\\" in self.filename or ":" in self.filename or self.filename.startswith("."):
            raise ValueError("Package filename must be a basename")
        expected = ".zip" if self.media_type == "application/zip" else ".json"
        if not self.filename.lower().endswith(expected):
            raise ValueError("Package filename and media type disagree")
        if self.data is not None and self.media_type != "application/json":
            raise ValueError("Inline data must be JSON")
        return self


class Resource(Strict):
    metadata: ResourceMetadata
    package: PackageReference


def canonical_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as exc:
        raise CommunityError("资源必须是有效且有界的 JSON。") from exc


def _read_json(data, *, limit=MAX_CATALOG_BYTES):
    if not data or len(data) > limit:
        raise CommunityError("社区目录或分享文件超过大小限制。")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CommunityError("目录存在重复 JSON 字段。")
            result[key] = value
        return result
    try:
        result = json.loads(data.decode("utf-8-sig"), object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(CommunityError("目录不能包含非有限数值。")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, CommunityError):
            raise
        raise CommunityError("请提供有效的 UTF-8 社区目录 JSON。") from exc
    if not isinstance(result, dict):
        raise CommunityError("社区目录须为 JSON 对象。")
    return result


def _now():
    return datetime.now(timezone.utc).isoformat()


def _public_url(url):
    from mathtutor.application.community_fetch import CommunityFetchError, validate_public_url
    try:
        return validate_public_url(url)
    except CommunityFetchError as exc:
        raise CommunityError(str(exc)) from exc


async def _default_fetch(url, *, max_bytes):
    from mathtutor.application.community_fetch import CommunityFetchError, fetch_public_bytes
    try:
        return await fetch_public_bytes(url, max_bytes=max_bytes)
    except CommunityFetchError as exc:
        raise CommunityError(str(exc)) from exc


def _origin(url):
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or 443


def _version(value):
    match = re.fullmatch(_VERSION, value)
    suffix = match[4]
    prerelease = tuple((0, int(part)) if part.isdigit() else (1, part) for part in suffix.split(".")) if suffix else ((2, ""),)
    return int(match[1]), int(match[2]), int(match[3]), prerelease


def _builtin_resources():
    envelope = _read_json((ASSETS / "catalog.json").read_bytes())
    rows = list(envelope["resources"])
    try:
        from mathtutor.extensions.community_plugins import builtin_plugin_packages
    except ModuleNotFoundError as exc:
        if exc.name != "mathtutor.extensions.community_plugins":
            raise
        builtin_plugin_packages = lambda: []
    for package in builtin_plugin_packages():
        permissions = package.get("required_permissions", [])
        metadata = {key: package.get(key, "") for key in ("id", "version", "name", "author", "license", "description", "readme", "changelog")}
        if not isinstance(metadata["changelog"], str):
            metadata["changelog"] = json.dumps(metadata["changelog"], ensure_ascii=False)
        metadata.update(type="plugin", tags=package.get("tags", []), grades=package.get("grades", []),
            permissions=permissions, project_example=True, package_sha256=sha256(canonical_bytes(package)).hexdigest())
        rows.append({"metadata": metadata, "package": {"filename": package["id"] + ".json", "media_type": "application/json", "data": package}})
    return rows


class CommunityService:
    def __init__(self, state, *, data_dir=None, fetcher=None):
        self.state = state
        self.root = (Path(data_dir) if data_dir is not None else state.document_storage.uploads_root().parent) / "community"
        self.fetcher = fetcher or _default_fetch

    def _path(self, owner):
        return self.root / (sha256(str(owner).encode()).hexdigest() + ".json")

    def _load(self, owner):
        path = self._path(owner)
        if not path.exists():
            return {"format": "mathtutor.community-owner.v1", "favorites": [], "history": [], "sources": []}
        try:
            if path.stat().st_size > MAX_OWNER_BYTES:
                raise CommunityError("社区资料状态过大，请先导出并清理自定义源。")
            value = _read_json(path.read_bytes(), limit=MAX_OWNER_BYTES)
            if value.get("format") != "mathtutor.community-owner.v1" or any(not isinstance(value.get(key), list) for key in ("favorites", "history", "sources")):
                raise ValueError
            if not isinstance(value.get("file_imports", []), list) or len(value.get("file_imports", [])) > 1000:
                raise ValueError
            return value
        except (OSError, ValueError) as exc:
            if isinstance(exc, CommunityError):
                raise
            raise CommunityError("社区状态无法读取，原文件已保留，请恢复备份后重试。") from exc

    def _save(self, owner, value):
        data = canonical_bytes(value)
        if len(data) > MAX_OWNER_BYTES:
            raise CommunityError("社区状态超过 64 MiB，请移除不需要的自定义源。")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".community-", dir=self.root)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path(owner))
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    def _local_bytes(self, package):
        if package.get("data") is not None:
            return canonical_bytes(package["data"])
        if package.get("data_base64") is not None:
            try:
                return base64.b64decode(package["data_base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise CommunityError("资源包 Base64 内容无效。") from exc
        if package.get("bundled_path") is not None:
            relative = package["bundled_path"]
            # Imported catalogs can name only assets explicitly shipped in the
            # bundled directory; a relative reference never reads user files.
            allowed = {row["package"].get("bundled_path") for row in _read_json((ASSETS / "catalog.json").read_bytes())["resources"]}
            if relative not in allowed or PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts or "\\" in relative:
                raise CommunityError("目录引用了未随应用打包的资源。")
            return (ASSETS / relative).read_bytes()
        return None

    def _validate_payload(self, resource, data):
        metadata, package = resource["metadata"], resource["package"]
        if len(data) > MAX_UPLOAD_BYTES or sha256(data).hexdigest() != metadata["package_sha256"]:
            raise CommunityError("资源包大小或 SHA256 校验不通过。")
        if metadata["type"] == "question-pack":
            parse_pack(data, package["filename"])
        else:
            from mathtutor.extensions.community_plugins import validate_package
            payload = _read_json(data, limit=MAX_UPLOAD_BYTES)
            try:
                plugin = validate_package(payload).model_dump()
            except ValueError as exc:
                raise CommunityError("插件清单不符合支持的声明式格式。") from exc
            if plugin["id"] != metadata["id"] or plugin["version"] != metadata["version"]:
                raise CommunityError("插件 ID 或版本与目录不一致。")
            if sorted(plugin.get("required_permissions", [])) != sorted(metadata.get("permissions", [])):
                raise CommunityError("插件权限与目录预览不一致。")

    def _parse_catalog(self, data, *, source_url=None, share=False):
        envelope = _read_json(data, limit=MAX_SHARE_BYTES if share else MAX_CATALOG_BYTES)
        if envelope.get("format") == RESOURCE_FORMAT:
            if set(envelope) != {"format", "resource"}:
                raise CommunityError("分享资源字段不正确。")
            records, name = [envelope["resource"]], "导入的分享资源"
        elif envelope.get("format") == CATALOG_FORMAT:
            if len(data) > MAX_CATALOG_BYTES:
                raise CommunityError("社区目录 JSON 最多 8 MiB。")
            if set(envelope) - {"format", "name", "resources"} or not isinstance(envelope.get("resources"), list):
                raise CommunityError("社区目录字段不正确。")
            records, name = envelope["resources"], envelope.get("name", "自定义资源目录")
        else:
            raise CommunityError("不支持此社区目录或分享资源版本。")
        if not isinstance(name, str) or not name.strip() or len(name) > 120 or not 1 <= len(records) <= 100:
            raise CommunityError("目录须有名称，且包含 1–100 个资源版本。")
        result, seen = [], set()
        for row in records:
            try:
                resource = Resource.model_validate(row).model_dump(exclude_none=True)
            except ValidationError as exc:
                raise CommunityError("资源元数据或包位置格式无效。") from exc
            metadata, package = resource["metadata"], resource["package"]
            key = metadata["id"], metadata["version"]
            if key in seen:
                raise CommunityError("同一资源版本在目录中重复。")
            seen.add(key)
            if package.get("download_url") is not None:
                if source_url is None:
                    raise CommunityError("离线目录不能引用远程包；请订阅公开目录源。")
                package["download_url"] = _public_url(urljoin(source_url, package["download_url"]))
                if _origin(package["download_url"]) != _origin(source_url):
                    raise CommunityError("资源包须与目录源位于同一公开 HTTPS origin。")
            local = self._local_bytes(package)
            if local is not None:
                self._validate_payload(resource, local)
            result.append(resource)
        return name.strip(), result

    def _sources(self, owner_data):
        builtin = {"id": "builtin", "name": "MathTutor 项目示例", "kind": "builtin", "source_url": None,
                   "sha256": sha256(canonical_bytes(_builtin_resources())).hexdigest(), "last_refreshed": None,
                   "error": None, "stale": False, "resources": _builtin_resources()}
        return [builtin, *owner_data["sources"]]

    @staticmethod
    def _source_public(source):
        return {key: source.get(key) for key in ("id", "name", "kind", "source_url", "sha256", "last_refreshed", "error", "stale")} | {"resource_count": len(source["resources"])}

    def sources(self, owner):
        return {"sources": [self._source_public(source) for source in self._sources(self._load(owner))]}

    def _entries(self, data):
        result = {}
        for source in self._sources(data):
            for entry in source["resources"]:
                key = entry["metadata"]["id"], entry["metadata"]["version"]
                if key not in result:
                    result[key] = (entry, source)
        return result

    def _entry(self, data, resource_id, version=None):
        choices = [(key, value) for key, value in self._entries(data).items() if key[0] == resource_id and (version is None or key[1] == version)]
        if not choices:
            raise CommunityError("资源版本不存在，请刷新目录后重新选择。")
        return max(choices, key=lambda item: _version(item[0][1]))[1]

    def _public_resource(self, owner, data, entry, source):
        metadata = dict(entry["metadata"])
        metadata["project_example"] = source["kind"] == "builtin"
        for field in ("project_url", "issues_url", "discussions_url"):
            metadata.setdefault(field, None)
        records = [record for record in data["history"] if record["resource_id"] == metadata["id"]]
        plugin = None
        if metadata["type"] == "plugin" and getattr(self.state, "community_plugins", None) is not None:
            plugin = next((item for item in self.state.community_plugins.list_installed(owner) if item["plugin"]["id"] == metadata["id"]), None)
        versions_ = list(dict.fromkeys(record["version"] for record in records))
        if plugin and plugin["plugin"]["version"] not in versions_:
            versions_.append(plugin["plugin"]["version"])
        latest = max(versions_, key=_version) if versions_ else None
        installed_version = plugin["plugin"]["version"] if plugin else None
        # History remains truthful after uninstall, while update status follows
        # the plugin that is actually installed (possibly an older rollback).
        current_version = installed_version if metadata["type"] == "plugin" else latest
        status = "not_imported"
        if current_version:
            status = "update_available" if _version(metadata["version"]) > _version(current_version) else "current"
            imported = next((record for record in reversed(records) if record["version"] == metadata["version"]), None)
            if status == "current" and imported and imported["package_sha256"] != metadata["package_sha256"]:
                status = "different_content"
        local = self._local_bytes(entry["package"])
        return {**metadata, "plugin_id": metadata["id"] if metadata["type"] == "plugin" else None,
            "source_id": source["id"], "source_name": source["name"], "source_url": source.get("source_url"),
            "favorite": metadata["id"] in data["favorites"], "imported_versions": versions_, "latest_imported_version": latest,
            "installed_version": installed_version,
            "update_status": status, "package_size_bytes": len(local) if local is not None else None, "importable": True}

    def catalog(self, owner, *, q="", type=None, stage=None, favorites_only=False):
        if type not in {None, "question-pack", "plugin"} or stage not in {None, "primary", "middle", "high"} or len(q) > 200:
            raise CommunityError("搜索、资源类型或学段无效。")
        data, latest = self._load(owner), {}
        for entry, source in self._entries(data).values():
            rid = entry["metadata"]["id"]
            if rid not in latest or _version(entry["metadata"]["version"]) > _version(latest[rid][0]["metadata"]["version"]):
                latest[rid] = entry, source
        result = []
        for entry, source in latest.values():
            item = self._public_resource(owner, data, entry, source)
            if type and item["type"] != type or favorites_only and not item["favorite"]:
                continue
            if q.casefold() not in " ".join([item["name"], item["description"], item["author"], *item["tags"]]).casefold():
                continue
            if stage and item["grades"] and not set(item["grades"]) & set({"primary": range(1, 7), "middle": range(7, 10), "high": range(10, 13)}[stage]):
                continue
            result.append(item)
        return {"resources": sorted(result, key=lambda row: (row["type"], row["name"], row["id"])),
            **self.sources(owner), "notice": "导入喜欢的题库和插件，整理成自己的学习工具。项目示例已明确标注。"}

    def detail(self, owner, resource_id, *, version=None):
        data = self._load(owner)
        entry, source = self._entry(data, resource_id, version)
        public = self._public_resource(owner, data, entry, source)
        content = self._local_bytes(entry["package"])
        preview = {"available": content is not None, "documents": [], "partial": False}
        if content is not None:
            self._validate_payload(entry, content)
            if public["type"] == "question-pack":
                notes = parse_pack(content, entry["package"]["filename"]).notes
                preview["documents"] = [{"path": note.path, "title": note.title, "body": note.body[:4000]} for note in notes[:3]]
                preview["partial"] = len(notes) > 3 or any(len(note.body) > 4000 for note in notes[:3])
            else:
                preview["documents"] = [{"path": "README.md", "title": public["name"], "body": public["readme"]}]
        return {**public, "preview": preview}

    def favorite(self, owner, resource_id, favorite):
        if type(favorite) is not bool:
            raise CommunityError("收藏状态无效。")
        data = self._load(owner)
        self._entry(data, resource_id)
        data["favorites"] = [rid for rid in data["favorites"] if rid != resource_id]
        if favorite:
            data["favorites"].append(resource_id)
        self._save(owner, data)
        return self.detail(owner, resource_id)

    def _check_conflicts(self, data, entries, *, replacing=None):
        existing = self._entries({**data, "sources": [source for source in data["sources"] if source["id"] != replacing]})
        for entry in entries:
            key = entry["metadata"]["id"], entry["metadata"]["version"]
            if key in existing and canonical_bytes(existing[key][0]["metadata"]) != canonical_bytes(entry["metadata"]):
                raise CommunityError("同一资源版本已有不同内容或元数据；发布修改须增加版本号。")

    def import_source(self, owner, data):
        name, entries = self._parse_catalog(data, share=True)
        current = self._load(owner)
        digest = sha256(data).hexdigest()
        old = next((source for source in current["sources"] if source["kind"] == "imported" and source["sha256"] == digest), None)
        if old:
            return self._source_public(old)
        self._check_conflicts(current, entries)
        if len(current["sources"]) >= 32:
            raise CommunityError("最多保存 32 个自定义目录源。")
        source = {"id": "source-" + uuid4().hex, "name": name, "kind": "imported", "source_url": None,
            "sha256": digest, "last_refreshed": _now(), "error": None, "stale": False, "resources": entries}
        current["sources"].append(source)
        self._save(owner, current)
        return self._source_public(source)

    def subscribe(self, owner, name, url):
        if not name.strip() or len(name) > 120:
            raise CommunityError("源名称须为 1–120 字。")
        url = _public_url(url)
        current = self._load(owner)
        existing = next((source for source in current["sources"] if source.get("source_url") == url), None)
        if existing:
            return self._source_public(existing)
        if len(current["sources"]) >= 32:
            raise CommunityError("最多保存 32 个自定义目录源。")
        source = {"id": "source-" + uuid4().hex, "name": name.strip(), "kind": "remote", "source_url": url,
            "sha256": None, "last_refreshed": None, "error": None, "stale": True, "resources": []}
        current["sources"].append(source)
        self._save(owner, current)
        return self._source_public(source)

    async def refresh(self, owner, source_id):
        current = self._load(owner)
        source = next((item for item in current["sources"] if item["id"] == source_id), None)
        if source is None or source["kind"] != "remote":
            raise CommunityError("可刷新的远程目录源不存在。")
        try:
            raw = await self.fetcher(source["source_url"], max_bytes=MAX_CATALOG_BYTES)
            _, entries = self._parse_catalog(raw, source_url=source["source_url"])
            self._check_conflicts(current, entries, replacing=source_id)
            # A previously cached version is immutable even when this is the
            # only source carrying it. Updates must publish a new version.
            old = {(item["metadata"]["id"], item["metadata"]["version"]): item for item in source["resources"]}
            for entry in entries:
                key = entry["metadata"]["id"], entry["metadata"]["version"]
                if key in old and canonical_bytes(old[key]["metadata"]) != canonical_bytes(entry["metadata"]):
                    raise CommunityError("源修改了已缓存版本的内容；请发布新版本。")
            source.update(resources=entries, sha256=sha256(raw).hexdigest(), last_refreshed=_now(), stale=False, error=None)
        except (CommunityError, ValueError, OSError) as exc:
            source.update(stale=True, error=str(exc) if isinstance(exc, CommunityError) else "资源源刷新失败，已保留上次缓存。")
        self._save(owner, current)
        return self._source_public(source)

    def remove_source(self, owner, source_id):
        current = self._load(owner)
        retained = [source for source in current["sources"] if source["id"] != source_id]
        if len(retained) == len(current["sources"]):
            raise CommunityError("自定义目录源不存在。")
        current["sources"] = retained
        remaining_ids = {resource_id for resource_id, _ in self._entries(current)}
        current["favorites"] = [resource_id for resource_id in current["favorites"] if resource_id in remaining_ids]
        self._save(owner, current)
        return {"deleted": True}

    async def _package(self, entry):
        content = self._local_bytes(entry["package"])
        if content is None:
            limit = 65536 if entry["metadata"]["type"] == "plugin" else MAX_UPLOAD_BYTES
            content = await self.fetcher(entry["package"]["download_url"], max_bytes=limit)
        self._validate_payload(entry, content)
        return content

    async def import_resource(self, owner, resource_id, *, version, expected_sha256, operation_id=None):
        current = self._load(owner)
        if operation_id and any(record.get("operation_id") == operation_id for record in current.get("file_imports", [])):
            raise CommunityError("重复导入请求内容不一致，请重新选择文件。")
        entry, source = self._entry(current, resource_id, version)
        metadata = entry["metadata"]
        if expected_sha256 != metadata["package_sha256"]:
            raise CommunityError("资源版本或包内容已变化，请重新查看详情后再导入。")
        if operation_id:
            replay = next((record for record in current["history"] if record.get("operation_id") == operation_id), None)
            if replay:
                if (replay["resource_id"], replay["version"], replay["package_sha256"]) != (resource_id, version, expected_sha256):
                    raise CommunityError("重复导入请求内容不一致。")
                return replay["result"]
        if len(current["history"]) >= 1000:
            raise CommunityError("已达到本地导入历史上限，请先导出社区状态。")
        content = await self._package(entry)
        existing_ids = None
        if metadata["type"] == "question-pack":
            existing_ids = {str(doc.document_id) for doc in await self.state.documents.list_documents(owner)}
            imported = await QuestionPackService(self.state).import_pack(owner, content, entry["package"]["filename"], name=metadata["name"])
            result = {"resource_id": resource_id, "version": version, **imported}
        else:
            service = getattr(self.state, "community_plugins", None)
            if service is None:
                raise CommunityError("当前运行环境尚未提供社区插件服务。")
            plugin = service.import_package(owner, _read_json(content, limit=MAX_UPLOAD_BYTES))
            result = {"resource_id": resource_id, "version": version, "plugin": plugin, "warnings": ["插件已导入；启用和权限授权需另行确认。"]}
        current["history"].append({"id": uuid4().hex, "resource_id": resource_id, "version": version,
            "name": metadata["name"], "type": metadata["type"], "source_name": source["name"],
            "package_sha256": expected_sha256, "source_id": source["id"], "imported_at": _now(),
            "operation_id": operation_id, "space_id": result.get("space_id"), "result": result})
        try:
            self._save(owner, current)
        except (OSError, CommunityError) as exc:
            if existing_ids is not None:
                try:
                    await QuestionPackService(self.state).rollback_import(owner, result["space_id"], existing_ids)
                except Exception:
                    raise CommunityError("社区历史保存失败，个人副本清理未完成；请到知识库检查，避免重复导入。") from exc
                raise CommunityError("社区历史保存失败，本次新建题库副本已撤回，原有资料保持不变。") from exc
            # Plugin installation has already succeeded in its own durable
            # store and same-package installation is idempotent. Report that
            # actual result, rather than pretending nothing was installed.
            return {**result, "history_recorded": False, "warnings": [*result.get("warnings", []),
                "插件安装成功，但社区导入历史未能保存；请以已安装插件列表为准。"]}
        return result

    async def import_file(self, owner, data, filename, *, operation_id=None):
        """Import a downloaded package in one explicit, owner-scoped action.

        Friendly extensions are presentation only. Bytes select the original
        validated package protocol; no uploaded content is executed. File
        receipts share the community store and compensate only a newly-created
        library if their durable write fails, rather than claiming a transaction
        across the file and database stores.
        """
        if not data or len(data) > MAX_SHARE_BYTES:
            raise CommunityError("请选择非空的分享文件，最大 32 MiB。")
        if operation_id is not None and (not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 128):
            raise CommunityError("导入请求无效，请重新选择文件。")
        current, digest = self._load(owner), sha256(data).hexdigest()
        if operation_id:
            replay = next((row for row in current.get("file_imports", []) if row["operation_id"] == operation_id), None)
            if replay:
                if replay["sha256"] != digest:
                    raise CommunityError("重复导入请求内容不一致，请重新选择文件。")
                return replay["result"]
        archive = data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
        payload = None
        if not archive:
            try:
                payload = _read_json(data, limit=MAX_SHARE_BYTES)
            except CommunityError as exc:
                raise CommunityError("暂不支持此文件。请选择下载的 MathTutor 插件、题库或笔记压缩包。") from exc
        format_name = payload.get("format") if payload is not None else None
        if format_name == RESOURCE_FORMAT:
            # Finish all metadata/hash/payload validation before adding a source
            # or consulting resource IDs. An upload cannot refer to another
            # owner's private source or borrow its cached package bytes.
            _, entries = self._parse_catalog(data, share=True)
            metadata = entries[0]["metadata"]
            previous = next((row for row in current["history"] if operation_id and row.get("operation_id") == operation_id), None)
            if previous and (previous["resource_id"], previous["version"], previous["package_sha256"]) != (
                    metadata["id"], metadata["version"], metadata["package_sha256"]):
                raise CommunityError("重复导入请求内容不一致，请重新选择文件。")
            self.import_source(owner, data)
            result = await self.import_resource(owner, metadata["id"], version=metadata["version"],
                expected_sha256=metadata["package_sha256"], operation_id=operation_id)
            return {"kind": metadata["type"], **result}
        if operation_id and any(row.get("operation_id") == operation_id for row in current["history"]):
            raise CommunityError("重复导入请求内容不一致，请重新选择文件。")
        if operation_id and len(current.get("file_imports", [])) >= 1000:
            raise CommunityError("本地导入记录已满，请先备份并清理社区记录。")
        existing_ids = None
        if format_name == CATALOG_FORMAT:
            result = {"kind": "source", "source": self.import_source(owner, data),
                "warnings": ["资源来源已添加，可在高级选项中查看；其中的题库和插件尚未导入。"]}
            current = self._load(owner)
        elif payload is not None and (payload.get("schema_version") == "mathtutor.community-plugin.v1"
                or payload.get("kind") == "teaching-plugin" or "workflow" in payload):
            service = getattr(self.state, "community_plugins", None)
            if service is None:
                raise CommunityError("当前运行环境尚未提供社区插件服务。")
            try:
                plugin = service.import_package(owner, payload)
            except ValueError as exc:
                raise CommunityError("插件文件不受支持，请重新下载完整文件，并确认版本及所需权限。") from exc
            result = {"kind": "plugin", "plugin": plugin,
                "warnings": ["插件已导入；首次使用前，请在插件列表中查看并同意所需权限。"]}
        elif archive or format_name == QUESTION_FORMAT:
            # The existing importer selects a parser by filename. Map the
            # detected byte format back to its original suffix, so renaming a
            # downloaded .json/.zip to .mathtutor never changes its semantics.
            basename = PurePosixPath(str(filename or "分享资料").replace("\\", "/")).stem
            original_name = (basename[:100] or "分享资料") + (".zip" if archive else ".json")
            parse_pack(data, original_name)
            existing_ids = {str(doc.document_id) for doc in await self.state.documents.list_documents(owner)}
            imported = await QuestionPackService(self.state).import_pack(owner, data, original_name)
            result = {"kind": "question-pack", **imported}
        else:
            raise CommunityError("暂不支持此文件。请选择下载的 MathTutor 插件、题库或笔记压缩包。")
        if not operation_id:
            return result
        current.setdefault("file_imports", []).append({"operation_id": operation_id, "sha256": digest,
            "imported_at": _now(), "result": result})
        try:
            self._save(owner, current)
        except (OSError, CommunityError) as exc:
            if existing_ids is not None:
                try:
                    await QuestionPackService(self.state).rollback_import(owner, result["space_id"], existing_ids)
                except Exception:
                    raise CommunityError("导入记录保存失败，个人副本清理未完成；请到知识库检查，避免重复导入。") from exc
                raise CommunityError("导入记录保存失败，本次新建题库副本已撤回，原有资料保持不变。") from exc
            return {**result, "history_recorded": False, "warnings": [*result.get("warnings", []),
                "文件已导入，但重复导入保护记录未能保存；请以插件列表或资源来源列表为准。"]}
        return result

    def history(self, owner):
        return {"imports": [{key: value for key, value in record.items() if key not in {"operation_id", "result"}} for record in reversed(self._load(owner)["history"])]}

    async def export_resource(self, owner, resource_id, *, version=None, expected_sha256=None):
        current = self._load(owner)
        entry, _ = self._entry(current, resource_id, version)
        if expected_sha256 is not None and expected_sha256 != entry["metadata"]["package_sha256"]:
            raise CommunityError("资源内容已变化，请重新查看详情。")
        content = await self._package(entry)
        # Raw bytes preserve externally declared hashes even if their JSON
        # whitespace differs from our canonical inline JSON representation.
        exported = {"metadata": entry["metadata"], "package": {"filename": entry["package"]["filename"],
            "media_type": entry["package"]["media_type"], "data_base64": base64.b64encode(content).decode("ascii")}}
        return canonical_bytes({"format": RESOURCE_FORMAT, "resource": exported})

    async def publish_library(self, owner, sid, metadata):
        metadata = {**metadata, "type": "question-pack"}
        package = await QuestionPackService(self.state).export_library(owner, sid)
        metadata["package_sha256"] = sha256(package).hexdigest()
        try:
            validated = ResourceMetadata.model_validate(metadata).model_dump(exclude_none=True)
        except ValidationError as exc:
            raise CommunityError("分享资源的作者、许可、版本或其他元数据无效。") from exc
        resource = {"metadata": validated, "package": {"filename": "learning-vault.zip", "media_type": "application/zip",
            "data_base64": base64.b64encode(package).decode("ascii")}}
        return canonical_bytes({"format": RESOURCE_FORMAT, "resource": resource})

    def export_owner_data(self, owner):
        return self._load(owner)

    def delete_owner_data(self, owner):
        self._path(owner).unlink(missing_ok=True)
        return {"deleted": True}
