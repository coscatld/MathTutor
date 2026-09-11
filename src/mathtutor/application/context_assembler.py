"""ContextAssembler — the ONLY path from repositories to LLM consumers.

Resolves the RetrievalPolicy → loads REQUIRED sources → optionally
retrieves OPTIONAL sources (router + user permission + token budget) →
projects each into a typed context → records provenance. LLM consumers
(TutorWriter, practice generators) receive :class:`AssembledContext` and
NOTHING else: they never query repositories directly, never see raw DB
rows, and never decide for themselves whether to read REQUIRED
educational state — the plan is frozen data.

Enforcement rules implemented HERE (design §21):

- REQUIRED sources must load; an unavailable REQUIRED source fails the
  operation closed (RequiredSourceUnavailableError). Two exceptions,
  both recorded rather than fatal: ``disabled_by_user`` (user permission
  outranks EVERYTHING including the policy matrix) and ``empty_data``
  (the source loaded but has no data yet — a brand-new student has no
  projection/observations/evidence).
- OPTIONAL sources are retrieved only when the ContextRouter selects
  them and the remaining token budget allows (else ``budget_trimmed``).
- FORBIDDEN sources are structurally absent (``forbidden`` provenance).
- Providers enforce user permission at the DATA layer (repositories
  filter retrieval_enabled + soft delete), so a disabled source can
  never leak through the router path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Protocol, Sequence
from uuid import UUID

from mathtutor.domain.assembled_context import (
    AssembledContext,
    AttemptSummaryEntry,
    ContextProvenance,
    CurriculumContext,
    CurriculumNodeRef,
    DocumentChunkRef,
    DocumentContextSelection,
    MasteryEntry,
    MemoryContextEntry,
    MisconceptionContext,
    MisconceptionEntry,
    PersonalMemoryContext,
    RecentAttemptsContext,
    StudentModelContext,
)
from mathtutor.domain.retrieval_policy import (
    RetrievalIntent,
    RetrievalPlan,
    RetrievalPolicy,
    RetrievalSource,
)
from mathtutor.repositories.memory_repository import MemoryRepository
from mathtutor.security.scopes import student_uuid

DEFAULT_TOKEN_BUDGET = 4000
OPTIONAL_FLOOR_TOKENS = 150  # below this remaining budget, optional sources are trimmed
MAX_MEMORY_ENTRIES = 20
MAX_ATTEMPT_ENTRIES = 10
MAX_DOCUMENT_CHUNKS = 8
MAX_PROJECTED_CHUNK_CHARS = 600  # per-chunk projection cap for LLM consumers


class RequiredSourceUnavailableError(RuntimeError):
    """A REQUIRED source could not be loaded — the operation fails closed."""


@dataclass(frozen=True, slots=True)
class LoadOutcome:
    """One provider load/retrieve result (typed payload or nothing).

    ``payload is None`` combined with:
    - ``empty_data=True`` → the source loaded fine, there is simply no data
      (a brand-new student has no projection/observations/evidence) — a
      legitimate EMPTY state, never a failure;
    - ``disabled_by_user=True`` → user permission blocked the read —
      recorded, never fatal, outranks even REQUIRED;
    - neither → the source is genuinely UNAVAILABLE: REQUIRED fail-closed
      (RequiredSourceUnavailableError), OPTIONAL recorded as unavailable.
    """

    payload: Any | None = None
    empty_data: bool = False
    disabled_by_user: bool = False
    detail: str = ""


def estimate_text_tokens(text: str) -> int:
    """Conservative token estimate (CJK ≈1 token/char, latin ≈4 chars/token)."""
    return max(1, len(text) // 2)


def estimate_payload_tokens(payload: Any) -> int:
    """Budget estimate for one typed payload (deterministic, cheap)."""
    try:
        if hasattr(payload, "model_dump_json"):
            raw = payload.model_dump_json()
        elif hasattr(payload, "model_dump"):
            raw = json.dumps(payload.model_dump(), ensure_ascii=False, default=str)
        else:
            raw = str(payload)
    except Exception:
        raw = str(payload)
    return estimate_text_tokens(raw)


class TokenBudget:
    """Non-persistent running budget for one assembly."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def remaining(self) -> int:
        return self.limit - self.used

    def consume(self, tokens: int) -> None:
        self.used += tokens


