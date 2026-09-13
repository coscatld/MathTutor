"""Conversation trash retains content until an explicit permanent deletion."""
async def purge_conversation(state, owner, cid):
    """Caller holds the same conversation lock used by WebSocket turns.

    Learning facts/statistics and user-created backups are separate data
    categories, explicitly excluded in the permanent-delete confirmation.
    """
    repo = state.conversations
    messages = await repo.messages(owner, cid)
    image_ids = {a["id"] for m in messages for a in m.get("attachments", []) if a.get("id")}
    for other in await repo.list(owner, all_records=True):
        if other["conversation_id"] != cid:
            for message in await repo.messages(owner, other["conversation_id"]):
                image_ids.difference_update(a.get("id") for a in message.get("attachments", []))
    for doc_id in await repo.document_ids(owner, cid):
        doc = await state.documents.get_document(owner, doc_id)
        memberships = await repo.conversation_ids_for_document(owner, doc_id)
        if doc and not doc.is_global and not (set(memberships) - {cid}):
            await state.data_lifecycle.delete_document(owner, doc_id)
    for image_id in image_ids:
        await state.images.remove(owner, image_id)
    await repo.purge(owner, cid)
    await state.turn_requests.forget(owner, cid)
