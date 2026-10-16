"""Persistent knowledge built on the product document store, FTS and owner boundary.

Libraries are explicit sets, not alternate identities for conversations. Source
offsets address immutable UTF-8-decoded text versions (Python character offsets).
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import PurePosixPath
import re
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
import zipfile

from sqlalchemy import select, func, delete
from sqlalchemy.dialects.sqlite import insert

from mathtutor.application.rerank import ProductionReranker
from mathtutor.domain.documents import DocumentChunk, UserDocument
from mathtutor.infrastructure.knowledge_schema import spaces, members, bindings, versions, generations, operations, drafts, receipts
from mathtutor.infrastructure.schema import user_documents, document_chunk_vectors, document_index_builds
from mathtutor.infrastructure.document_storage import sanitize_filename
from mathtutor.infrastructure.lexical import tokenize_lexical, build_fts_text
from mathtutor.repositories import sqlite_documents as sd
from mathtutor.security.scopes import student_uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return sha256((value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


class KnowledgeError(ValueError):
    pass


def reference_configuration(value=None):
    """Complete defaults for both old bindings and newly opened conversations."""
    result = {"space_ids": [], "only_selected": False, "document_ids": [],
              "mode": "tutor", "save_space_id": "", "tool_mode": "native", "hints_only": False,
              **(value or {})}
    # Callers edit drafts; never expose a mutable list from a stored payload.
    result["space_ids"] = list(result["space_ids"])
    result["document_ids"] = list(result["document_ids"])
    return result


def markdown_fingerprint(sid, title, body, tags, document_id, expected_version, path_intent=None):
    value = [sid, title, body, list(tags), document_id, expected_version]
    # Preserve historical callers' six-field fingerprints. Only an explicit,
    # stable path intention extends it; current source provenance is mutable.
    if path_intent:
        value.append({"path_intent": path_intent})
    return digest(value)


class KnowledgeService:
    def __init__(self, state, engine):
        self.state, self.engine = state, engine

    async def generation(self, owner, conn=None):
        if conn is None:
            async with self.engine.begin() as db:
                return await self.generation(owner, db)
        await conn.execute(insert(generations).values(student_id=owner, generation=0).on_conflict_do_nothing())
        return (await conn.execute(select(generations.c.generation).where(generations.c.student_id == owner))).scalar_one()

    async def guard_generation(self, db, owner, expected):
        matched = await db.execute(generations.update().where(generations.c.student_id == owner,
            generations.c.generation == expected).values(generation=generations.c.generation))
        if matched.rowcount != 1:
            raise KnowledgeError("资料已删除或权限已变更，请重新发起操作。")

    async def bump(self, owner, db=None):
        if db is None:
            async with self.engine.begin() as conn:
                return await self.bump(owner, conn)
        await db.execute(insert(generations).values(student_id=owner, generation=1).on_conflict_do_update(
            index_elements=["student_id"], set_={"generation": generations.c.generation + 1}))
        # Drafts/receipts contain private source-derived content. Do not retain it
        # across revocation; the generation tombstone prevents old work reviving it.
        for table in (drafts, operations):
            await db.execute(delete(table).where(table.c.student_id == owner))

    async def create_space(self, owner, name, kind="personal", conversation_id=""):
        if kind not in {"personal", "course", "session"} or not name.strip() or len(name) > 120:
            raise KnowledgeError("请选择空间类型并填写 1–120 字名称。")
        if kind == "session":
            await self.require_conversation(owner, conversation_id)
        elif conversation_id:
            raise KnowledgeError("只有会话资料可以绑定固定会话。")
        row = dict(student_id=owner, space_id=str(uuid4()), name=name.strip(), kind=kind,
                   conversation_id=conversation_id, enabled=1, deleted_at=None, created_at=now())
        async with self.engine.begin() as db:
            await db.execute(spaces.insert().values(**row))
        return row

    async def list_spaces(self, owner):
        async with self.engine.connect() as db:
            return [dict(r) for r in (await db.execute(select(spaces).where(
                spaces.c.student_id == owner, spaces.c.deleted_at.is_(None)).order_by(spaces.c.created_at))).mappings()]

    async def require_space(self, owner, sid, db=None, *, enabled=False):
        if db is None:
            async with self.engine.connect() as conn:
                return await self.require_space(owner, sid, conn, enabled=enabled)
        row = (await db.execute(select(spaces).where(spaces.c.student_id == owner,
            spaces.c.space_id == sid, spaces.c.deleted_at.is_(None)))).mappings().first()
        if row is None or (enabled and not row["enabled"]):
            raise KnowledgeError("知识库不存在、已删除或已禁用。")
        return dict(row)

    async def require_conversation(self, owner, cid):
        row = await self.state.conversations.get(owner, cid)
        if not row or row.get("trashed_at") or row.get("purged_at"):
            raise KnowledgeError("当前会话不存在或已删除。")
        return row

    async def _reference_conversation(self, owner, cid, *, allow_missing=False):
        row = await self.state.conversations.get(owner, cid)
        if row:
            if row.get("trashed_at") or row.get("purged_at"):
                raise KnowledgeError("当前会话不存在或已删除。")
            return row
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", cid):
            raise KnowledgeError("会话标识无效。")
        # A missing owner-scoped row may still belong to another owner. A
        # preview may inspect the caller's libraries, never that conversation.
        from mathtutor.infrastructure.schema import conversations
        async with self.engine.connect() as db:
            exists = (await db.execute(select(conversations.c.student_id).where(
                conversations.c.conversation_id == cid))).scalar_one_or_none()
        if exists is not None:
            raise KnowledgeError("当前会话不可用。")
        if not allow_missing:
            raise KnowledgeError("当前会话不存在或已删除。")
        return None

    async def _validate_reference_configuration(self, owner, cid, value, *, allow_missing=False):
        await self._reference_conversation(owner, cid, allow_missing=allow_missing)
        payload = reference_configuration(value)
        space_ids, document_ids = payload["space_ids"], payload["document_ids"]
        if len(space_ids) > 32 or len(document_ids) > 128:
            raise KnowledgeError("一次最多挂载 32 个库、选择 128 份资料。")
        if any(not isinstance(x, str) for x in [*space_ids, *document_ids]):
            raise KnowledgeError("知识库和资料标识无效。")
        for sid in set(space_ids):
            space = await self.require_space(owner, sid, enabled=True)
            if space["kind"] == "session" and space["conversation_id"] != cid:
                raise KnowledgeError("会话资料不能挂载到其他会话；请显式导入个人库。")
        if payload["mode"] not in {"knowledge", "tutor"} or payload["tool_mode"] not in {"native", "structured"}:
            raise KnowledgeError("问答或工具协议模式无效。")
        if payload["save_space_id"]:
            space = await self.require_space(owner, payload["save_space_id"], enabled=True)
            if space["kind"] == "session" and space["conversation_id"] != cid:
                raise KnowledgeError("笔记不能保存到其他会话的资料库。")
        payload["space_ids"] = list(dict.fromkeys(space_ids))
        payload["document_ids"] = list(dict.fromkeys(document_ids))
        payload["only_selected"] = bool(payload["only_selected"])
        allowed, _ = await self._reference_candidates(owner, cid, payload)
        if not set(document_ids).issubset({str(x) for x in allowed}):
            raise KnowledgeError("所选资料不属于本会话已挂载范围。")
        return payload

    async def configure(self, owner, cid, *, space_ids, only_selected=False, document_ids=(),
                        mode="tutor", save_space_id="", tool_mode="native", hints_only=False):
        payload = await self._validate_reference_configuration(owner, cid, {
            "space_ids": space_ids, "only_selected": only_selected, "document_ids": document_ids,
            "mode": mode, "save_space_id": save_space_id, "tool_mode": tool_mode, "hints_only": hints_only,
        }, allow_missing=True)
        # Validation and preview are read-only. Only an explicit save creates
        # the conversation and binding, after all selected sources are valid.
        if not await self.state.conversations.get(owner, cid):
            await self.state.conversations.ensure(owner, cid)
        async with self.engine.begin() as db:
            await self.bump(owner, db)
            await db.execute(insert(bindings).values(student_id=owner, conversation_id=cid, payload=payload)
                .on_conflict_do_update(index_elements=["student_id", "conversation_id"], set_={"payload": payload}))
        return payload

    async def attach(self, owner, sid, did, *, expected_generation):
        doc = await self.state.documents.get_document(owner, UUID(did))
        if not doc:
            raise KnowledgeError("资料不存在。")
        async with self.engine.begin() as db:
            await self.guard_generation(db, owner, expected_generation)
            await self.require_space(owner, sid, db, enabled=True)
            await db.execute(insert(members).values(student_id=owner, space_id=sid, document_id=did).on_conflict_do_nothing())
        return await self.snapshot(owner, did)

    async def configuration(self, owner, cid):
        async with self.engine.connect() as db:
            payload = (await db.execute(select(bindings.c.payload).where(bindings.c.student_id == owner,
                bindings.c.conversation_id == cid))).scalar_one_or_none()
        return reference_configuration(payload)

    async def _reference_candidates(self, owner, cid, config):
        legacy = await self.state.conversations.document_ids(owner, cid)
        # Existing explicit global consent is retained; no legacy row is promoted.
        globals_ = [d.document_id for d in await self.state.documents.list_documents(owner) if d.is_global]
        async with self.engine.connect() as db:
            stmt = select(members.c.document_id, members.c.space_id).select_from(members.join(spaces,
                (spaces.c.student_id == members.c.student_id) & (spaces.c.space_id == members.c.space_id))).where(
                members.c.student_id == owner, spaces.c.student_id == owner, spaces.c.deleted_at.is_(None),
                spaces.c.enabled == 1, spaces.c.space_id.in_(config["space_ids"]),
                (spaces.c.kind != "session") | (spaces.c.conversation_id == cid))
            rows = (await db.execute(stmt)).all()
            mounted = [UUID(x.document_id) for x in rows]
        ids = list(dict.fromkeys([*legacy, *globals_, *mounted]))
        legacy_set, global_set = set(legacy), set(globals_)
        memberships = {}
        for row in rows:
            memberships.setdefault(row.document_id, []).append(row.space_id)
        origins = {str(did): {"origin": "conversation" if did in legacy_set else "global" if did in global_set else "library",
                              "space_ids": list(dict.fromkeys(memberships.get(str(did), [])))} for did in ids}
        return ids, origins

    async def reference_state(self, owner, cid, *, configuration=None, preview=False):
        """Project candidates and effective selection without creating any rows.

        New conversation IDs are valid preview targets, but an ordinary GET
        remains empty until the conversation exists. Stored disabled libraries
        are tolerated on reads and excluded by the candidate query; a new save
        or preview must validate its explicitly selected libraries.
        """
        if preview:
            config = await self._validate_reference_configuration(owner, cid, configuration, allow_missing=True)
        else:
            row = await self.state.conversations.get(owner, cid)
            if row is None:
                return {**reference_configuration(), "available_documents": [], "effective_document_ids": []}
            await self.require_conversation(owner, cid)
            config = await self.configuration(owner, cid)
        ids, origins = await self._reference_candidates(owner, cid, config)
        selected = set(config["document_ids"])
        available, effective = [], []
        for did in ids:
            doc = await self.state.documents.get_document(owner, did)
            if doc is None or doc.deleted_at is not None:
                continue
            chosen = not config["only_selected"] or str(did) in selected
            enabled = doc.is_retrievable()
            available.append({"document_id": str(did), "title": doc.filename, "status": doc.status,
                "enabled": enabled, "retrieval_enabled": doc.retrieval_enabled,
                "selected": chosen, **origins[str(did)]})
            if chosen and enabled:
                effective.append(str(did))
        return {**config, "available_documents": available, "effective_document_ids": effective}

    async def scope(self, owner, cid, *, configuration=None):
        await self.require_conversation(owner, cid)
        config = reference_configuration(configuration) if configuration is not None else await self.configuration(owner, cid)
        ids, _ = await self._reference_candidates(owner, cid, config)
        if config["only_selected"]:
            ids = [x for x in ids if str(x) in config["document_ids"]]
        # Repository repeats owner/status/disabled checks before scoring.
        return ids

    async def set_enabled(self, owner, sid, enabled):
        async with self.engine.begin() as db:
            await self.require_space(owner, sid, db)
            await self.bump(owner, db)
            await db.execute(spaces.update().where(spaces.c.student_id == owner, spaces.c.space_id == sid).values(enabled=int(enabled)))

    async def delete_space(self, owner, sid):
        async with self.engine.begin() as db:
            await self.require_space(owner, sid, db)
            await self.bump(owner, db)
            ids = list((await db.execute(select(members.c.document_id).where(members.c.student_id == owner,
                members.c.space_id == sid))).scalars())
            await db.execute(delete(members).where(members.c.student_id == owner, members.c.space_id == sid))
            await db.execute(spaces.update().where(spaces.c.student_id == owner, spaces.c.space_id == sid).values(deleted_at=now()))
            # Shared explicitly imported documents survive in other spaces.
            remaining = set((await db.execute(select(members.c.document_id).where(members.c.student_id == owner))).scalars())
        for did in ids:
            if did not in remaining:
                doc = await self.state.documents.get_document(owner, UUID(did))
                legacy = await self.state.conversations.conversation_ids_for_document(owner, UUID(did))
                if doc and not doc.is_global and not legacy:
                    await self.state.data_lifecycle.delete_document(owner, UUID(did))

    async def persistent_member(self, owner, did):
        async with self.engine.connect() as db:
            return bool((await db.execute(select(members.c.space_id).select_from(members.join(spaces,
                (members.c.student_id == spaces.c.student_id) & (members.c.space_id == spaces.c.space_id))).where(
                members.c.student_id == owner, members.c.document_id == str(did),
                spaces.c.kind.in_(["personal", "course"]), spaces.c.deleted_at.is_(None)).limit(1))).first())

    async def purge_conversation(self, owner, cid):
        for space in await self.list_spaces(owner):
            if space["kind"] == "session" and space["conversation_id"] == cid:
                await self.delete_space(owner, space["space_id"])
        async with self.engine.begin() as db:
            await self.bump(owner, db)
            await db.execute(delete(bindings).where(bindings.c.student_id == owner, bindings.c.conversation_id == cid))

    async def list_notes(self, owner, sid):
        await self.require_space(owner, sid)
        async with self.engine.connect() as db:
            ids = list((await db.execute(select(members.c.document_id).where(
                members.c.student_id == owner, members.c.space_id == sid))).scalars())
        rows = []
        for did in ids:
            doc = await self.state.documents.get_document(owner, UUID(did))
            if doc:
                v = await self.snapshot(owner, did)
                provenance = dict(v["provenance"])
                paths = provenance.get("vault_paths", {}).get(sid)
                if paths:
                    provenance["relative_path"] = paths[0]["path"]
                    provenance["relative_paths"] = [path["path"] for path in paths]
                rows.append({"document_id": did, "title": v["title"], "version": v["version"],
                    "tags": v["tags"], "links": v["links"], "retrieval_enabled": doc.retrieval_enabled,
                    "editable": v["provenance"].get("format") == "markdown", "provenance": provenance})
        return rows

    @staticmethod
    def markdown_chunks(owner, did, version, body):
        chunks, start, section = [], 0, ""
        while start < len(body):
            end = min(len(body), start + 1200)
            if end < len(body):
                newline = body.rfind("\n", start + 400, end)
                if newline >= 0:
                    end = newline + 1
            text = body[start:end]
            headings = re.findall(r"^#{1,6}\s+(.+)$", text, re.M)
            section = headings[-1] if headings else section
            chunks.append(DocumentChunk(chunk_id=uuid5(NAMESPACE_URL, f"{did}:{version}:{start}"),
                student_id=student_uuid(owner), document_id=UUID(did), sequence=len(chunks), text=text,
                content_hash=digest(text), section=section, chunker_version="knowledge_offsets_v1",
                metadata_json={"version": version, "start": start, "end": end}, fts_text=build_fts_text(text)))
            start = end
        return chunks

    async def markdown_operation_receipt(self, owner, sid, *, title, body, tags=(), operation_id,
                                         document_id=None, expected_version=None, path_intent=None):
        """Replay before a caller resolves a now-moved source path.

        The normal save repeats this check inside its write transaction. This
        read is for adapters preparing provenance from the latest snapshot;
        an exact retry must not depend on that snapshot still being unchanged.
        """
        await self.require_space(owner, sid, enabled=True)
        async with self.engine.connect() as db:
            receipt = (await db.execute(select(operations).where(operations.c.student_id == owner,
                operations.c.operation_id == operation_id))).mappings().first()
        if receipt is None:
            return None
        fingerprint = markdown_fingerprint(sid, title, body, tags, document_id, expected_version, path_intent)
        if receipt["fingerprint"] != fingerprint:
            raise KnowledgeError("重复请求的内容不一致。")
        return receipt["payload"]

    async def save_markdown(self, owner, sid, *, title, body, tags=(), operation_id,
                            document_id=None, expected_version=None, expected_generation=None, provenance=None,
                            path_intent=None):
        if not body.strip() or len(body.encode()) > 1024 * 1024 or len(title) > 120 or not title.strip():
            raise KnowledgeError("笔记须有标题和正文，正文最多 1 MiB。")
        if len(tags) > 32 or any(not isinstance(t, str) or len(t) > 64 for t in tags):
            raise KnowledgeError("标签最多 32 个，每个最多 64 字。")
        generation = await self.generation(owner) if expected_generation is None else expected_generation
        fingerprint = markdown_fingerprint(sid, title, body, tags, document_id, expected_version, path_intent)
        content_hash = sha256(body.encode("utf-8")).hexdigest()
        did = document_id or str(uuid4())
        stored_ref = None
        old_ref = None
        try:
            async with self.engine.begin() as db:
                await self.guard_generation(db, owner, generation)
                await self.require_space(owner, sid, db, enabled=True)
                receipt = (await db.execute(select(operations).where(operations.c.student_id == owner,
                    operations.c.operation_id == operation_id))).mappings().first()
                if receipt:
                    if receipt["fingerprint"] != fingerprint:
                        raise KnowledgeError("重复请求的内容不一致。")
                    return receipt["payload"]
                if document_id:
                    member = (await db.execute(select(members).where(members.c.student_id == owner,
                        members.c.space_id == sid, members.c.document_id == did))).first()
                    if not member:
                        raise KnowledgeError("笔记不属于该知识库。")
                    previous = (await db.execute(select(versions).where(versions.c.student_id == owner,
                        versions.c.document_id == did).order_by(versions.c.version.desc()).limit(1))).mappings().first()
                    if not previous or previous["version"] != expected_version or previous["provenance"].get("format") != "markdown":
                        raise KnowledgeError("笔记版本已变化或不是可编辑 Markdown；请重新打开，不能覆盖旧版本。")
                    doc = await sd.select_user_document(db, student_id=owner, document_id=UUID(did))
                    if not doc:
                        raise KnowledgeError("笔记已删除。")
                    version, old_ref = expected_version + 1, doc.storage_ref
                else:
                    # Keep the old owner's content de-duplication contract. Only
                    # this explicit import/save may add a membership.
                    # A new explicit import may reuse bytes previously deleted,
                    # but must get a NEW identity, never revive old citations.
                    tombstones = (await db.execute(select(user_documents.c.document_id).where(
                        user_documents.c.student_id == owner, user_documents.c.content_hash == content_hash,
                        user_documents.c.deleted_at.is_not(None)))).scalars().all()
                    for tombstone in tombstones:
                        await db.execute(user_documents.update().where(user_documents.c.student_id == owner,
                            user_documents.c.document_id == tombstone).values(content_hash=digest(["deleted", tombstone])))
                    doc = await sd.find_user_document_by_hash(db, student_id=owner, content_hash=content_hash)
                    if doc:
                        did = str(doc.document_id)
                        previous = (await db.execute(select(versions.c.version).where(versions.c.student_id == owner,
                            versions.c.document_id == did).order_by(versions.c.version.desc()).limit(1))).scalar_one_or_none()
                        version = previous or 1
                        await db.execute(insert(members).values(student_id=owner, space_id=sid, document_id=did).on_conflict_do_nothing())
                        result = {"document_id": did, "version": version, "space_id": sid, "deduplicated": True}
                        await db.execute(operations.insert().values(student_id=owner, operation_id=operation_id,
                            fingerprint=fingerprint, payload=result, generation=generation))
                        return result
                    version = 1
                text_note = PurePosixPath(str((provenance or {}).get("relative_path", ""))).suffix.lower() == ".txt"
                title_suffix = PurePosixPath(title).suffix
                if text_note:
                    stem = title[:-len(title_suffix)] if title_suffix.lower() in {".txt", ".md", ".markdown"} else title
                    safe_title = sanitize_filename(stem + ".txt")
                else:
                    safe_title = sanitize_filename(title.removesuffix(".md") + ".md")
                stored_ref = self.state.document_storage.ref_for(student_uuid(owner), UUID(did), f"v{version}-{safe_title}")
                await self.state.document_storage.store_bytes(stored_ref, body.encode())
                chunks = self.markdown_chunks(owner, did, version, body)
                doc_values = dict(filename=safe_title, content_hash=content_hash, storage_ref=stored_ref,
                    size_bytes=len(body.encode()), status="ready", parser_version="markdown_exact_v1", chunk_count=len(chunks))
                if document_id:
                    doc = doc.model_copy(update={**doc_values, "mime_type": "text/plain" if text_note else "text/markdown"})
                    await sd.update_user_document(db, student_id=owner, doc=doc)
                    for table in (document_chunk_vectors, document_index_builds):
                        await db.execute(delete(table).where(table.c.student_id == owner, table.c.document_id == did))
                else:
                    doc = UserDocument(document_id=UUID(did), student_id=student_uuid(owner), mime_type="text/plain" if text_note else "text/markdown", **doc_values)
                    await sd.insert_user_document(db, student_id=owner, doc=doc)
                await sd.replace_document_chunks(db, student_id=owner, document_id=UUID(did), chunks=chunks)
                await db.execute(versions.insert().values(student_id=owner, document_id=did, version=version,
                    body=body, body_hash=digest(body), title=safe_title, tags=list(dict.fromkeys(tags)),
                    links=list(dict.fromkeys(re.findall(r"\[\[([^\]\n]{1,120})\]\]", body)))[:128],
                    provenance={**(provenance or {}), "format": "markdown"}, created_at=now()))
                await db.execute(insert(members).values(student_id=owner, space_id=sid, document_id=did).on_conflict_do_nothing())
                result = {"document_id": did, "version": version, "space_id": sid, "deduplicated": False}
                await db.execute(operations.insert().values(student_id=owner, operation_id=operation_id,
                    fingerprint=fingerprint, payload=result, generation=generation))
        except BaseException:
            if stored_ref:
                # Cancellation can arrive at the commit boundary. Never remove
                # bytes that a completed transaction has already referenced.
                async with self.engine.connect() as db:
                    committed = (await db.execute(select(user_documents.c.document_id).where(
                        user_documents.c.student_id == owner, user_documents.c.document_id == did,
                        user_documents.c.storage_ref == stored_ref))).first()
                if not committed:
                    await self.state.document_storage.remove(stored_ref)
            raise
        if old_ref and old_ref != stored_ref:
            await self.state.document_storage.remove(old_ref)
        return result

    async def snapshot(self, owner, did, version=None):
        doc = await self.state.documents.get_document(owner, UUID(did))
        if not doc:
            raise KnowledgeError("资料不存在或已删除。")
        async with self.engine.connect() as db:
            stmt = select(versions).where(versions.c.student_id == owner, versions.c.document_id == did)
            if version is not None:
                stmt = stmt.where(versions.c.version == version)
            row = (await db.execute(stmt.order_by(versions.c.version.desc()).limit(1))).mappings().first()
        if row and (version is not None or row["provenance"].get("format") == "markdown"):
            return dict(row)
        if version is not None and row is None:
            # An explicitly requested version that does not exist must NEVER be
            # answered with the CURRENT content labelled as that version. The
            # old `not in (None, 1)` exemption let `version=1` on a
            # never-snapshotted document return today's text as "v1", which
            # makes a citation claim a provenance the system cannot support.
            raise KnowledgeError("引用版本不存在。")
        generation = await self.generation(owner)
        chunks = await self.state.document_repository.list_chunks(owner, UUID(did))
        body = "\n".join(c.text for c in chunks)
        if row and row["body_hash"] == digest(body) and row["title"] == doc.filename:
            return dict(row)
        next_version = row["version"] + 1 if row else 1
        row = dict(student_id=owner, document_id=did, version=next_version, body=body, body_hash=digest(body),
            # D8: two different hashes, named so they cannot be confused.
            # `source_file_hash` covers the imported BYTES; `body_hash` (the
            # row's own column) covers the RECONSTRUCTED text. They legitimately
            # differ whenever chunking is lossy, and calling both "the hash"
            # made a mismatch unreadable.
            title=doc.filename, tags=[], links=[],
            provenance={"format": "extracted", "source_file_hash": doc.content_hash},
            created_at=now())
        async with self.engine.begin() as db:
            await self.guard_generation(db, owner, generation)
            live = (await db.execute(select(user_documents.c.document_id).where(user_documents.c.student_id == owner,
                user_documents.c.document_id == did, user_documents.c.deleted_at.is_(None)))).first()
            if not live:
                raise KnowledgeError("资料已删除，不能重建旧版本。")
            await db.execute(insert(versions).values(**row).on_conflict_do_nothing())
        return row

    # --------------------------------------------------- citation receipts
    #
    # Active retrieval authorization and historical citation authorization are
    # DIFFERENT questions and are answered by different code paths on purpose.
    # A receipt is issued only from a range that was already legitimately
    # surfaced, grants no new authority, and can never widen a range.

    async def issue_citation_receipt(self, owner, cid, *, did, version, start, end,
                                     body_hash, source_id, generation):
        """Record that this exact range was legitimately surfaced.

        Server-side only. Nothing reaches here from a model argument: the
        caller passes a range it just read successfully.
        """
        receipt_id = "cr-" + digest([str(owner), str(cid), str(did), version, start, end, body_hash])[:32]
        row = dict(student_id=owner, receipt_id=receipt_id, conversation_id=str(cid),
                   document_id=str(did), document_version=version, start=start, end=end,
                   body_hash=body_hash, source_id=source_id,
                   generation_at_issue=generation, issued_at=now())
        async with self.engine.begin() as db:
            await db.execute(insert(receipts).values(**row).on_conflict_do_nothing())
        return receipt_id

    async def read_citation_receipt(self, owner, cid, receipt_id, start, end):
        """Re-verify a historical citation. Fail closed on anything unexpected.

        Deliberately does NOT consult ``retrieval_enabled`` or the current
        generation: a citation the student was already given does not stop
        being verifiable because retrieval was later turned off. It DOES
        require the immutable version to still exist, so deletion (which is
        physical here) invalidates the receipt — privacy deletion overrides
        historical citation availability.
        """
        async with self.engine.connect() as db:
            row = (await db.execute(select(receipts).where(
                receipts.c.student_id == owner, receipts.c.receipt_id == receipt_id))).mappings().first()
        if row is None:
            raise KnowledgeError("引用凭证不存在，或已随资料删除。")
        if str(row["conversation_id"]) != str(cid):
            raise KnowledgeError("引用凭证不属于当前会话。")
        # Exact-tuple equality: a receipt must never be usable to read a
        # wider, a shifted, or a different range.
        if (int(start), int(end)) != (int(row["start"]), int(row["end"])) or end <= start:
            raise KnowledgeError("引用凭证只允许读取其签发的原始区间。")
        async with self.engine.connect() as db:
            version_row = (await db.execute(select(versions).where(
                versions.c.student_id == owner, versions.c.document_id == row["document_id"],
                versions.c.version == row["document_version"]))).mappings().first()
        if version_row is None:
            raise KnowledgeError("资料已删除，历史引用不再可用。")
        body = version_row["body"]
        if version_row["body_hash"] != row["body_hash"] or digest(body) != row["body_hash"]:
            raise KnowledgeError("引用凭证据以校验的版本已变化。")
        if end > len(body):
            raise KnowledgeError("引用凭证区间超出该版本正文。")
        return {"receipt_id": receipt_id, "document_id": row["document_id"],
                "version": row["document_version"], "start": start, "end": end,
                "title": version_row["title"], "body_hash": row["body_hash"],
                "text": body[start:end], "source_id": row["source_id"],
                "historical": True}

    async def read_source(self, owner, cid, did, version, start, end):
        allowed = await self.scope(owner, cid)
        doc = await self.state.documents.get_document(owner, UUID(did))
        if UUID(did) not in allowed or not doc or not doc.is_retrievable():
            raise KnowledgeError("引用不在当前已启用的资料范围内。")
        row = await self.snapshot(owner, did, version)
        if start < 0 or end <= start or end > len(row["body"]) or end - start > 6000:
            raise KnowledgeError("引用区间无效或超过 6000 字。")
        return {"document_id": did, "version": version, "start": start, "end": end,
            "body_hash": row["body_hash"], "title": row["title"], "text": row["body"][start:end],
            "line_start": row["body"][:start].count("\n") + 1,
            "line_end": row["body"][:end].count("\n") + 1,
            "source_format": row["provenance"].get("format", "extracted")}

    async def search(self, owner, cid, query, limit=6):
        if not query.strip() or len(query) > 1000:
            raise KnowledgeError("检索词须为 1–1000 字。")
        ids = await self.scope(owner, cid)
        # Index manager already uses actual configured embeddings, or lexical
        # search. Explicitly reject test-only backends from this product path.
        runtime = self.state.embedding_runtime
        status = runtime.status()
        from mathtutor.infrastructure.embedding_runtime import FakeEmbeddingBackend
        fake = isinstance(runtime.backend(), FakeEmbeddingBackend) or bool(status.descriptor and "fake" in status.descriptor.backend_id.casefold())
        if fake:
            result = await self.state.document_repository.search_chunks(owner, query=query,
                query_tokens=tokenize_lexical(query), document_ids=ids, limit=min(24, limit * 3))
        else:
            result = await self.state.document_index.search(owner, query=query, document_ids=ids, limit=min(24, limit * 3))
        # Ranking goes through the ONE production reranker. This used to be an
        # inline `hit.score + 1.0*exact + .25*section` here, which meant two
        # different rankers scored the same hits on the same path and the
        # inline weights were untested magic numbers. The reranker is applied
        # BEFORE offset resolution so an unresolvable (stale) hit cannot
        # influence the ordering of citable ones.
        reranked = ProductionReranker().rerank(query, result.hits)

        candidates = []
        for row in reranked:
            hit = row.hit
            snapshot_row = await self.snapshot(owner, str(hit.document_id))
            meta = hit.chunk.metadata_json
            start = meta.get("start") if meta.get("version") == snapshot_row["version"] else None
            if start is None:
                start = snapshot_row["body"].find(hit.chunk.text)
            if start < 0 or snapshot_row["body"][start:start + len(hit.chunk.text)] != hit.chunk.text:
                continue  # stale or mismatched index is not citation evidence
            candidates.append({"document_id": str(hit.document_id), "version": snapshot_row["version"],
                "start": start, "end": start + min(len(hit.chunk.text), 1800), "title": snapshot_row["title"],
                "section": hit.chunk.section, "excerpt": hit.chunk.text[:1800],
                "score": row.rerank_score})
        # Stable tiebreak on (document_id, start) so equally-scored hits do not
        # reorder between runs.
        candidates.sort(key=lambda item: (-item["score"], item["document_id"], item["start"]))
        return {"query": query, "hits": candidates[:limit],
            "retrieval": "hybrid" if result.vector_used and not fake else "lexical", "support_verified": False}

    async def backlinks(self, owner, did):
        target = await self.snapshot(owner, did)
        names = {target["title"], target["title"].removesuffix(".md")}
        latest = {}
        async with self.engine.connect() as db:
            for row in (await db.execute(select(versions).where(versions.c.student_id == owner).order_by(versions.c.version))).mappings():
                latest[row["document_id"]] = dict(row)
        result = []
        for row in latest.values():
            if names.intersection(row["links"]) and await self.state.documents.get_document(owner, UUID(row["document_id"])):
                result.append({"document_id": row["document_id"], "title": row["title"]})
        return result

    async def export(self, owner, sid):
        notes = await self.list_notes(owner, sid)
        if len(notes) > 1000:
            raise KnowledgeError("单次导出最多 1000 份笔记，请分库导出。")
        stream = io.BytesIO()
        total = 0
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for note in notes:
                row = await self.snapshot(owner, note["document_id"])
                total += len(row["body"].encode())
                if total > 64 * 1024 * 1024:
                    raise KnowledgeError("单次导出正文最多 64 MiB，请分库导出。")
                archive.writestr(note["document_id"] + "-" + sanitize_filename(row["title"]).removesuffix(".md") + ".md", row["body"])
            archive.writestr("manifest.json", json.dumps(notes, ensure_ascii=False, indent=2))
        return stream.getvalue()

    async def forget_document(self, owner, did, db=None):
        if db is None:
            async with self.engine.begin() as conn:
                return await self.forget_document(owner, did, conn)
        await self.bump(owner, db)
        # Receipts are removed with the document: deletion is physical here,
        # and privacy deletion overrides historical citation availability.
        # They also carry a document id and a range, so retaining them after
        # the content is gone would be retention the user did not ask for.
        for table in (versions, members, receipts):
            await db.execute(delete(table).where(table.c.student_id == owner, table.c.document_id == str(did)))

    async def purge(self, owner):
        async with self.engine.begin() as db:
            await self.bump(owner, db)
            for table in (versions, members, bindings, spaces):
                await db.execute(delete(table).where(table.c.student_id == owner))
