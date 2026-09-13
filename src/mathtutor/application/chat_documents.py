"""Bounded, owner- and conversation-scoped documents for ordinary/vision chat.

Reuses the existing search pipeline. A named-file overview selects existing
chunks, never reparses files or treats uploaded text as trusted instructions.
"""
from pathlib import PurePath
import re

from mathtutor.application.conversation_scope import current_document_scope

MAX_CONTEXT_CHARS = 12000
MAX_CHUNKS = 8


class ChatDocumentContext:
    def __init__(self, documents, repository, search):
        self.documents = documents
        self.repository = repository
        self.search = search

    async def build(self, owner, text, history=()):
        scope = current_document_scope()
        if not owner or not scope:
            return None  # never widen a missing conversation scope to all files
        inventory = []
        eligible = []
        for document_id in scope[:32]:
            doc = await self.documents.get_document(owner, document_id)
            if doc is None or doc.deleted_at is not None:
                continue
            inventory.append({"filename": doc.filename, "status": doc.status,
                              "retrieval_enabled": doc.retrieval_enabled})
            if doc.can_enable_retrieval() and doc.retrieval_enabled:
                eligible.append(doc)
        result = {"files": inventory, "status": "no_retrievable_documents", "chunks": []}
        if not eligible:
            return result
        named = [d for d in eligible if d.filename.casefold() in text.casefold()
                 or (len(PurePath(d.filename).stem) >= 2 and PurePath(d.filename).stem.casefold() in text.casefold())]
        targets = named or eligible
        query = text.strip()
        if not named and re.search(r"这个|那个|继续|这份|上述|刚才|里面", query):
            previous = [m.get("content", "") for m in history[-6:] if m.get("role") == "student" and m.get("content") != text]
            query += " " + " ".join(previous[-2:])[:500]
        hits = await self.search.search(owner, query=query, document_ids=[d.document_id for d in targets], limit=MAX_CHUNKS)
        candidates = [(h.filename, h.chunk, "检索命中") for h in hits.hits]
        # Referential requests often contain no topic keywords ("我上传的文档").
        # One file or explicitly named files can supply a bounded overview.
        if named or (len(eligible) == 1 and re.search(r"文档|资料|文件|附件|总结|概括|pdf", text, re.I)):
            overview = []
            total_chunks = 0
            for doc in targets[:3]:
                chunks = await self.repository.list_chunks(owner, doc.document_id)
                total_chunks += len(chunks)
                overview.extend((doc.filename, chunk, "文档概览") for chunk in chunks[:MAX_CHUNKS])
            # Keep overview order for small files; matching chunks win for long files.
            candidates = overview if total_chunks <= MAX_CHUNKS else candidates + overview
        seen = set()
        budget = MAX_CONTEXT_CHARS
        for filename, chunk, source in candidates:
            if chunk.chunk_id in seen or len(result["chunks"]) >= MAX_CHUNKS or budget <= 0:
                continue
            seen.add(chunk.chunk_id)
            body = chunk.text[:min(2000, budget)]
            if not body.strip():
                continue
            result["chunks"].append({"filename": filename, "chunk": chunk.sequence + 1,
                                     "text": body, "selection": source})
            budget -= len(body)
        result["status"] = "available" if result["chunks"] else "no_matching_chunks"
        result["partial"] = True  # bounded selections are never proof of full-file reading
        return result
