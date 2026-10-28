"""Explicitly imported reference packs and editable Markdown vaults.

Nothing in an archive is extracted or executed. Parsing finishes before the
first database write. Imports use ordinary versioned user documents and never
mount a library, release official exercises, or write learning evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import io
import json
from pathlib import PurePosixPath
import stat
from uuid import uuid4
import zipfile
import zlib

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, or_, select

from mathtutor.application.knowledge import KnowledgeError, library_aliases, vault_path_key
from mathtutor.infrastructure.document_storage import sanitize_filename
from mathtutor.infrastructure.knowledge_schema import members, operations, spaces, versions
from mathtutor.infrastructure.schema import (
    conversation_documents, document_chunks, document_chunk_vectors, document_index_builds, user_documents,
)

QUESTION_FORMAT = "mathtutor.question-pack.v1"
VAULT_FORMAT = "mathtutor.vault.v1"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_MARKDOWN_BYTES = 1024 * 1024
MAX_FILES = 1000
MAX_ARCHIVE_ENTRIES = 4000
REFERENCE_NOTICE = "用户提供的参考答案，未经应用自动数学核验；不作为学习掌握度证据。"


class QuestionPackError(KnowledgeError):
    pass


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SharedQuestion(Strict):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(default="", max_length=120)
    stem: str = Field(min_length=1, max_length=16000)
    answer: str = Field(min_length=1, max_length=16000)
    explanation: str = Field(default="", max_length=24000)
    grade: int | None = Field(default=None, ge=1, le=12)
    tags: list[str] = Field(default_factory=list, max_length=32)


class SharedQuestionPack(Strict):
    format: str
    name: str = Field(min_length=1, max_length=120)
    author: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=4000)
    questions: list[SharedQuestion] = Field(min_length=1, max_length=MAX_FILES)


class VaultFile(Strict):
    path: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=32)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_format: str = Field(default="markdown", max_length=40)


class VaultManifest(Strict):
    format: str
    name: str = Field(min_length=1, max_length=120)
    files: list[VaultFile] = Field(min_length=1, max_length=MAX_FILES)


@dataclass(frozen=True)
class ImportedNote:
    path: str
    title: str
    body: str
    tags: tuple[str, ...] = ()
    provenance: dict | None = None


@dataclass(frozen=True)
class ParsedPack:
    name: str
    format: str
    notes: tuple[ImportedNote, ...]
    warnings: tuple[str, ...] = ()


def _json(data):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise QuestionPackError("JSON 存在重复字段。")
            result[key] = value
        return result
    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(QuestionPackError("JSON 不允许非有限数值。")))
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, QuestionPackError):
            raise
        raise QuestionPackError("文件必须是有效的 UTF-8 JSON。") from exc


def _tags(values):
    if not isinstance(values, (list, tuple)) or len(values) > 32 or any(not isinstance(x, str) or not x.strip() or len(x) > 64 for x in values):
        raise QuestionPackError("标签必须为 1–64 字的文字，最多 32 个。")
    return tuple(dict.fromkeys(values))


def _path(value, *, directory=False):
    if not isinstance(value, str) or not value or len(value) > 512 or "\\" in value or "\x00" in value:
        raise QuestionPackError("资料包包含无效或越界路径。")
    if any(ord(char) < 32 for char in value) or value.startswith("/") or ":" in value:
        raise QuestionPackError("资料包包含绝对路径或无效路径。")
    trimmed = value[:-1] if directory and value.endswith("/") else value
    if any(part in {"", ".", ".."} for part in trimmed.split("/")):
        raise QuestionPackError("资料包包含无效或越界路径。")
    return trimmed


def _key(path):
    return vault_path_key(path)


def _note(path, title, body, tags=(), provenance=None):
    _path(path)
    if PurePosixPath(path).suffix.lower() not in {".md", ".markdown", ".txt"}:
        raise QuestionPackError("资料文件必须是 Markdown 或 TXT 文本。")
    if not isinstance(body, str) or not body.strip() or "\x00" in body or len(body.encode("utf-8")) > MAX_MARKDOWN_BYTES:
        raise QuestionPackError("Markdown 须有正文、不能含二进制内容，单份最多 1 MiB。")
    if not title.strip() or len(title) > 120:
        raise QuestionPackError("资料标题须为 1–120 字。")
    return ImportedNote(path, title, body, _tags(tags), provenance or {})


def _question_pack(data):
    try:
        pack = SharedQuestionPack.model_validate(_json(data))
    except ValidationError as exc:
        raise QuestionPackError("题库格式不正确：请检查字段、题目数量、年级和文字长度。") from exc
    if pack.format != QUESTION_FORMAT or not pack.name.strip():
        raise QuestionPackError("不支持此题库版本或题库名称为空。")
    seen, notes = set(), []
    for index, question in enumerate(pack.questions, 1):
        if not question.id.strip() or _key(question.id) in seen:
            raise QuestionPackError("题目 ID 不能为空或重复。")
        if not question.stem.strip() or not question.answer.strip():
            raise QuestionPackError("题干和参考答案不能为空。")
        seen.add(_key(question.id))
        title = (question.title.strip() or f"题目 {question.id}")[:120]
        path = f"questions/{index:04d}-{sanitize_filename(title)[:100]}.md"
        lines = [f"# {title}", "", f"> {REFERENCE_NOTICE}", "", f"题目编号：{question.id}"]
        if pack.author:
            lines.append(f"来源作者：{pack.author}")
        if question.grade is not None:
            lines.append(f"年级：{question.grade}")
        lines.extend(["", "## 题干", "", question.stem, "", "## 用户参考答案", "", question.answer])
        if question.explanation:
            lines.extend(["", "## 参考讲解", "", question.explanation])
        notes.append(_note(path, title, "\n".join(lines) + "\n", question.tags, {
            "pack_format": QUESTION_FORMAT, "author": pack.author, "description": pack.description,
            "question_id": question.id, "grade": question.grade, "answer_verified": False,
        }))
    return ParsedPack(pack.name.strip(), QUESTION_FORMAT, tuple(notes), (REFERENCE_NOTICE,))


def _zip_pack(data, filename):
    warnings, entries, total, seen = [], {}, 0, set()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        with archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise QuestionPackError("压缩包条目过多。")
            for info in infos:
                if info.orig_filename != info.filename:
                    raise QuestionPackError("压缩包包含截断或无效文件路径。")
                path = _path(info.filename, directory=info.is_dir())
                key = _key(path)
                if key in seen:
                    raise QuestionPackError("压缩包存在重复文件路径（含大小写冲突）。")
                seen.add(key)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                    raise QuestionPackError("压缩包不允许符号链接或特殊文件。")
                if info.flag_bits & 1:
                    raise QuestionPackError("不支持加密压缩包。")
                if info.is_dir():
                    continue
                total += info.file_size
                if total > MAX_EXPANDED_BYTES or info.file_size > MAX_MARKDOWN_BYTES:
                    raise QuestionPackError("压缩包展开后超出大小限制。")
                # Even skipped members count toward expansion/ratio limits.
                if info.file_size > 65536 and info.file_size > max(1, info.compress_size) * 200:
                    raise QuestionPackError("压缩包压缩比例异常，请分批导入。")
                hidden = any(part.startswith(".") or part == "__MACOSX" for part in path.split("/"))
                if hidden:
                    warnings.append(f"已跳过隐藏配置：{path}")
                    continue
                if path != "manifest.json" and PurePosixPath(path).suffix.lower() not in {".md", ".markdown", ".txt"}:
                    warnings.append(f"已跳过非 Markdown/TXT 文件：{path}")
                    continue
                with archive.open(info) as source:
                    content = source.read(MAX_MARKDOWN_BYTES + 1)
                if len(content) > MAX_MARKDOWN_BYTES or len(content) != info.file_size:
                    raise QuestionPackError("压缩包文件大小不一致或超出限制。")
                entries[path] = content
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise QuestionPackError("压缩包损坏、加密或使用了不支持的格式。") from exc
    markdown = {path: value for path, value in entries.items() if path != "manifest.json"}
    if not markdown or len(markdown) > MAX_FILES:
        raise QuestionPackError("请提供 1–1000 份 Markdown 文档。")
    metadata = {}
    name = PurePosixPath(filename.replace("\\", "/")).stem[:120].strip() or "导入的学习资料"
    format_name = "obsidian-markdown"
    if "manifest.json" in entries:
        manifest = _json(entries["manifest.json"])
        if isinstance(manifest, list):
            # Existing KnowledgeService.export(): <document-id>-<title>.md.
            for row in manifest:
                if not isinstance(row, dict) or not isinstance(row.get("document_id"), str) or not isinstance(row.get("title"), str):
                    raise QuestionPackError("旧版知识库清单无效。")
                path = row["document_id"] + "-" + sanitize_filename(row["title"]).removesuffix(".md") + ".md"
                _path(path)
                if path not in markdown or path in metadata:
                    raise QuestionPackError("旧版知识库清单与文件不一致。")
                metadata[path] = {"title": row["title"], "tags": row.get("tags", []), "source_format": "markdown"}
            if set(metadata) != set(markdown):
                raise QuestionPackError("旧版知识库清单与文件不一致。")
            format_name = "mathtutor.legacy-knowledge"
        else:
            try:
                parsed = VaultManifest.model_validate(manifest)
            except ValidationError as exc:
                raise QuestionPackError("资料库清单格式不正确。") from exc
            if parsed.format != VAULT_FORMAT or not parsed.name.strip():
                raise QuestionPackError("不支持此资料库版本。")
            name, format_name = parsed.name.strip(), VAULT_FORMAT
            for item in parsed.files:
                _path(item.path)
                if item.path in metadata or item.path not in markdown or sha256(markdown[item.path]).hexdigest() != item.sha256:
                    raise QuestionPackError("资料库清单与文件或 SHA256 不一致。")
                metadata[item.path] = item.model_dump()
            if set(metadata) != set(markdown):
                raise QuestionPackError("资料库清单与文件不一致。")
    notes = []
    for path, content in markdown.items():
        try:
            body = content.decode("utf-8-sig")
        except UnicodeError as exc:
            raise QuestionPackError("Markdown 必须使用 UTF-8 编码。") from exc
        item = metadata.get(path, {})
        title = item.get("title") or PurePosixPath(path).name[:120]
        notes.append(_note(path, title, body, item.get("tags", []), {
            "pack_format": format_name, "source_format": item.get("source_format", "text" if PurePosixPath(path).suffix.lower() == ".txt" else "markdown"),
        }))
    if any(PurePosixPath(note.path).name.casefold() == "skill.md" for note in notes):
        warnings.append("SKILL.md 仅作为普通 Markdown 参考资料导入，不会启用技能或插件。")
    return ParsedPack(name, format_name, tuple(notes), tuple(warnings))


def parse_pack(data: bytes, filename: str, *, name="") -> ParsedPack:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise QuestionPackError("资料包不能为空，最大 20 MiB。")
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.casefold()
    if suffix == ".json":
        pack = _question_pack(data)
    elif suffix == ".zip":
        pack = _zip_pack(data, filename)
    else:
        raise QuestionPackError("请选择题库 JSON 或 Markdown ZIP 资料包。")
    if name:
        if not name.strip() or len(name) > 120:
            raise QuestionPackError("知识库名称须为 1–120 字。")
        pack = ParsedPack(name.strip(), pack.format, pack.notes, pack.warnings)
    if sum(len(note.body.encode("utf-8")) for note in pack.notes) > MAX_EXPANDED_BYTES:
        raise QuestionPackError("资料包正文总大小超过 32 MiB。")
    return pack


class QuestionPackService:
    def __init__(self, state):
        self.state, self.knowledge = state, state.knowledge

    async def import_pack(self, owner, data, filename, *, name=""):
        pack = parse_pack(data, filename, name=name)
        # Snapshot only identities: cancellation/failure cleanup must never
        # remove a document reused from another pre-existing library.
        existing_ids = {str(d.document_id) for d in await self.state.documents.list_documents(owner)}
        library = await self.knowledge.create_space(owner, pack.name, kind="course")
        sid, operation_prefix = library["space_id"], "pack-" + uuid4().hex + "-"
        aliases = {}
        try:
            for index, note in enumerate(pack.notes):
                result = await self.knowledge.save_markdown(owner, sid, title=note.title, body=note.body,
                    tags=list(note.tags), operation_id=f"{operation_prefix}{index}", provenance={
                        **(note.provenance or {}), "origin": "shared_reference", "relative_path": note.path,
                    })
                aliases.setdefault(result["document_id"], []).append({"path": note.path, "title": note.title, "tags": list(note.tags)})
        except BaseException:
            await self._cleanup(owner, sid, existing_ids, operation_prefix)
            raise
        warnings = list(pack.warnings)
        if len(aliases) != len(pack.notes) or any(did in existing_ids for did in aliases):
            warnings.append("相同正文复用了已有资料；本库文件路径已保留，编辑同一资料会更新所有引用它的库。")
        return {"space_id": sid, "name": pack.name, "imported_count": len(pack.notes),
                "input_file_count": len(pack.notes), "unique_body_count": len(aliases),
                "retained_path_count": len(pack.notes), "created_document_count": len(set(aliases) - existing_ids),
                "warnings": warnings, "format": pack.format}

    async def rollback_import(self, owner, sid, existing_ids):
        """Undo only a just-created import when a coordinating store fails.

        The caller captures existing document identities before import. No
        owner-wide generation bump or deletion of unrelated drafts occurs.
        """
        await self.knowledge.require_space(owner, sid)
        await self._cleanup(owner, sid, set(existing_ids), None)

    async def _cleanup(self, owner, sid, existing_ids, prefix):
        """Compensate this new library only; do not revoke unrelated drafts."""
        storage_refs = []
        async with self.knowledge.engine.begin() as db:
            ids = list((await db.execute(select(members.c.document_id).where(
                members.c.student_id == owner, members.c.space_id == sid))).scalars())
            await db.execute(delete(members).where(members.c.student_id == owner, members.c.space_id == sid))
            imported_operations = operations.c.payload["space_id"].as_string() == sid
            if prefix is not None:
                imported_operations = or_(imported_operations, operations.c.operation_id.like(prefix + "%"))
            await db.execute(delete(operations).where(operations.c.student_id == owner, imported_operations))
            await db.execute(delete(spaces).where(spaces.c.student_id == owner, spaces.c.space_id == sid))
            for did in ids:
                if did in existing_ids:
                    current = (await db.execute(select(versions).where(versions.c.student_id == owner,
                        versions.c.document_id == did).order_by(versions.c.version.desc()).limit(1))).mappings().first()
                    if current and sid in current["provenance"].get("vault_paths", {}):
                        provenance = dict(current["provenance"])
                        provenance["vault_paths"] = {key: value for key, value in provenance["vault_paths"].items() if key != sid}
                        if not provenance["vault_paths"]:
                            provenance.pop("vault_paths")
                        await db.execute(versions.update().where(versions.c.student_id == owner,
                            versions.c.document_id == did, versions.c.version == current["version"]).values(provenance=provenance))
                    continue
                retained = (await db.execute(select(members.c.document_id).where(members.c.student_id == owner,
                    members.c.document_id == did).limit(1))).first()
                attached = (await db.execute(select(conversation_documents.c.document_id).where(
                    conversation_documents.c.student_id == owner, conversation_documents.c.document_id == did).limit(1))).first()
                doc = (await db.execute(select(user_documents).where(user_documents.c.student_id == owner,
                    user_documents.c.document_id == did))).mappings().first()
                if retained or attached or not doc or doc["is_global"]:
                    continue
                storage_refs.append(doc["storage_ref"])
                for table in (document_chunk_vectors, document_index_builds, document_chunks, versions, user_documents):
                    await db.execute(delete(table).where(table.c.student_id == owner, table.c.document_id == did))
        for ref in storage_refs:
            await self.state.document_storage.remove(ref)

    async def export_library(self, owner, sid):
        library = await self.knowledge.require_space(owner, sid)
        notes = await self.knowledge.list_notes(owner, sid)
        if not notes:
            raise QuestionPackError("空知识库没有可导出的 Markdown 资料。")
        files, used, total = [], set(), 0
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for note in notes:
                source = await self.knowledge.snapshot(owner, note["document_id"])
                content = source["body"].encode("utf-8")
                if not source["body"].strip():
                    raise QuestionPackError("知识库含尚未提取到文字的资料，请先处理或移出后再导出 Markdown 资料库。")
                provenance = source["provenance"]
                aliases = library_aliases(provenance, sid, source["title"], source["tags"])
                for alias in aliases:
                    path = alias["path"]
                    try:
                        _path(path)
                    except QuestionPackError:
                        path = sanitize_filename(source["title"]).removesuffix(".md") + ".md"
                    if PurePosixPath(path).suffix.lower() not in {".md", ".markdown", ".txt"}:
                        path += ".md"
                    # Reserved/hidden paths are never emitted as trusted vault
                    # entries; imported hidden files were skipped at parse time.
                    if any(part.startswith(".") for part in path.split("/")):
                        path = sanitize_filename(source["title"]).lstrip(".") + ".md"
                    if _key(path) in used or path == "manifest.json":
                        original = PurePosixPath(path)
                        path = str(original.with_name(note["document_id"][:12] + "-" + original.name))
                        index = 2
                        while _key(path) in used:
                            path = str(original.with_name(f"{note['document_id'][:12]}-{index}-{original.name}"))
                            index += 1
                    if len(path) > 512:
                        path = note["document_id"] + "-" + sanitize_filename(source["title"])[:100] + ".md"
                        index = 2
                        while _key(path) in used:
                            path = f"{note['document_id']}-{index}.md"
                            index += 1
                    used.add(_key(path))
                    total += len(content)
                    if len(files) >= MAX_FILES or len(content) > MAX_MARKDOWN_BYTES or total > MAX_EXPANDED_BYTES:
                        raise QuestionPackError("导出超过 1000 份、单份 1 MiB 或合计 32 MiB 限制，请分库导出。")
                    # Highly compressible ordinary notes must still be
                    # re-importable under the archive bomb ratio guard.
                    highly_compressible = len(content) > 65536 and len(content) > max(1, len(zlib.compress(content))) * 180
                    archive.writestr(path, content, compress_type=zipfile.ZIP_STORED if highly_compressible else zipfile.ZIP_DEFLATED)
                    files.append({"path": path, "title": alias["title"], "tags": alias["tags"],
                        "sha256": sha256(content).hexdigest(), "source_format": provenance.get("source_format", provenance.get("format", "extracted"))})
            archive.writestr("manifest.json", json.dumps({"format": VAULT_FORMAT, "name": library["name"], "files": files},
                ensure_ascii=False, indent=2))
        data = output.getvalue()
        if len(data) > MAX_UPLOAD_BYTES:
            raise QuestionPackError("导出压缩包超过可回导的 20 MiB 上限，请分库导出。")
        return data