def _mastery_pairs(raw: Any) -> list[tuple[str, float]]:
    """Normalize a persisted mastery column into (id, value) pairs.

    The student-model projection (learning.projection) writes mastery as a
    list of ``{"<skill|concept>_id": ..., "mastery": ...}`` dicts; earlier
    readers expected a flat ``{id: value}`` map. Accept BOTH shapes so the
    authoritative persistence format and legacy rows stay compatible — a
    read-side normalization only (Invariant D: the student model itself is
    never written here).
    """
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        return [(str(key), float(value)) for key, value in raw.items()]
    pairs: list[tuple[str, float]] = []
    for entry in raw:
        if isinstance(entry, Mapping):
            key = entry.get("skill_id") or entry.get("concept_id") or entry.get("id")
            if key is None:
                continue
            pairs.append((str(key), float(entry.get("mastery", 0.0))))
        elif entry is not None:
            pairs.append((str(entry), 0.0))
    return pairs


def _mastery_entry(key: str, value: float) -> MasteryEntry:
    """One normalized mastery entry (skill/concept id → mastery)."""
    try:
        return MasteryEntry(skill_id=key, mastery=float(value))
    except (TypeError, ValueError):
        return MasteryEntry(skill_id=key, mastery=0.0)


class ContextSourceProvider(Protocol):
    """One knowledge source behind the assembler (typed, owner-scoped)."""

    source: RetrievalSource

    async def load(
        self,
        *,
        student_id: str,
        intent: RetrievalIntent,
        node_ids: Sequence[str] | None = None,
        query_hint: str = "",
    ) -> LoadOutcome: ...

    async def retrieve(
        self,
        *,
        student_id: str,
        intent: RetrievalIntent,
        query_hint: str,
    ) -> LoadOutcome: ...


class BaseContextSourceProvider:
    """Default no-op load/retrieve (providers override what they support)."""

    source: RetrievalSource

    async def load(
        self,
        *,
        student_id: str,
        intent: RetrievalIntent,
        node_ids: Sequence[str] | None = None,
        query_hint: str = "",
    ) -> LoadOutcome:
        return LoadOutcome(detail="load not supported by this provider")

    async def retrieve(
        self,
        *,
        student_id: str,
        intent: RetrievalIntent,
        query_hint: str,
    ) -> LoadOutcome:
        return LoadOutcome(detail="retrieve not supported by this provider")


# ------------------------------------------------------------- providers


class StudentModelSourceProvider(BaseContextSourceProvider):
    """REQUIRED authoritative state (projection only — derived, not raw)."""

    source = RetrievalSource.STUDENT_MODEL

    def __init__(
        self,
        load_projection: Callable[[str], Awaitable[dict[str, Any] | None]],
    ) -> None:
        self._load_projection = load_projection

    async def load(
        self,
        *,
        student_id: str,
        intent: RetrievalIntent,
        node_ids: Sequence[str] | None = None,
        query_hint: str = "",
    ) -> LoadOutcome:
        projection = await self._load_projection(student_id)
        if projection is None:
            return LoadOutcome(empty_data=True, detail="no student projection yet")
        concept_mastery = tuple(
            _mastery_entry(key, value)
            for key, value in _mastery_pairs(projection.get("concept_mastery"))
        )
        skill_mastery = tuple(
            _mastery_entry(key, value)
            for key, value in _mastery_pairs(projection.get("skill_mastery"))
        )
        active = projection.get("active_misconceptions") or []
        rule_ids: list[str] = []
        for entry in active:
            if isinstance(entry, dict):
                rule_id = entry.get("rule_id")
            else:
                rule_id = entry
            if rule_id:
                rule_ids.append(str(rule_id))
        context = StudentModelContext(
            estimator_version=str(projection.get("estimator_version") or ""),
            projection_version=int(projection.get("projection_version") or 0),
            concept_mastery=concept_mastery,
            skill_mastery=skill_mastery,
            active_misconception_rule_ids=tuple(rule_ids),
        )
        return LoadOutcome(payload=context)


class CurriculumSourceProvider(BaseContextSourceProvider):
    """REQUIRED curriculum slice (what the math IS — versioned catalog)."""

    source = RetrievalSource.CURRICULUM

    def __init__(
        self,
        fetch_nodes: Callable[
            [str, Sequence[str] | None], Awaitable[list[CurriculumNodeRef]]
        ],
        version_code: str,
    ) -> None:
        self._fetch_nodes = fetch_nodes
        self._version_code = version_code

    async def load(
        self,
        *,
        student_id: str,
        intent: RetrievalIntent,
        node_ids: Sequence[str] | None = None,
        query_hint: str = "",
    ) -> LoadOutcome:
        nodes = await self._fetch_nodes(student_id, node_ids)
        if not nodes:
            return LoadOutcome(empty_data=True, detail="no curriculum nodes")
        return LoadOutcome(
            payload=CurriculumContext(version_code=self._version_code, nodes=tuple(nodes))
        )


