"""A logical conversation folder over existing owner-scoped repositories."""
import json
import tempfile
import zipfile

from mathtutor.infrastructure.document_storage import sanitize_filename
from mathtutor.repositories.image_repository import public_image


async def reference_state(state, owner, conversation_id):
    knowledge = getattr(state, "knowledge", None)
    if knowledge is not None:
        return await knowledge.reference_state(owner, conversation_id)
    # In-memory/legacy runtimes have no knowledge binding, but keep the same
    # public shape without widening an absent conversation to owner-wide data.
    from mathtutor.application.knowledge import reference_configuration
    document_ids = await state.conversations.document_ids(owner, conversation_id)
    document_ids += [d.document_id for d in await state.documents.list_documents(owner) if d.is_global]
    available, effective = [], []
    for did in dict.fromkeys(document_ids):
        doc = await state.documents.get_document(owner, did)
        if doc is None or doc.deleted_at is not None:
            continue
        enabled = doc.is_retrievable()
        available.append({"document_id": str(did), "title": doc.filename, "status": doc.status,
            "enabled": enabled, "retrieval_enabled": doc.retrieval_enabled, "selected": True,
            "origin": "global" if doc.is_global else "conversation", "space_ids": []})
        if enabled:
            effective.append(str(did))
    return {**reference_configuration(), "available_documents": available, "effective_document_ids": effective}


async def resources(state, owner, conversation_id, *, scope=None):
    messages = await state.conversations.messages(owner, conversation_id)
    documents = []
    if scope is None:
        scope = await reference_state(state, owner, conversation_id)
    from uuid import UUID
    # Inventory includes currently unselected files. Selection changes never
    # detach an uploaded document or remove it from an explicit folder export.
    for candidate in scope["available_documents"]:
        doc_id = UUID(candidate["document_id"])
        doc = await state.documents.get_document(owner, doc_id)
        if doc is not None and doc.deleted_at is None:
            documents.append(doc)
    images = []
    seen = set()
    for message in messages:
        for attachment in message.get("attachments", []):
            image_id = attachment.get("id")
            if not image_id or image_id in seen:
                continue
            seen.add(image_id)
            row = await state.images.get(owner, image_id)
            if row:
                images.append(public_image(row))
    return documents, images, messages


async def export_folder(state, owner, conversation_id):
    scope = await reference_state(state, owner, conversation_id)
    documents, images, messages = await resources(state, owner, conversation_id, scope=scope)
    if sum(d.size_bytes for d in documents) + sum(i["size"] for i in images) > 200 * 1024 * 1024:
        raise ValueError("本对话资料超过 200 MB，请分别导出资料。")
    stream = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    manifest = {"conversation_id": conversation_id, "files": [], "missing": [], "scope": scope,
                "document_sources": []}
    try:
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            public_messages = [{k: m[k] for k in ("role", "content", "created_at", "attachments") if k in m} for m in messages]
            archive.writestr("conversation/messages.json", json.dumps(public_messages, ensure_ascii=False, indent=2))
            for doc in documents:
                name = f"conversation/documents/{doc.document_id}-{sanitize_filename(doc.filename)}"
                path = state.document_storage.resolve(doc.storage_ref)
                if path.is_file():
                    archive.write(path, name)
                    manifest["files"].append(name)
                    manifest["document_sources"].append({"document_id": str(doc.document_id),
                        "file": name, "source": "stored_file", "source_file_hash": doc.content_hash})
                else:
                    # Markdown notes are authoritative versioned content even
                    # when their optional original storage file is unavailable.
                    knowledge = getattr(state, "knowledge", None)
                    if knowledge is not None:
                        snapshot = await knowledge.snapshot(owner, str(doc.document_id))
                        text = snapshot["body"]
                        fallback = name if name.lower().endswith((".md", ".txt", ".tex")) else name + ".txt"
                        archive.writestr(fallback, text)
                        manifest["files"].append(fallback)
                        manifest["document_sources"].append({"document_id": str(doc.document_id), "file": fallback,
                            "source": "knowledge_snapshot", "version": snapshot["version"],
                            "body_hash": snapshot["body_hash"], "source_format": snapshot["provenance"].get("format", "extracted")})
                    else:
                        manifest["missing"].append(doc.filename)
            for item in images:
                row = await state.images.get(owner, item["id"])
                if row:
                    name = f"conversation/images/{item['id']}-{sanitize_filename(item['name'])}"
                    archive.writestr(name, row["data"])
                    manifest["files"].append(name)
            archive.writestr("conversation/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        stream.seek(0)
        return stream
    except BaseException:
        stream.close()
        raise
