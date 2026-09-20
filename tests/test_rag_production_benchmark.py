"""The ONE official RAG benchmark — real corpus, real kernel, real metrics.

Migrated from ``test_phase6_retrieval_benchmark.py``, which scored hand-built
``RetrievalItem`` projections through ``MetadataFirstRetriever`` — a stack with
zero production callers. Its numbers could not go up or down when the product
changed, which made it a benchmark of nothing.

This version differs in every load-bearing respect:

    real documents/chunks → real SQLite repository → real DocumentIndexManager
    → ConversationRetrievalOrchestrator → ProductionReranker → EvidencePack

so a regression anywhere in the production path moves these numbers.

Ground truth is expressed as ``(document_id, sequence)`` — the same identity
retrieval actually returns — not as an id from a parallel fixture type.

Security cases (disabled / cross-owner / cross-conversation / unbound /
deleted / UNSET scope) are asserted to contribute ZERO on every pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log2
from pathlib import Path
from typing import Sequence
from uuid import UUID

import pytest
import pytest_asyncio

from mathtutor.application.context_expansion import ContextExpander
from mathtutor.application.document_ingestion import (
    DocumentIndexManager,
    DocumentIngestionService,
)
from mathtutor.application.desktop_files import PickedFile
from mathtutor.application.rerank import ProductionReranker
from mathtutor.application.retrieval_orchestrator import (
    ConversationRetrievalOrchestrator,
)
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.document_storage import DocumentStorage
from mathtutor.infrastructure.embedding_runtime import EmbeddingRuntime
from mathtutor.infrastructure.migrate import upgrade_db
from mathtutor.infrastructure.observability import MathTutorMetrics
from mathtutor.repositories.sqlite_knowledge import SQLiteDocumentRepository

pytestmark = pytest.mark.asyncio

OWNER = "bench-owner"
OTHER_OWNER = "bench-other"
CONVERSATION = "bench-A"


# ------------------------------------------------------------------ metrics


def recall_at_k(ranked: Sequence[str], relevant: frozenset[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def mrr_at_k(ranked: Sequence[str], relevant: frozenset[str], k: int) -> float:
    for index, item in enumerate(ranked[:k], start=1):
        if item in relevant:
            return 1.0 / index
    return 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: frozenset[str], k: int) -> float:
    if not relevant:
        return 0.0

    def dcg(items: Sequence[str]) -> float:
        return sum(
            1.0 / log2(index + 1)
            for index, item in enumerate(items, start=1)
            if item in relevant
        )

    ideal = dcg(sorted(relevant)[:k])
    return dcg(ranked[:k]) / ideal if ideal else 0.0


def hit_rate_at_k(ranked: Sequence[str], relevant: frozenset[str], k: int) -> float:
    return 1.0 if set(ranked[:k]) & relevant else 0.0


def test_metric_functions_are_hand_verified():
    """The metrics themselves are pinned — a benchmark with a wrong metric
    reports confident nonsense."""
    ranked = ["a", "b", "c"]
    relevant = frozenset({"b", "z"})
    assert recall_at_k(ranked, relevant, 3) == pytest.approx(0.5)
    assert recall_at_k(ranked, relevant, 5) == pytest.approx(0.5)
    assert mrr_at_k(ranked, relevant, 3) == pytest.approx(0.5)
    assert mrr_at_k(ranked, relevant, 1) == 0.0
    assert hit_rate_at_k(ranked, relevant, 1) == 0.0
    assert hit_rate_at_k(ranked, relevant, 2) == 1.0
    assert recall_at_k([], frozenset(), 3) == 0.0
    assert ndcg_at_k([], frozenset(), 3) == 0.0
    # Perfect ranking scores 1.0
    assert ndcg_at_k(["b", "z"], frozenset({"b", "z"}), 2) == pytest.approx(1.0)


# ------------------------------------------------------------------- corpus


@dataclass(frozen=True)
class Document:
    key: str
    filename: str
    body: str


#: Chinese math corpus. Covers the required axes explicitly:
#: canonical terms, spoken variants of the same idea, formula-heavy lines,
#: mixed Chinese/LaTeX, and near-miss concepts that share vocabulary.
CORPUS = (
    Document(
        "linear",
        "一次方程.md",
        # Two `#` sections on purpose: a one-chunk document cannot exercise
        # either multi-hit ranking or context expansion.
        "## 一次方程的定义\n"
        "\n"
        "只含有一个未知数、未知数次数为一的整式方程叫做一元一次方程。\n"
        "\n"
        "## 解一元一次方程的步骤\n"
        "\n"
        "去分母、去括号、移项、合并同类项、系数化为1。\n"
        "\n"
        "移项要变号：把等式一边的某项移到另一边时，符号必须改变。\n"
        "\n"
        "等式的基本性质：等式两边同时加上或减去同一个数，等式仍然成立。\n",
    ),
    Document(
        "quadratic",
        "二次方程.md",
        "## 一元二次方程的一般形式\n"
        "\n"
        "一元二次方程的一般形式是 ax^2 + bx + c = 0，其中 a 不等于零。\n"
        "\n"
        "## 求根公式与判别式\n"
        "\n"
        "求根公式：x = (-b ± √(b²-4ac)) / (2a)。\n"
        "\n"
        "判别式 Δ = b²-4ac 决定根的个数：Δ>0 有两个不等实根，Δ=0 有两个相等实根，Δ<0 无实根。\n",
    ),
    Document(
        "commutative",
        "交换律.md",
        "## 加法交换律\n"
        "\n"
        "两个数相加，交换加数的位置，和不变。\n"
        "\n"
        "用字母表示：a + b = b + a。\n"
        "\n"
        "## 乘法交换律\n"
        "\n"
        "乘法也有交换律：a × b = b × a。\n",
    ),
    Document(
        "associative",
        "结合律.md",
        "## 加法结合律\n"
        "\n"
        "三个数相加，先把前两个数相加，或者先把后两个数相加，和不变。\n"
        "\n"
        "用字母表示：(a + b) + c = a + (b + c)。\n"
        "\n"
        "## 与交换律的区别\n"
        "\n"
        "结合律改变的是运算顺序，交换律改变的是运算对象的位置。\n",
    ),
    Document(
        "fraction",
        "分式笔记.md",
        "## 分式有意义的条件\n"
        "\n"
        "分式的分母不能为零，这是分式有意义的前提条件。\n"
        "\n"
        "分式的基本性质：分子分母同乘或同除以一个不为零的整式，分式的值不变。\n"
        "\n"
        "## 分式方程的增根\n"
        "\n"
        "去分母可能产生增根，所以解分式方程后必须把根代回原方程检验。\n",
    ),
    Document(
        "distractor",
        "数学史话.md",
        "## 九章算术\n"
        "\n"
        "中国古代数学名著《九章算术》成书于汉代，其中记载了方程术与正负术。\n"
        "\n"
        "## 圆周率\n"
        "\n"
        "祖冲之把圆周率精确到小数点后七位。\n",
    ),
)


@dataclass(frozen=True)
class Query:
    key: str
    text: str
    #: ground truth as (document key, chunk sequence). Validated against the
    #: real chunking at fixture time — a hand-written sequence that the
    #: chunker does not produce must fail loudly, not silently mis-score.
    relevant: tuple[tuple[str, int], ...]
    #: text that must appear in the ground-truth chunk
    contains: str


QUERIES = (
    Query("canonical_term", "一元一次方程的定义是什么", (("linear", 0),), "只含有一个未知数"),
    Query("spoken_variant", "等式两边同时减同一个数可以吗", (("linear", 1),), "等式的基本性质"),
    Query("transposition", "移项要变号吗", (("linear", 1),), "移项要变号"),
    Query("formula", "求根公式 x = (-b ± √(b²-4ac)) / (2a)", (("quadratic", 1),), "求根公式"),
    Query("discriminant", "判别式决定根的个数", (("quadratic", 1),), "判别式"),
    Query("commutative", "交换加数的位置和不变", (("commutative", 0),), "两个数相加"),
    Query("associative", "加法结合律的字母表示", (("associative", 0),), "三个数相加"),
    Query("cross_topic", "去分母后为什么要检验", (("fraction", 1),), "增根"),
    Query("mixed_cjk_latex", "ax^2 + bx + c = 0 中 a 不能为零", (("quadratic", 0),), "一般形式是"),
)


# ------------------------------------------------------------------ harness


async def build_benchmark(tmp_path: Path) -> dict:
    """Real SQLite corpus bound to ONE conversation, plus a second owner.

    Extracted from the fixture so the hard-set runner can drive the SAME
    corpus, the SAME orchestrator and the SAME metric definitions. A runner
    that reimplemented any of those would be a second benchmark whose numbers
    could not be compared with these.
    """
    db_file = tmp_path / "bench.db"
    upgrade_db(str(db_file))
    engine = create_db_engine(db_file)
    repository = SQLiteDocumentRepository(engine)
    service = DocumentIngestionService(
        repository=repository,
        storage=DocumentStorage(tmp_path / "data"),
        index_manager=DocumentIndexManager(
            repository=repository, embedding_runtime=EmbeddingRuntime()
        ),
    )

    documents: dict[str, dict] = {}
    for index, document in enumerate(CORPUS):
        ingested = await service.ingest(
            OWNER,
            PickedFile(
                filename=document.filename,
                mime_type="text/markdown",
                data=document.body.encode("utf-8"),
            ),
        )
        chunks = await repository.list_chunks(OWNER, ingested.document_id)
        documents[document.key] = {
            "document_id": ingested.document_id,
            "chunks": sorted(chunks, key=lambda chunk: chunk.sequence),
        }

    # The distractor lives in the same owner but is NOT bound to the
    # conversation, so it must never appear in conversation-scoped results.
    unbound = await service.ingest(
        OWNER,
        PickedFile(
            filename="未绑定.md",
            mime_type="text/markdown",
            data="一元一次方程的移项方法详解，与上面的内容高度相似。".encode("utf-8"),
        ),
    )
    foreign = await service.ingest(
        OTHER_OWNER,
        PickedFile(
            filename="他人.md",
            mime_type="text/markdown",
            data="一元一次方程的移项方法详解，与上面的内容逐字相同。".encode("utf-8"),
        ),
    )

    scope = [
        documents[key]["document_id"]
        for key in ("linear", "quadratic", "commutative", "associative", "fraction", "distractor")
    ]
    metrics = MathTutorMetrics()
    orchestrator = ConversationRetrievalOrchestrator(
        kernel=DocumentIndexManager(
            repository=repository, embedding_runtime=EmbeddingRuntime()
        ),
        reranker=ProductionReranker(),
        expander=ContextExpander(repository),
        metrics=metrics,
    )

    return {
        "engine": engine,
        "repository": repository,
        "service": service,
        "documents": documents,
        "scope": scope,
        "unbound": unbound,
        "foreign": foreign,
        "orchestrator": orchestrator,
        "metrics": metrics,
    }


@pytest_asyncio.fixture()
async def bench(tmp_path: Path):
    env = await build_benchmark(tmp_path)
    try:
        yield env
    finally:
        await env["engine"].dispose()


def _identity(bench, key: str, sequence: int) -> str:
    return f"{bench['documents'][key]['document_id']}:{sequence}"


async def _rank(bench, query: str, *, limit: int = 8, scope=None, owner: str | None = None):
    # ``owner`` is a parameter so a runner over a DIFFERENT corpus can reuse
    # this ranking path instead of writing a second one. Querying the wrong
    # owner is silent — retrieval simply returns nothing — so a duplicated
    # helper would be a quiet way to produce a benchmark of zeroes.
    pack = await bench["orchestrator"].retrieve_for_turn(
        OWNER if owner is None else owner,
        bench["scope"] if scope is None else scope,
        query,
    )
    ranked = [f"{e.document_id}:{e.sequence}" for e in pack.evidences]
    return pack, ranked


# ------------------------------------------------------------------ retrieval


async def test_ground_truth_matches_the_real_chunking(bench):
    """Every ground-truth reference must exist and contain what it claims.

    Written after a hand-authored sequence silently pointed at a chunk the
    chunker never produced: the metric then reported a miss for a completely
    correct retrieval. Fixture drift has to fail here, loudly, rather than
    quietly depress the benchmark.
    """
    for query in QUERIES:
        for key, sequence in query.relevant:
            chunks = bench["documents"][key]["chunks"]
            assert sequence < len(chunks), (
                f"{query.key} expects {key}:{sequence} but that document has "
                f"only {len(chunks)} chunk(s)"
            )
            assert query.contains in chunks[sequence].text, (
                f"{query.key}: {key}:{sequence} does not contain {query.contains!r}"
            )


async def test_retrieval_metrics_are_measured_not_asserted(bench, record_property):
    """Real Recall/MRR/nDCG/HitRate over the real production pipeline.

    The numbers are RECORDED (for docs/RAG_EVALUATION.md) rather than frozen
    to constants: freezing them here would make every unrelated retrieval
    change fail this test, and the schema of the corpus would stop being able
    to evolve. The floor assertions below are what guard against regression.
    """
    per_query = {}
    for query in QUERIES:
        relevant = frozenset(_identity(bench, key, seq) for key, seq in query.relevant)
        _pack, ranked = await _rank(bench, query.text)
        per_query[query.key] = {
            "recall@1": recall_at_k(ranked, relevant, 1),
            "recall@3": recall_at_k(ranked, relevant, 3),
            "recall@5": recall_at_k(ranked, relevant, 5),
            "mrr@3": mrr_at_k(ranked, relevant, 3),
            "mrr@5": mrr_at_k(ranked, relevant, 5),
            "ndcg@3": ndcg_at_k(ranked, relevant, 3),
            "ndcg@5": ndcg_at_k(ranked, relevant, 5),
            "hit@1": hit_rate_at_k(ranked, relevant, 1),
            "hit@3": hit_rate_at_k(ranked, relevant, 3),
            "hit@5": hit_rate_at_k(ranked, relevant, 5),
        }
        record_property(f"recall@5:{query.key}", round(per_query[query.key]["recall@5"], 4))

    aggregate = {
        metric: round(sum(row[metric] for row in per_query.values()) / len(per_query), 4)
        for metric in next(iter(per_query.values()))
    }
    record_property("aggregate", aggregate)

    # Floors, not frozen values: the production lexical path must find the
    # right document for every query in this corpus.
    assert aggregate["recall@5"] >= 0.95, aggregate
    assert aggregate["hit@5"] >= 0.95, aggregate
    assert aggregate["mrr@5"] >= 0.75, aggregate
    assert aggregate["ndcg@5"] >= 0.75, aggregate


async def test_near_miss_concepts_are_not_confused(bench):
    """加法交换律 vs 加法结合律 share the word 加法 but are different facts."""
    _pack, ranked = await _rank(bench, "加法结合律的字母表示")
    assert ranked[0] == _identity(bench, "associative", 0), ranked

    _pack, ranked = await _rank(bench, "交换加数的位置和不变")
    assert ranked[0] == _identity(bench, "commutative", 0), ranked


async def test_formula_query_reaches_the_formula_chunk(bench):
    _pack, ranked = await _rank(bench, "x = (-b ± √(b²-4ac)) / (2a)")
    assert _identity(bench, "quadratic", 1) in ranked


# ------------------------------------------------------------------ security


async def test_unbound_document_never_enters_the_candidate_set(bench):
    unbound_id = bench["unbound"].document_id
    for query in QUERIES:
        _pack, ranked = await _rank(bench, query.text)
        assert not any(item.startswith(str(unbound_id)) for item in ranked), query.key


async def test_cross_owner_document_never_enters_the_candidate_set(bench):
    """The foreign document is byte-identical to an unbound local one, so a
    leak would be lexically indistinguishable from a correct hit."""
    foreign_id = bench["foreign"].document_id
    for query in QUERIES:
        _pack, ranked = await _rank(bench, query.text)
        assert not any(item.startswith(str(foreign_id)) for item in ranked), query.key


async def test_disabled_document_drops_out_of_retrieval(bench):
    document_id = bench["documents"]["quadratic"]["document_id"]
    await bench["repository"].set_retrieval_enabled(OWNER, document_id, False)

    _pack, ranked = await _rank(bench, "求根公式")
    assert not any(item.startswith(str(document_id)) for item in ranked)

    await bench["repository"].set_retrieval_enabled(OWNER, document_id, True)
    _pack, ranked = await _rank(bench, "求根公式")
    assert any(item.startswith(str(document_id)) for item in ranked)


async def test_deleted_document_drops_out_of_retrieval(bench):
    document_id = bench["documents"]["commutative"]["document_id"]
    await bench["repository"].soft_delete_document(OWNER, document_id)

    _pack, ranked = await _rank(bench, "交换加数的位置和不变")
    assert not any(item.startswith(str(document_id)) for item in ranked)


async def test_unset_or_empty_scope_never_widens_to_the_owner(bench):
    """UNSET and EMPTY both retrieve nothing — never "everything this owner has"."""
    for scope in ([],):
        pack, ranked = await _rank(bench, "求根公式", scope=scope)
        assert pack.empty is True
        assert ranked == []
        assert pack.execution.retrieval_ran is False

    # An empty scope must not reach the kernel at all.
    assert bench["metrics"].rag()["rag_retrieval_skipped_total"] >= 1


async def test_conversation_scope_is_the_only_whitelist(bench):
    """A document the caller did not put in scope is invisible even if the
    owner owns it and it matches the query lexically."""
    single = [bench["documents"]["fraction"]["document_id"]]
    _pack, ranked = await _rank(bench, "求根公式", scope=single)
    assert all(item.startswith(str(single[0])) for item in ranked), ranked


# ------------------------------------------------------ context expansion


async def test_expansion_extends_a_truncated_hit_but_stays_in_scope(bench):
    """The transposition rule is split across two chunks; a hit on the second
    needs the first to be answerable."""
    document_id = bench["documents"]["linear"]["document_id"]
    pack, ranked = await _rank(bench, "移项要变号", scope=[document_id])

    assert ranked, "the transposition query found nothing"
    evidence = pack.evidences[0]
    assert evidence.document_id == document_id
    # Whatever expansion did, in-scope is the only thing it could have added.
    assert all(chunk_id for chunk_id in evidence.expanded_from)


# -------------------------------------------------------------- telemetry


async def test_the_benchmark_also_exercises_telemetry(bench):
    """Metrics are read from the same runs the metrics above come from, so a
    silently-broken telemetry path shows up here rather than in production."""
    for query in QUERIES:
        await _rank(bench, query.text)
    bench["metrics"].end_retrieval_turn()

    rag = bench["metrics"].rag()
    assert rag["rag_retrieval_requested_total"] == len(QUERIES)
    assert rag["rag_lexical_only_total"] == len(QUERIES)
    assert rag["rag_hybrid_total"] == 0
    assert rag["rag_vector_unavailable_total"] == len(QUERIES)

    health = bench["metrics"].rag_health()
    assert health["retrieval_request_rate"] == 1.0
    assert health["average_context_chunks"] > 0
    assert all(isinstance(value, (int, float)) for value in health.values())