class MisconceptionSourceProvider(BaseContextSourceProvider):
    """REQUIRED observation-history aggregate (rule id + count)."""

    source = RetrievalSource.MISCONCEPTION_HISTORY

    def __init__(
        self,
        load_observations: Callable[[str], Awaitable[Sequence[Any]]],
    ) -> None:
        self._load_observations = load_observations

    async def load(
        self,
        *,
        student_id: str,
        intent: RetrievalIntent,
        node_ids: Sequence[str] | None = None,
        query_hint: str = "",
    ) -> LoadOutcome:
        observations = await self._load_observations(student_id)
        if not observations:
            return LoadOutcome(empty_data=True, detail="no misconception observations")
        counts: dict[str, int] = {}
        for observation in observations:
            rule_id = str(getattr(observation, "rule_id", observation))
            counts[rule_id] = counts.get(rule_id, 0) + 1
        entries = tuple(
            MisconceptionEntry(rule_id=rule_id, observation_count=count)
            for rule_id, count in sorted(counts.items())
        )
        return LoadOutcome(payload=MisconceptionContext(entries=entries))


class RecentAttemptsSourceProvider(BaseContextSourceProvider):
    """REQUIRED recent attempt stream (evidence replay, chronological)."""

    source = RetrievalSource.RECENT_ATTEMPTS

    def __init__(
        self,
        load_evidence: Callable[[str], Awaitable[Sequence[Any]]],
        max_entries: int = MAX_ATTEMPT_ENTRIES,
    ) -> None:
        self._load_evidence = load_evidence
        self._max_entries = max_entries

    async def load(
        self,
        *,
        student_id: str,
        intent: RetrievalIntent,
        node_ids: Sequence[str] | None = None,
        query_hint: str = "",
    ) -> LoadOutcome:
        evidence = await self._load_evidence(student_id)
        if not evidence:
            return LoadOutcome(empty_data=True, detail="no attempt evidence")
        entries = tuple(
            AttemptSummaryEntry(
                skill_id=str(getattr(item, "skill_id", "UNKNOWN_SKILL")),
                correctness=str(getattr(item, "correctness", "incorrect")),
                effective_assistance_level=int(
                    getattr(item, "effective_assistance_level", 0)
                ),
                attempt_index=int(getattr(item, "attempt_index", 1)),
                created_at=str(getattr(item, "created_at", "")),
                problem_id=str(getattr(item, "problem_id", "")),
            )
            for item in list(evidence)[-self._max_entries :]
        )
        return LoadOutcome(payload=RecentAttemptsContext(entries=entries))


class PersonalMemorySourceProvider(BaseContextSourceProvider):
    """OPTIONAL personal KG (user permission enforced at the data layer)."""

    source = RetrievalSource.PERSONAL_MEMORY

    def __init__(self, repository: MemoryRepository) -> None:
        self._repo = repository

    async def load(
        self,
        *,
        student_id: str,
        intent: RetrievalIntent,
        node_ids: Sequence[str] | None = None,
        query_hint: str = "",
    ) -> LoadOutcome:
        nodes = await self._repo.list_retrievable(
            student_id, limit=MAX_MEMORY_ENTRIES
        )
        if not nodes:
            live = await self._repo.list_nodes(student_id, limit=1)
            if live:
                return LoadOutcome(disabled_by_user=True, detail="retrieval disabled by user")
            return LoadOutcome(empty_data=True, detail="no personal memories")
        entries = tuple(
            MemoryContextEntry(
                memory_id=node.memory_id,
                memory_type=node.memory_type,
                subject=node.subject,
                predicate=node.predicate,
                object_json=node.object_json,
                source_type=node.source_type,
                confidence=node.confidence,
            )
            for node in nodes
        )
        return LoadOutcome(payload=PersonalMemoryContext(entries=entries))


