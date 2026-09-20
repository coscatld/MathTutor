"""Bounded, owner- and conversation-scoped documents for ordinary/vision chat.

ROLE (Route 2, docs/CURRENT_STATE_RAG_AUDIT.md §4.5): this is a **presentation
and selection adapter**, not a retrieval path.

It used to resolve the scope, run its own search, decide its own overview
retrieval and carry its own visibility rules — a second initial-retrieval
implementation alongside the knowledge path. Retrieval now comes from the one
:class:`ConversationRetrievalOrchestrator`; what stays here is what is genuinely
presentation:

- which of the conversation's documents exist, and their status (inventory);
- preferring files the student named explicitly, and a bounded overview when a
  referential question ("我上传的文档") has no topical keywords;
- the projection shape the chat prompt consumes, and its ``partial`` label.

The scope is still read from the per-turn contextvar, and an UNSET scope is
fails closed — the orchestrator's ``document_ids`` is a required argument, so
"no scope" cannot degrade into an owner-wide search.
"""

from pathlib import PurePath
import re

from mathtutor.application.context_expansion import ContextExpander
from mathtutor.application.conversation_scope import current_document_scope
from mathtutor.application.rerank import ProductionReranker
from mathtutor.application.retrieval_orchestrator import ConversationRetrievalOrchestrator

MAX_CONTEXT_CHARS = 12000
MAX_CHUNKS = 8


class ChatDocumentContext:
    def __init__(self, documents, repository, search, orchestrator=None):
        self.documents = documents
        self.repository = repository
        self.search = search
        # Built from the same kernel the knowledge path uses. Injectable so a
        # caller can supply a metrics-wired instance.
        self.orchestrator = orchestrator or ConversationRetrievalOrchestrator(
            kernel=search,
            reranker=ProductionReranker(),
            expander=ContextExpander(repository),
        )

    async def build(self, owner, text, history=()):
        scope = current_document_scope()
        if not owner or not scope:
            # Never widen a missing/empty conversation scope to all files.
            return None

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

        # SELECTION stays here: named files narrow the search scope. RETRIEVAL
        # does not — the orchestrator decides, searches, reranks, expands and
        # bounds, exactly as it does for the knowledge path.
        pack = await self.orchestrator.retrieve_for_turn(
            owner,
            [doc.document_id for doc in targets],
            text,
            history=history,
        )

        if not pack.empty:
            result["chunks"] = [
                {
                    "filename": evidence.filename,
                    "chunk": evidence.sequence + 1,
                    "text": evidence.text,
                    "selection": "上下文扩展" if evidence.expanded else "检索命中",
                }
                for evidence in pack.evidences
            ]

        # Referential requests often carry no topic keywords ("我上传的文档").
        # One file, or explicitly named files, can supply a bounded overview —
        # still read through the visibility-gated repository primitive.
        if not result["chunks"] and (
            named or (len(eligible) == 1 and re.search(r"文档|资料|文件|附件|总结|概括|pdf", text, re.I))
        ):
            overview = []
            total_chunks = 0
            for doc in targets[:3]:
                chunks = await self.repository.list_retrievable_chunks(owner, doc.document_id)
                total_chunks += len(chunks)
                overview.extend((doc.filename, chunk) for chunk in chunks[:MAX_CHUNKS])
            for filename, chunk in overview[:MAX_CHUNKS]:
                result["chunks"].append({
                    "filename": filename,
                    "chunk": chunk.sequence + 1,
                    "text": chunk.text[:MAX_CONTEXT_CHARS],
                    "selection": "文档概览",
                })

        result["status"] = "available" if result["chunks"] else "no_matching_chunks"
        result["partial"] = True  # bounded selections are never proof of full-file reading
        return result
