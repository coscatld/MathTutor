"""A logical conversation folder over existing owner-scoped repositories."""
import json
import tempfile
import zipfile

from mathtutor.infrastructure.document_storage import sanitize_filename
from mathtutor.repositories.image_repository import public_image


async def resources(state, owner, conversation_id):
    messages = await state.conversations.messages(owner, conversation_id)
    documents = []
    document_ids = await state.conversations.document_ids(owner, conversation_id)
    document_ids += [d.document_id for d in await state.documents.list_documents(owner) if d.is_global]
    for doc_id in dict.fromkeys(document_ids):
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
    documents, images, messages = await resources(state, owner, conversation_id)
    if sum(d.size_bytes for d in documents) + sum(i["size"] for i in images) > 200 * 1024 * 1024:
        raise ValueError("本对话资料超过 200 MB，请分别导出资料。")
    stream = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    manifest = {"conversation_id": conversation_id, "files": [], "missing": []}
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