class UserDocumentsSourceProvider(BaseContextSourceProvider):
    """OPTIONAL (or REQUIRED under USE_MY_DOCUMENT) chunk selection.

    Query-driven: ``retrieve`` searches the student's own documents with
    the query hint and projects ranked chunks (capped, per-chunk text
    projection cap). Disabled/deleted documents are invisible at the
    repository layer.
    """

    source = RetrievalSource.USER_DOCUMENTS

    def __init__(self, searchable: Any) -> None:  # DocumentSearchable
        self._searchable = searchable

    async def load(
        self,
        *,
        student_id: str,
        intent: RetrievalIntent,
        node_ids: Sequence[str] | None = None,
        query_hint: str = "",
    ) -> LoadOutcome:
        return LoadOutcome(detail="query-only source — use retrieve()")

    async def retrieve(
        self,
        *,
        student_id: str,
        intent: RetrievalIntent,
        query_hint: str,
    ) -> LoadOutcome:
        if not query_hint.strip():
            return LoadOutcome(detail="no query hint")
        from mathtutor.application.conversation_scope import current_document_scope

        document_ids = current_document_scope()
        if document_ids is not None and not document_ids:
            return LoadOutcome(empty_data=True, detail="conversation has no documents")
        result = await self._searchable.search(
            student_id,
            query=query_hint,
            limit=MAX_DOCUMENT_CHUNKS,
            document_ids=document_ids,
        )
        if not result.hits:
            return LoadOutcome(empty_data=True, detail="no document hits")
        retriever = "lexical+vector" if result.vector_used else "lexical"
        selections: dict[UUID, list[DocumentChunkRef]] = {}
        filenames: dict[UUID, str] = {}
        for hit in result.hits:
            selections.setdefault(hit.document_id, []).append(
                DocumentChunkRef(
                    chunk_id=hit.chunk.chunk_id,
                    document_id=hit.document_id,
                    sequence=hit.chunk.sequence,
                    page=hit.chunk.page,
                    filename=hit.filename,
                    text=hit.chunk.text[:MAX_PROJECTED_CHUNK_CHARS],
                    score=hit.score,
                    retriever=retriever,
                )
            )
            filenames.setdefault(hit.document_id, hit.filename)
        ordered = sorted(selections, key=lambda doc_id: -max(
            (chunk.score for chunk in selections[doc_id]), default=0.0
        ))
        payload = tuple(
            DocumentContextSelection(
                document_id=doc_id,
                filename=filenames[doc_id],
                chunks=tuple(selections[doc_id]),
            )
            for doc_id in ordered
        )
        return LoadOutcome(payload=payload)


class StaticCurriculumProvider(CurriculumSourceProvider):
    """MVP curriculum catalog (skills.py taxonomy) — static, versioned.

    The full curriculum (versioned nodes, stages, mappings) is future
    work; this provider serves the stable MVP taxonomy so practice and
    document contexts carry a real curriculum slice today.
    """

    VERSION_CODE = "mt-curriculum-mvp-v1"

    def __init__(self) -> None:
        nodes = [
            CurriculumNodeRef(node_id="ARITHMETIC", code="ARITHMETIC", kind="skill", title="四则运算", stage="primary"),
            CurriculumNodeRef(node_id="POLYNOMIAL_BASIC", code="POLYNOMIAL_BASIC", kind="skill", title="多项式基础", stage="junior"),
            CurriculumNodeRef(node_id="LINEAR_EQUATION", code="LINEAR_EQUATION", kind="skill", title="一元一次方程", stage="junior"),
            CurriculumNodeRef(node_id="QUADRATIC_EQUATION", code="QUADRATIC_EQUATION", kind="skill", title="一元二次方程", stage="junior"),
            CurriculumNodeRef(node_id="LINEAR_SYSTEM", code="LINEAR_SYSTEM", kind="skill", title="二元一次方程组", stage="junior"),
            CurriculumNodeRef(node_id="CONCEPT_NUMBER_OPERATIONS", code="CONCEPT_NUMBER_OPERATIONS", kind="concept", title="数与运算", stage="primary"),
            CurriculumNodeRef(node_id="CONCEPT_POLYNOMIALS", code="CONCEPT_POLYNOMIALS", kind="concept", title="多项式", stage="junior"),
            CurriculumNodeRef(node_id="CONCEPT_LINEAR_EQUATIONS", code="CONCEPT_LINEAR_EQUATIONS", kind="concept", title="一次方程", stage="junior"),
            CurriculumNodeRef(node_id="CONCEPT_QUADRATIC_EQUATIONS", code="CONCEPT_QUADRATIC_EQUATIONS", kind="concept", title="二次方程", stage="junior"),
            CurriculumNodeRef(node_id="CONCEPT_LINEAR_SYSTEMS", code="CONCEPT_LINEAR_SYSTEMS", kind="concept", title="线性方程组", stage="junior"),
        ]

        async def fetch(_student_id: str, node_ids: Sequence[str] | None) -> list[CurriculumNodeRef]:
            if node_ids:
                wanted = set(node_ids)
                return [node for node in nodes if node.node_id in wanted]
            return list(nodes)

        super().__init__(fetch_nodes=fetch, version_code=self.VERSION_CODE)


