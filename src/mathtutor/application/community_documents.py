"""Explicit text/folder imports; validate the entire batch before any write.

The browser supplies relative names and bytes, never a host path to open. A
deterministic, stored ZIP reuses the existing owner receipt/rollback protocol.
Plugins and catalogs are refused during preflight, not after import side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import PurePosixPath
import stat
import unicodedata
import zipfile

from mathtutor.application.community import CATALOG_FORMAT, RESOURCE_FORMAT, CommunityError, _read_json
from mathtutor.application.question_packs import (
    MAX_FILES, MAX_MARKDOWN_BYTES, MAX_UPLOAD_BYTES, QUESTION_FORMAT, QuestionPackError, parse_pack,
)
from mathtutor.infrastructure.document_storage import sanitize_filename

TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt"})
PACK_SUFFIXES = frozenset({".json", ".zip", ".mathtutor"})


@dataclass(frozen=True)
class DocumentUpload:
    filename: str
    data: bytes


def relative_document_path(value: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > 512 or "\\" in value or ":" in value
            or value.startswith("/") or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise CommunityError("文件名须为文件夹内的相对路径，不能包含盘符或越界路径。")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part.startswith(".") or part == "__MACOSX" for part in parts):
        raise CommunityError("不能导入隐藏目录、空路径或越界路径。")
    return value


def _key(path):
    return unicodedata.normalize("NFC", path).casefold()


class CommunityDocumentService:
    def __init__(self, state):
        self.state = state
        self.community = state.community

    def _preflight_pack(self, upload: DocumentUpload) -> None:
        path = relative_document_path(upload.filename)
        suffix = PurePosixPath(path).suffix.casefold()
        if suffix not in PACK_SUFFIXES:
            raise CommunityError("请选择 Markdown、TXT、资料包，或包含文本资料的文件夹；插件请到‘我的插件’导入。")
        if upload.data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            parsed = parse_pack(upload.data, "资料.zip")
        else:
            payload = _read_json(upload.data, limit=MAX_UPLOAD_BYTES)
            if payload.get("format") == QUESTION_FORMAT:
                parsed = parse_pack(upload.data, "题库.json")
            elif payload.get("format") == RESOURCE_FORMAT:
                _, entries = self.community._parse_catalog(upload.data, share=True)
                if len(entries) != 1 or entries[0]["metadata"]["type"] != "question-pack":
                    raise CommunityError("这里仅导入题库和资料，插件请到‘我的插件’导入。")
                entry = entries[0]
                content = self.community._local_bytes(entry["package"])
                if content is None:
                    raise CommunityError("请选择包含完整资料的分享文件。")
                parsed = parse_pack(content, entry["package"]["filename"])
            elif payload.get("format") == CATALOG_FORMAT:
                raise CommunityError("目录来源不能作为个人资料导入，请选择其中的具体题库或资料包。")
            else:
                raise CommunityError("这里仅导入题库和文本资料，插件请到‘我的插件’导入。")
        if sum(len(note.body.encode("utf-8")) for note in parsed.notes) > MAX_UPLOAD_BYTES:
            raise CommunityError("资料正文合计不能超过 20 MiB，请分批导入。")

    def prepare(self, uploads: list[DocumentUpload]) -> DocumentUpload:
        if not uploads or len(uploads) > MAX_FILES:
            raise CommunityError("请选择 1–1000 份资料文件。")
        if any(not isinstance(item.data, bytes) or not item.data for item in uploads):
            raise CommunityError("资料文件不能为空。")
        if sum(len(item.data) for item in uploads) > MAX_UPLOAD_BYTES:
            raise CommunityError("资料文件合计不能超过 20 MiB，请分批导入。")
        if len(uploads) == 1 and PurePosixPath(uploads[0].filename).suffix.casefold() not in TEXT_SUFFIXES:
            self._preflight_pack(uploads[0])
            return uploads[0]
        seen, files = set(), []
        for item in uploads:
            path = relative_document_path(item.filename)
            if PurePosixPath(path).suffix.casefold() not in TEXT_SUFFIXES:
                raise CommunityError("文件夹中仅支持 Markdown 和 TXT 文本，请移除其他文件后重试。")
            key = _key(path)
            if key in seen:
                raise CommunityError("资料中存在重名文件或大小写冲突，请调整后重试。")
            seen.add(key)
            if len(item.data) > MAX_MARKDOWN_BYTES:
                raise CommunityError("每份文本资料最多 1 MiB。")
            try:
                body = item.data.decode("utf-8-sig")
            except UnicodeError as exc:
                raise CommunityError("Markdown 和 TXT 须使用 UTF-8 编码。") from exc
            if not body.strip() or "\x00" in body:
                raise CommunityError("资料须有正文，不能含空字节或二进制内容。")
            files.append((path, item.data))
        # A path must not be both a file and another file's parent. This is
        # metadata only, but preserving an impossible tree would break export.
        for path, _ in files:
            if any(_key(str(parent)) in seen for parent in PurePosixPath(path).parents if str(parent) != "."):
                raise CommunityError("资料路径存在文件与文件夹重名，请调整后重试。")
        common = {path.split("/")[0] for path, _ in files if "/" in path}
        root_name = next(iter(common)) if len(common) == 1 and all("/" in path for path, _ in files) else "导入的学习资料"
        if len(files) == 1:
            root_name = PurePosixPath(files[0][0]).stem
        filename = (sanitize_filename(root_name)[:110] or "学习资料") + ".zip"
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for path, content in sorted(files, key=lambda row: row[0]):
                info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                info.compress_type = zipfile.ZIP_STORED
                archive.writestr(info, content)
        result = DocumentUpload(filename, output.getvalue())
        # Includes ZIP structure overhead in the existing import limit. This
        # final preflight is still before any library or receipt is written.
        self._preflight_pack(result)
        return result

    async def import_files(self, owner: str, uploads: list[DocumentUpload], *, operation_id=None):
        prepared = self.prepare(uploads)
        return await self.community.import_file(owner, prepared.data, prepared.filename, operation_id=operation_id)