# ----------------------------------------------------------------- router


class ContextRouter:
    """Deterministic OPTIONAL-source selection (budget + query-drivenness).

    Default rule: retrieve every OPTIONAL source the policy allows while
    the remaining budget is above the floor; USER_DOCUMENTS additionally
    requires a non-empty query hint (documents are query-driven). The
    router NEVER re-includes a source the policy forbids and NEVER
    overrides user permission — providers enforce that at the data layer.
    """

    def __init__(self, optional_floor_tokens: int = OPTIONAL_FLOOR_TOKENS) -> None:
        self._floor = optional_floor_tokens

    def decide_optional(
        self, plan: RetrievalPlan, budget: TokenBudget, *, has_query_hint: bool
    ) -> set[RetrievalSource]:
        chosen: set[RetrievalSource] = set()
        for source in plan.optional_sources():
            if budget.remaining() < self._floor:
                continue
            if source is RetrievalSource.USER_DOCUMENTS and not has_query_hint:
                continue
            chosen.add(source)
        return chosen


# -------------------------------------------------------------- assembler


def _item_count(payload: Any) -> int:
    if isinstance(payload, StudentModelContext):
        return len(payload.skill_mastery) + len(payload.concept_mastery)
    if isinstance(payload, CurriculumContext):
        return len(payload.nodes)
    if isinstance(payload, MisconceptionContext):
        return len(payload.entries)
    if isinstance(payload, RecentAttemptsContext):
        return len(payload.entries)
    if isinstance(payload, PersonalMemoryContext):
        return len(payload.entries)
    if isinstance(payload, tuple):  # DocumentContextSelection tuple
        return sum(len(selection.chunks) for selection in payload)
    return 1 if payload is not None else 0


class ContextAssembler:
    """Policy → load/retrieve → projection → budget → provenance → context."""

    def __init__(
        self,
        *,
        providers: Mapping[RetrievalSource, ContextSourceProvider],
        policy: RetrievalPolicy | None = None,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        router: ContextRouter | None = None,
    ) -> None:
        self._providers = dict(providers)
        self._policy = policy if policy is not None else RetrievalPolicy()
        self._token_budget = token_budget
        self._router = router if router is not None else ContextRouter()

    async def assemble(
        self,
        *,
        student_id: str,
        intent: RetrievalIntent,
        query_hint: str = "",
        node_ids: Sequence[str] | None = None,
    ) -> AssembledContext:
        plan = self._policy.resolve(intent)
        budget = TokenBudget(self._token_budget)
        provenance: list[ContextProvenance] = []
        fields: dict[RetrievalSource, Any] = {}

        # FORBIDDEN first — structurally absent, recorded as such.
        for source in RetrievalSource:
            if plan.is_forbidden(source):
                provenance.append(
                    ContextProvenance(
                        source=source,
                        status="forbidden",
                        schema_version=RetrievalPolicy.POLICY_VERSION,
                    )
                )

        # REQUIRED: fail closed on unavailability (user permission excepted).
        # USER_DOCUMENTS is query-driven even when REQUIRED (USE_MY_DOCUMENT)
        # — it goes through retrieve(); a missing query hint fails closed.
        for source in plan.required_sources():
            provider = self._providers.get(source)
            if provider is None:
                raise RequiredSourceUnavailableError(
                    f"no provider registered for REQUIRED source {source.value}"
                )
            if source is RetrievalSource.USER_DOCUMENTS:
                outcome = await provider.retrieve(
                    student_id=student_id, intent=intent, query_hint=query_hint
                )
            else:
                outcome = await provider.load(
                    student_id=student_id, intent=intent, node_ids=node_ids, query_hint=query_hint
                )
            if outcome.payload is None:
                if outcome.disabled_by_user:
                    # User permission outranks the policy matrix — recorded,
                    # not fatal (e.g. USE_MY_DOCUMENT with all docs disabled).
                    provenance.append(
                        ContextProvenance(
                            source=source,
                            status="disabled_by_user",
                            schema_version=RetrievalPolicy.POLICY_VERSION,
                            detail=outcome.detail,
                        )
                    )
                    continue
                if outcome.empty_data:
                    # The source loaded; there is simply no data yet (a new
                    # student has no projection/observations/evidence).
                    provenance.append(
                        ContextProvenance(
                            source=source,
                            status="empty",
                            schema_version=RetrievalPolicy.POLICY_VERSION,
                            detail=outcome.detail,
                        )
                    )
                    continue
                raise RequiredSourceUnavailableError(
                    f"REQUIRED source {source.value} unavailable: {outcome.detail}"
                )
            fields[source] = outcome.payload
            budget.consume(estimate_payload_tokens(outcome.payload))
            provenance.append(
                ContextProvenance(
                    source=source,
                    status="loaded" if _item_count(outcome.payload) > 0 else "empty",
                    item_count=_item_count(outcome.payload),
                    schema_version=RetrievalPolicy.POLICY_VERSION,
                )
            )

        # OPTIONAL: router → user permission (data layer) → budget.
        chosen = self._router.decide_optional(
            plan, budget, has_query_hint=bool(query_hint.strip())
        )
        for source in plan.optional_sources():
            if source not in chosen:
                provenance.append(
                    ContextProvenance(
                        source=source,
                        status="router_skipped",
                        schema_version=RetrievalPolicy.POLICY_VERSION,
                    )
                )
                continue
            provider = self._providers.get(source)
            if provider is None:
                provenance.append(
                    ContextProvenance(
                        source=source,
                        status="unavailable",
                        schema_version=RetrievalPolicy.POLICY_VERSION,
                        detail="no provider registered",
                    )
                )
                continue
            if source is RetrievalSource.USER_DOCUMENTS:
                outcome = await provider.retrieve(
                    student_id=student_id, intent=intent, query_hint=query_hint
                )
            else:
                outcome = await provider.load(
                    student_id=student_id,
                    intent=intent,
                    node_ids=node_ids,
                    query_hint=query_hint,
                )
            if outcome.payload is None:
                if outcome.disabled_by_user:
                    status = "disabled_by_user"
                elif outcome.empty_data:
                    status = "empty"
                else:
                    status = "unavailable"
                provenance.append(
                    ContextProvenance(
                        source=source,
                        status=status,
                        schema_version=RetrievalPolicy.POLICY_VERSION,
                        detail=outcome.detail,
                    )
                )
                continue
            tokens = estimate_payload_tokens(outcome.payload)
            if tokens > budget.remaining():
                provenance.append(
                    ContextProvenance(
                        source=source,
                        status="budget_trimmed",
                        schema_version=RetrievalPolicy.POLICY_VERSION,
                        detail=f"needs ~{tokens} tokens, {budget.remaining()} left",
                    )
                )
                continue
            budget.consume(tokens)
            fields[source] = outcome.payload
            provenance.append(
                ContextProvenance(
                    source=source,
                    status="loaded" if _item_count(outcome.payload) > 0 else "empty",
                    item_count=_item_count(outcome.payload),
                    schema_version=RetrievalPolicy.POLICY_VERSION,
                )
            )

        return AssembledContext(
            intent=intent,
            student_id=student_uuid(student_id),
            policy_version=RetrievalPolicy.POLICY_VERSION,
            plan=plan,
            student_model=fields.get(RetrievalSource.STUDENT_MODEL),
            curriculum=fields.get(RetrievalSource.CURRICULUM),
            misconception_history=fields.get(RetrievalSource.MISCONCEPTION_HISTORY),
            recent_attempts=fields.get(RetrievalSource.RECENT_ATTEMPTS),
            personal_memory=fields.get(RetrievalSource.PERSONAL_MEMORY),
            user_documents=fields.get(RetrievalSource.USER_DOCUMENTS, ()),
            provenance=tuple(provenance),
        )


__all__ = [
    "BaseContextSourceProvider",
    "ContextAssembler",
    "ContextRouter",
    "ContextSourceProvider",
    "CurriculumSourceProvider",
    "DEFAULT_TOKEN_BUDGET",
    "LoadOutcome",
    "MAX_ATTEMPT_ENTRIES",
    "MAX_DOCUMENT_CHUNKS",
    "MAX_MEMORY_ENTRIES",
    "MAX_PROJECTED_CHUNK_CHARS",
    "MisconceptionSourceProvider",
    "PersonalMemorySourceProvider",
    "RecentAttemptsSourceProvider",
    "RequiredSourceUnavailableError",
    "StaticCurriculumProvider",
    "StudentModelSourceProvider",
    "TokenBudget",
    "UserDocumentsSourceProvider",
    "estimate_payload_tokens",
    "estimate_text_tokens",
]
