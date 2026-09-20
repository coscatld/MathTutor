"""F2 hard-set: run the REAL ingestion path, then the REAL retrieval pipeline.

Order matters and is deliberate:

    1. ingest   — real DocumentIngestionService → real parser → real TextChunker
    2. manifest  — what the chunker ACTUALLY produced (boundaries, parent links,
                   heading paths, sections)
    3. anchors   — ground-truth facts bound to REAL chunk identities from (2),
                   each anchor carrying the verbatim substring it claims
    4. selfcheck — structural preconditions are verified BEFORE any metric is
                   computed; a failure is BENCHMARK_INVALID, never a pretty number
    5. queries   — run through the shared ConversationRetrievalOrchestrator
    6. artefact  — machine-readable JSON with the ACTUAL selected context

Ground truth is written AFTER the manifest and never adjusted to match what
retrieval returned. If the chunker does not produce the boundary a case needs,
the FIXTURE TEXT is changed — not the chunker, and never the ground truth.

Selected context is the union of each evidence's own ``chunk_id`` and every id
in ``expanded_from``: expansion is a change to what the model sees, so it must
count toward precision and recall rather than hiding behind the original hit.

Usage::

    python scripts/rag_hard_set_probe.py              # human manifest summary
    python scripts/rag_hard_set_probe.py --json       # machine-readable manifest
    python scripts/rag_hard_set_probe.py --evaluate   # run queries, write artefact
    python scripts/rag_hard_set_probe.py --evaluate --json   # artefact on stdout
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mathtutor.application.context_expansion import (  # noqa: E402
    MAX_EXPANDED_ITEMS,
    MAX_EXPANSION_CHARS,
    NEIGHBOUR_RADIUS,
    ContextExpander,
)
from mathtutor.application.desktop_files import PickedFile  # noqa: E402
from mathtutor.application.document_ingestion import (  # noqa: E402
    DocumentIndexManager,
    DocumentIngestionService,
)
from mathtutor.application.rerank import ProductionReranker, RerankedHit  # noqa: E402
from mathtutor.application.retrieval_orchestrator import (  # noqa: E402
    DEFAULT_CANDIDATE_LIMIT,
    DEFAULT_EVIDENCE_LIMIT,
    ConversationRetrievalOrchestrator,
)
from mathtutor.domain.evidence import (  # noqa: E402
    MAX_EVIDENCE_CHARS,
    MAX_EVIDENCE_ITEMS,
    MAX_PER_ITEM_CHARS,
)
from mathtutor.infrastructure.chunking import TextChunker  # noqa: E402
from mathtutor.infrastructure.db import create_db_engine  # noqa: E402
from mathtutor.infrastructure.document_storage import DocumentStorage  # noqa: E402
from mathtutor.infrastructure.embedding_runtime import EmbeddingRuntime  # noqa: E402
from mathtutor.infrastructure.lexical import lexical_score, tokenize_lexical  # noqa: E402
from mathtutor.infrastructure.migrate import upgrade_db  # noqa: E402
from mathtutor.infrastructure.observability import MathTutorMetrics  # noqa: E402
from mathtutor.repositories.sqlite_knowledge import SQLiteDocumentRepository  # noqa: E402

OWNER = "hard-owner"
#: A second owner whose document is byte-identical to `disc`. Retrieval scoped
#: to OWNER must never surface it — the check is only meaningful because the
#: text is identical, so a leak cannot be blamed on the content differing.
OTHER_OWNER = "hard-owner-other"

ARTEFACT_PATH = ROOT / "artifacts" / "rag-evaluation.json"

TERMINAL_CHARS = "。！？；：.!?;:）)」』】\"]"


class BenchmarkInvalid(Exception):
    """Raised when the fixture cannot support the claims the metrics make."""


# ------------------------------------------------------------ run provenance

#: Bumped by hand when a fixture changes in a way that moves the numbers.
#: Deliberately NOT derived from a hash of the text: a version that moved on
#: every whitespace edit would make "same version, different result" impossible
#: to state, which is the only thing a version is for.
CORPUS_VERSION = "hard-corpus/2"
ANNOTATION_VERSION = "hard-annotations/3"
#: Every metric definition in this file. Bump when a denominator changes.
SCORER_VERSION = "hard-scorer/2"


def _digest(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    return sha256(path.read_bytes()).hexdigest()[:16]


def _tree_digest(directory: Path) -> str:
    """Digest of every ``.py`` under a tree, path-and-content.

    The point is to make "which code produced these numbers" answerable. A git
    sha is not enough: this working tree has uncommitted production changes, so
    the commit would name code that never ran.
    """
    if not directory.exists():
        return "MISSING"
    accumulator = sha256()
    for path in sorted(directory.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        accumulator.update(path.relative_to(directory).as_posix().encode())
        accumulator.update(sha256(path.read_bytes()).hexdigest().encode())
    return accumulator.hexdigest()[:16]


def source_fingerprint() -> dict:
    from mathtutor.infrastructure.chunking import CHUNKER_VERSION

    chunker = TextChunker()
    return {
        "git_head": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "working_tree_dirty": bool(_git("status", "--porcelain")),
        "production_source_digest": _tree_digest(ROOT / "src" / "mathtutor"),
        "probe_script_digest": _digest(Path(__file__)),
        "official_benchmark_digest": _digest(ROOT / "tests" / "test_rag_production_benchmark.py"),
        "chunker_version": CHUNKER_VERSION,
        "corpus_version": CORPUS_VERSION,
        "annotation_version": ANNOTATION_VERSION,
        "scorer_version": SCORER_VERSION,
    }


def _git(*args: str) -> str:
    try:
        import subprocess

        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def budgets() -> dict:
    """Every bound that can move a number, read from the code, not restated."""
    chunker = TextChunker()
    return {
        "candidate_limit": DEFAULT_CANDIDATE_LIMIT,
        "evidence_limit": DEFAULT_EVIDENCE_LIMIT,
        "max_evidence_items": MAX_EVIDENCE_ITEMS,
        "max_evidence_chars": MAX_EVIDENCE_CHARS,
        "max_per_item_chars": MAX_PER_ITEM_CHARS,
        "max_expanded_items": MAX_EXPANDED_ITEMS,
        "max_expansion_chars": MAX_EXPANSION_CHARS,
        "expansion_neighbour_radius": NEIGHBOUR_RADIUS,
        "chunker_max_chunk_chars": chunker.max_chunk_chars,
        "chunker_min_chunk_chars": chunker.min_chunk_chars,
        "chunker_overlap_chars": chunker.overlap_chars,
        "counting_unit": "chunk identity (document_key, sequence)",
        "note": (
            "Metrics here are CHUNK-weighted, never token-weighted. A 988-char "
            "chunk and an 18-char chunk each count as one. Nothing in this "
            "artefact may be re-read as a per-token or per-character rate."
        ),
    }


# --------------------------------------------------------------------- corpus


@dataclass(frozen=True)
class Doc:
    key: str
    filename: str
    body: str


#: C1/C2 need ONE section long enough that the chunker splits it. `_split_group_text`
#: only engages above `max_chunk_chars` (1000), and when it does, pieces are split
#: on sentence punctuation that is CONSUMED — so the pieces do not end in 。 and
#: `needs_expansion` fires. That is what makes neighbour restoration reachable.
_FILLER = (
    "在解一元二次方程的过程中，先观察二次项系数是否为零。"
    "若二次项系数为零，则方程退化为一次方程，处理方式随之改变。"
    "配方时需要保持等式两边同时变化，这一步最容易出现符号错误。"
    "因式分解法适用于能够直接看出因式的情形。"
    "使用公式法之前应当先把方程化为一般形式。"
)


def _long_section(heading: str, opening: str, closing: str) -> str:
    # Two constraints must hold together, and the first manifest run showed
    # neither did: the group must exceed ``max_chunk_chars`` (1000) or
    # `_split_group_text` returns it whole, AND the tail piece must stay above
    # ``min_chunk_chars`` (80) or `_merge_short_pieces` folds it back, undoing
    # the split. ~1400 characters satisfies both, landing the applicable-object
    # half and the definition half in DIFFERENT chunks of ONE section.
    block = opening * 10 + _FILLER * 8
    return f"## {heading}\n\n{block}\n{closing}\n"


#: C5 needs a section boundary INSIDE ONE DOCUMENT. The earlier note in the
#: recovery zone called the `weida` document a cross-section neighbour, but
#: `ContextExpander` reads neighbours through `list_chunk_neighbourhood` keyed
#: on the matched chunk's document_id, so two documents can never neighbour
#: each other — that fixture could not have failed the check it was meant to
#: test. Cross-document adjacency is not the hazard; the hazard is the last
#: chunk of section A sitting next to the first chunk of section B of the SAME
#: file. `_C5_FILLER` exists to build that situation for real.
_C5_FILLER = (
    "完全平方公式指出两数和的平方等于这两数的平方和加上它们乘积的两倍。"
    "运用完全平方公式时，中间的乘积项不能漏掉，这是最常见的展开错误。"
    "当两项符号相反时，完全平方公式的中间项应当取负号。"
    "完全平方公式常与提取公因式一起使用以便简化计算。"
)


#: C4 needs its own section text, split into THREE pieces: two relevant ones
#: followed by a lexically similar but IRRELEVANT one that sits in the SAME
#: section. That is the whole point — the expander pulls same-section
#: neighbours unconditionally, so C4 is the case where a legitimate-looking
#: expansion is still a precision loss. Chunking only cuts above
#: ``max_chunk_chars``, so the relevant half is written long enough to yield
#: two chunks, and the distractor is long enough that it survives
#: ``_merge_short_pieces`` as a chunk of its own rather than a 100-character
#: overlap remnant.
_C4_RELEVANT_OPENING = "完全平方公式把两数之和的平方展开为三项之和，"
_C4_RELEVANT_BODY = (
    "展开结果里第一项是第一个数的平方，最后一项是第二个数的平方。"
    "中间的一项是两数乘积的两倍，这一项最容易被漏写。"
    "完全平方公式在配方与因式分解中反复出现。"
    "当两个数符号相反时，中间项应当取负号。"
)
#: Lexically adjacent to the query's vocabulary — 平方, 公式, 两数, 展开, 结果
#: all recur — while answering a different question.
_C4_DISTRACTOR = (
    "定义： 平方差公式描述的是两数之和与两数之差的乘积。"
    "平方差公式的展开结果只有两项，并不存在中间的那一项。"
    "使用平方差公式之前要先确认两个二项式只有符号不同。"
    "平方差公式与完全平方公式的名字相近，展开结果却相差一项。"
)


def _c4_section() -> str:
    # The distractor opens its own GROUP — a line beginning with 「定义」 is a
    # structural marker to the chunker — while inheriting the SAME
    # ``heading_path``. That is what makes this C4 and not C5: the expander's
    # ``_same_section`` gate compares heading paths, so it will pull this
    # neighbour in. Length tuning was tried first and abandoned: the greedy
    # packer absorbs as many following sentences as fit, so a same-section
    # boundary cannot be placed by character count.
    #
    # The separate group also means NO overlap window is prepended, so the
    # chunk is purely the distractor rather than 100 characters of the answer
    # followed by it.
    return (
        "## 乘法公式\n\n"
        + _C4_RELEVANT_OPENING * 12
        + _C4_RELEVANT_BODY * 8
        + "\n"
        + _C4_DISTRACTOR
        + "\n"
    )


#: Corpus filler. Context precision is only meaningful when a pack CANNOT hold
#: the whole corpus, so the hard set needs more chunks than ``evidence_limit``.
#: These documents are ordinary course material on purpose: padding the corpus
#: with text that could never match would make precision look good for the
#: wrong reason. They overlap the query vocabulary wherever the maths genuinely
#: does.
_FILLER_DOCS: tuple[Doc, ...] = (
    Doc(
        "linear",
        "一元一次方程.md",
        "## 等式的基本性质\n\n"
        "等式两边同时加上或减去同一个数，等式仍然成立。\n\n"
        "## 移项\n\n"
        "移项的依据是等式的基本性质，把某一项从等式的一边移到另一边时需要改变符号。\n",
    ),
    Doc(
        "fraction",
        "分式方程.md",
        "## 去分母\n\n"
        "解分式方程的第一步通常是去分母，两边同乘各分母的最简公分母。\n\n"
        "## 增根\n\n"
        "去分母可能引入使最简公分母为零的根，因此解分式方程之后必须验根。\n",
    ),
    Doc(
        "inequality",
        "一元一次不等式.md",
        "## 不等式的基本性质\n\n"
        "不等式两边同时乘以或除以同一个负数时，不等号的方向必须改变。\n\n"
        "## 解集\n\n"
        "一元一次不等式的解集通常在数轴上用区间表示，端点是否包含要用空心点区分。\n",
    ),
)


HARD_DOCS: tuple[Doc, ...] = (
    Doc("neighbour", "乘法公式.md", _c4_section()),
    Doc(
        "disc",
        "判别式.md",
        # C1: the applicable object and the definition must be separable, so the
        # opening is repeated to push the definition past a chunk boundary.
        _long_section(
            "判别式",
            "对于一元二次方程 ax^2+bx+c=0，其中 a 不等于零，",
            "判别式定义为 Δ = b^2 - 4ac，它决定方程实数根的个数",
        ),
    ),
    Doc(
        "example",
        "例题.md",
        # C3: `例1` opens an example group; `解：` attaches to it as a CHILD
        # (parse_adapters/chunking role logic) provided it is long enough not to
        # be merged back by _merge_tiny_solutions.
        "## 例题\n\n"
        "例1：解方程 2x + 3 = 7。\n\n"
        # The solution must stay ABOVE min_chunk_chars (80) or
        # _merge_tiny_solutions folds it back into the example, and the
        # child->parent relation this case exists to test never forms.
        "解：两边同时减去 3，得到 2x = 4，这一步依据等式的基本性质中两边同时减去同一个数等式仍成立；"
        "再同时除以 2，得到 x = 2，这一步依据等式两边同时除以同一个不为零的数等式仍成立。\n",
    ),
    Doc(
        "boundary",
        "完全平方公式.md",
        # C5: TWO sections in ONE file. Section one is long enough to split, so
        # its last chunk is sequence-adjacent to section two's only chunk; the
        # expander must refuse that neighbour because `sequence` adjacency is a
        # storage fact and not a semantic one.
        _long_section(
            "完全平方公式",
            "完全平方公式是整式乘法中最基本的一个公式，",
            "完全平方公式的展开结果里，首末两项分别是两数的平方，中间项是两数乘积的两倍",
        )
        + "\n## 分母有理化\n\n"
        "分母有理化指把分母中的根号去掉，通常通过分子分母同乘分母的有理化因式来完成。\n",
    ),
    Doc(
        "weida",
        "韦达定理.md",
        # Retained as a corpus-level lexical distractor: same 一元二次方程
        # topic, different question. Not a C5 fixture — see the note on
        # `_C5_FILLER`.
        "## 韦达定理\n\n"
        "韦达定理描述一元二次方程根与系数的关系：x1 + x2 = -b/a，x1 * x2 = c/a。\n",
    ),
) + _FILLER_DOCS


# ------------------------------------------------ ground truth (pre-retrieval)


@dataclass(frozen=True)
class Anchor:
    """One ground-truth fact, bound to a real chunk AND to verbatim text.

    ``must_contain`` is the part of the claim that must literally appear in the
    named chunk. Binding both means a fixture edit that moves the fact to a
    different chunk is caught before any metric is computed, instead of quietly
    turning a correct retrieval into a reported miss.
    """

    key: str
    doc: str
    sequence: int
    must_contain: str


ANCHORS: tuple[Anchor, ...] = (
    Anchor(
        "disc.applicable_object",
        "disc",
        0,
        "对于一元二次方程 ax^2+bx+c=0，其中 a 不等于零",
    ),
    Anchor("disc.definition", "disc", 1, "判别式定义为 Δ = b^2 - 4ac"),
    Anchor("example.stem", "example", 0, "例1：解方程 2x + 3 = 7"),
    Anchor("example.solution", "example", 1, "两边同时减去 3，得到 2x = 4"),
    Anchor("example.solution_final", "example", 1, "得到 x = 2"),
    Anchor("boundary.square_first", "boundary", 0, "完全平方公式是整式乘法中最基本的一个公式"),
    Anchor("boundary.square_middle", "boundary", 1, "中间项是两数乘积的两倍"),
    Anchor("boundary.rationalize", "boundary", 2, "分母有理化指把分母中的根号去掉"),
    # C4: three chunks of ONE section. The first two carry the answer; the
    # third is the neighbour the expander will pull in and should not credit.
    Anchor("neighbour.relevant_head", "neighbour", 0, "完全平方公式把两数之和的平方展开为三项之和"),
    Anchor("neighbour.relevant_tail", "neighbour", 1, "完全平方公式在配方与因式分解中反复出现"),
    Anchor("neighbour.distractor", "neighbour", 2, "平方差公式的展开结果只有两项"),
)

#: Annotation policy, stated once so the numbers are readable without the code.
ANNOTATION_POLICY = {
    "required": (
        "A chunk is REQUIRED when the answer cannot be correct without its "
        "content: a definition, a stem the solution refers to, or the half of "
        "the answer that sits across a chunk boundary."
    ),
    "relevant": (
        "A chunk is RELEVANT when it materially supports the answer. Required "
        "chunks are always relevant (enforced by self-check), so "
        "required is a subset of relevant by construction."
    ),
    "forbidden": (
        "A chunk is FORBIDDEN when the CONTEXT EXPANDER must never pull it in — "
        "a section-adjacent chunk reached on sequence adjacency alone. Forbidden "
        "chunks are never in `relevant`."
    ),
    "distractor": (
        "A chunk that is lexically similar to the query, is NOT relevant, and "
        "IS expected to be swept in — the same-section neighbour C4 exists to "
        "expose. Its presence is priced into context precision and is NOT an "
        "expansion leak; the expander is behaving as specified. This is the "
        "mirror of `forbidden`, where the guard must refuse."
    ),
    "forbidden_scoring": (
        "A forbidden chunk that appears in `expanded_from` is an EXPANSION LEAK "
        "(the C5 guard failed). A forbidden chunk that the kernel matched on its "
        "own is RETRIEVAL NOISE, which is a different defect and is priced into "
        "context precision rather than into the C5 guard. Conflating the two "
        "would either hide a real expansion bug or libel a working guard."
    ),
    "redundant_coverage": (
        "`required` names the chunks of the query's primary document that carry "
        "the answer. When another document repeats the same fact — which a "
        "corpus that revisits a topic does naturally — those chunks are added "
        "to `relevant` but not to `required`: they can satisfy the answer, and "
        "counting one of them as missing would be wrong. `required` is "
        "therefore a floor for recall, not a partition."
    ),
    "authored_before_retrieval": (
        "Every label above was written from the fixture text and the manifest, "
        "before any query ran. Retrieval results never feed back into labels."
    ),
}


@dataclass(frozen=True)
class QueryCase:
    key: str
    text: str
    case: str
    required: tuple[str, ...]
    relevant: tuple[str, ...]
    forbidden: tuple[str, ...] = ()
    #: Lexically similar, NOT relevant, and EXPECTED to be swept in by
    #: expansion. Deliberately separate from ``forbidden``: the C5 guard is
    #: supposed to refuse its neighbour, while the C4 same-section rule is
    #: supposed to accept this one and take the precision hit. Sharing a label
    #: would have reported a working C4 as an expansion leak.
    distractor: tuple[str, ...] = ()
    #: Ground-truth annotation: the answer cannot be assembled from the
    #: directly-matched chunk alone, so this query belongs to the
    #: expansion-required subset. Annotated, never inferred from results.
    expansion_required: bool = False


QUERY_CASES: tuple[QueryCase, ...] = (
    QueryCase(
        key="Q01",
        text="判别式的定义是什么，它适用于什么样的方程",
        case="C1",
        # The definition sits in the LAST chunk of the section; what it applies
        # to sits in the chunk before it. Answering needs both halves.
        required=("disc.definition", "disc.applicable_object"),
        relevant=("disc.definition", "disc.applicable_object"),
        expansion_required=True,
    ),
    QueryCase(
        key="Q02",
        text="解方程 2x + 3 = 7 的完整步骤是什么",
        case="C3",
        # The solution chunk is a CHILD: its text never names the equation.
        required=("example.solution", "example.stem"),
        relevant=("example.solution", "example.stem", "example.solution_final"),
        expansion_required=True,
    ),
    QueryCase(
        key="Q03",
        text="完全平方公式展开后的中间项是什么",
        case="C5",
        required=("boundary.square_middle",),
        # `neighbour` also covers 完全平方公式, so its first two chunks carry
        # the answer too. A corpus that repeats a topic produces a genuinely
        # multi-document relevant set; omitting them would have scored a
        # correct retrieval as imprecise.
        relevant=(
            "boundary.square_first",
            "boundary.square_middle",
            "neighbour.relevant_head",
            "neighbour.relevant_tail",
        ),
        # Sequence-adjacent to the last chunk of section one, but a different
        # section: pulling it in is a defect.
        forbidden=("boundary.rationalize",),
        expansion_required=False,
    ),
    QueryCase(
        key="Q04",
        text="完全平方公式展开之后中间的那一项是什么",
        case="C4",
        # N-1 and N carry the answer; N+1 shares 平方/公式/两数/展开/结果 with
        # the query while answering a different question. The expander WILL
        # pull it in — same section, contiguous sequence — and precision is
        # supposed to take the hit.
        required=("neighbour.relevant_head", "neighbour.relevant_tail"),
        relevant=(
            "neighbour.relevant_head",
            "neighbour.relevant_tail",
            "boundary.square_first",
            "boundary.square_middle",
        ),
        distractor=("neighbour.distractor",),
        expansion_required=True,
    ),
    QueryCase(
        key="Q05",
        text="对于一元二次方程 ax^2+bx+c=0，其中 a 不等于零是为什么",
        case="C2",
        # The applicable object is stated in the FIRST chunk; the definition it
        # exists to introduce sits in the next one. Matching the earlier chunk
        # is what makes this C2 rather than C1.
        required=("disc.applicable_object", "disc.definition"),
        relevant=("disc.applicable_object", "disc.definition"),
        expansion_required=True,
    ),
)


# ------------------------------------------------------------------- harness


@dataclass
class Manifest:
    document_id: UUID
    chunks: list = field(default_factory=list)

    def by_sequence(self, sequence: int):
        for chunk in self.chunks:
            if chunk.sequence == sequence:
                return chunk
        raise BenchmarkInvalid(f"no chunk at sequence {sequence}")


async def _ingest_all(service, repository, owner: str, docs) -> dict[str, Manifest]:
    manifest: dict[str, Manifest] = {}
    for doc in docs:
        ingested = await service.ingest(
            owner,
            PickedFile(
                filename=doc.filename, mime_type="text/markdown", data=doc.body.encode("utf-8")
            ),
        )
        chunks = sorted(
            await repository.list_chunks(owner, ingested.document_id),
            key=lambda chunk: chunk.sequence,
        )
        manifest[doc.key] = Manifest(document_id=ingested.document_id, chunks=chunks)
    return manifest


async def build(tmp: Path) -> dict:
    db = tmp / "hard.db"
    upgrade_db(str(db))
    engine = create_db_engine(db)
    repository = SQLiteDocumentRepository(engine)
    service = DocumentIngestionService(
        repository=repository,
        storage=DocumentStorage(tmp / "data"),
        index_manager=DocumentIndexManager(
            repository=repository, embedding_runtime=EmbeddingRuntime()
        ),
    )

    manifest = await _ingest_all(service, repository, OWNER, HARD_DOCS)
    other_manifest = await _ingest_all(
        service, repository, OTHER_OWNER, tuple(doc for doc in HARD_DOCS if doc.key == "disc")
    )

    metrics = MathTutorMetrics()
    kernel = DocumentIndexManager(repository=repository, embedding_runtime=EmbeddingRuntime())
    orchestrator = ConversationRetrievalOrchestrator(
        kernel=kernel,
        reranker=ProductionReranker(),
        expander=ContextExpander(repository),
        metrics=metrics,
    )
    return {
        "engine": engine,
        "repository": repository,
        "kernel": kernel,
        "manifest": manifest,
        "other_manifest": other_manifest,
        "orchestrator": orchestrator,
        "metrics": metrics,
        "scope": [m.document_id for m in manifest.values()],
    }


def manifest_rows(manifest: dict[str, Manifest]) -> list[dict]:
    rows: list[dict] = []
    for key, entry in manifest.items():
        for chunk in entry.chunks:
            rows.append(
                {
                    "doc": key,
                    "document_id": str(entry.document_id),
                    "chunk_id": str(chunk.chunk_id),
                    "sequence": chunk.sequence,
                    "chunk_type": chunk.chunk_type,
                    "section": chunk.section,
                    "heading_path": list(chunk.heading_path),
                    "parent_chunk_id": str(chunk.parent_chunk_id) if chunk.parent_chunk_id else None,
                    "chars": len(chunk.text),
                    "ends_terminal": chunk.text.rstrip()[-1:] in TERMINAL_CHARS,
                    "preview": chunk.text.strip().replace("\n", " ")[:60],
                }
            )
    return rows


# ------------------------------------------------------------ ground truth IO


class Truth:
    """Anchors resolved against the REAL manifest."""

    def __init__(
        self,
        manifest: dict[str, Manifest],
        anchors: tuple[Anchor, ...],
        other_manifest: dict[str, Manifest] | None = None,
    ) -> None:
        self.manifest = manifest
        self.other_manifest = other_manifest or {}
        self.anchors = {anchor.key: anchor for anchor in anchors}
        self.chunk_id: dict[str, UUID] = {}
        self.location: dict[UUID, tuple[str, int]] = {}
        for key, entry in manifest.items():
            for chunk in entry.chunks:
                self.location[chunk.chunk_id] = (key, chunk.sequence)

    def chunk(self, anchor_key: str):
        anchor = self.anchors.get(anchor_key)
        if anchor is None:
            raise BenchmarkInvalid(f"undeclared anchor {anchor_key!r}")
        if anchor.doc not in self.manifest:
            raise BenchmarkInvalid(f"anchor {anchor_key!r} names unknown document {anchor.doc!r}")
        return self.manifest[anchor.doc].by_sequence(anchor.sequence)

    def key_of(self, chunk_id: UUID) -> tuple[str, int] | None:
        return self.location.get(chunk_id)


def run_selfcheck(truth: Truth, cases: tuple[QueryCase, ...]) -> list[dict]:
    """Every claim the metrics will make, verified before any metric is run."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    for key, entry in truth.manifest.items():
        check(
            f"documents_have_chunks[{key}]",
            bool(entry.chunks),
            f"{len(entry.chunks)} chunks",
        )

    for anchor in truth.anchors.values():
        try:
            chunk = truth.chunk(anchor.key)
        except BenchmarkInvalid as error:
            check(f"anchor_exists[{anchor.key}]", False, str(error))
            continue
        check(
            f"anchor_exists[{anchor.key}]",
            True,
            f"{anchor.doc} seq={anchor.sequence} chunk_id={chunk.chunk_id}",
        )
        check(
            f"anchor_text_present[{anchor.key}]",
            anchor.must_contain in chunk.text,
            f"{anchor.must_contain[:24]!r} in {len(chunk.text)} chars",
        )

    for case in cases:
        required = set(case.required)
        relevant = set(case.relevant)
        forbidden = set(case.forbidden)
        check(
            f"required_subset_of_relevant[{case.key}]",
            required <= relevant,
            f"required={sorted(required)} relevant={sorted(relevant)}",
        )
        check(
            f"forbidden_disjoint_from_relevant[{case.key}]",
            not (forbidden & relevant),
            f"forbidden={sorted(forbidden)}",
        )
        check(
            f"relevant_is_non_empty[{case.key}]",
            bool(relevant),
            f"{len(relevant)} labelled chunks",
        )
        check(
            f"distractor_disjoint_from_relevant[{case.key}]",
            not (set(case.distractor) & relevant),
            f"distractor={sorted(case.distractor)}",
        )
        for anchor_key in required | relevant | forbidden | set(case.distractor):
            check(
                f"label_resolves[{case.key}:{anchor_key}]",
                anchor_key in truth.anchors,
                f"{anchor_key!r} is a declared anchor",
            )

    # --- security fixture is a REAL fixture -----------------------------
    if truth.other_manifest:
        own = truth.manifest["disc"].chunks
        foreign = truth.other_manifest["disc"].chunks
        check(
            "isolation_foreign_document_exists",
            bool(foreign),
            f"{len(foreign)} chunks ingested under {OTHER_OWNER}",
        )
        # The probe is only worth running if the two documents are the same
        # content: otherwise a leak could be dismissed as "the texts differed".
        check(
            "isolation_foreign_text_is_identical",
            bool(foreign) and [c.text for c in own] == [c.text for c in foreign],
            "chunk-for-chunk identical text across owners",
        )
        check(
            "isolation_identities_are_distinct",
            {c.chunk_id for c in own}.isdisjoint({c.chunk_id for c in foreign}),
            "no shared chunk ids between owners",
        )
    else:
        check("isolation_foreign_document_exists", False, "no foreign owner ingested")

    # --- one case per label, or the dispatch below silently drops one -----
    labels = [case.case for case in cases]
    check(
        "case_labels_are_unique",
        len(labels) == len(set(labels)),
        f"{labels}",
    )

    # --- per-case structural truths -------------------------------------
    by_case = {case.case: case for case in cases}
    for case_name, probe in (
        ("C1", _check_neighbour_pair),
        ("C2", _check_neighbour_pair),
        ("C3", _check_parent_child),
        ("C4", _check_c4),
        ("C5", _check_cross_section),
    ):
        if case_name not in by_case:
            check(f"{case_name}_case_present", False, f"no query annotated {case_name}")
            continue
        try:
            probe(truth, by_case[case_name], check)
        except BenchmarkInvalid as error:
            # A structural probe that cannot even run is a FAILED check, not a
            # crash: the caller has to end up with BENCHMARK_INVALID and no
            # numbers, which is exactly what a traceback would prevent.
            check(f"{case_name}_probe_ran", False, str(error))

    return checks


def _resolve(truth: Truth, keys) -> list:
    return [truth.chunk(key) for key in keys]


def _check_neighbour_pair(truth, case, check) -> None:
    """C1: the answer straddles a chunk boundary inside ONE section."""
    chunks = _resolve(truth, case.required)
    check(
        f"C1_two_distinct_chunks[{case.key}]",
        len(chunks) == 2 and chunks[0].chunk_id != chunks[1].chunk_id,
        f"{len(chunks)} required chunks",
    )
    if len(chunks) != 2:
        return
    lower, upper = sorted(chunks, key=lambda chunk: chunk.sequence)
    check(
        f"C1_same_section[{case.key}]",
        lower.heading_path == upper.heading_path and bool(lower.heading_path),
        f"{lower.heading_path} vs {upper.heading_path}",
    )
    check(
        f"C1_sequence_adjacent[{case.key}]",
        upper.sequence == lower.sequence + 1,
        f"seq {lower.sequence} -> {upper.sequence}",
    )
    # The boundary is only something the expander can be asked to mend if the
    # chunk on the far side LOOKS cut off — that is the real trigger.
    check(
        f"C1_boundary_is_reachable[{case.key}]",
        bool(upper.text.rstrip()) and upper.text.rstrip()[-1] not in TERMINAL_CHARS,
        f"upper chunk ends {upper.text.rstrip()[-1:]!r}",
    )


def _check_parent_child(truth, case, check) -> None:
    """C3: the solution chunk names a parent that is a DIFFERENT, earlier chunk."""
    solved = [truth.chunk(key) for key in case.required if key.endswith("solution")]
    stems = [truth.chunk(key) for key in case.required if key.endswith("stem")]
    if not solved or not stems:
        check(f"C3_stem_and_solution[{case.key}]", False, "missing stem or solution anchor")
        return
    child, stem = solved[0], stems[0]
    check(
        f"C3_child_has_parent[{case.key}]",
        child.parent_chunk_id is not None,
        f"parent_chunk_id={child.parent_chunk_id}",
    )
    check(
        f"C3_parent_is_the_stem[{case.key}]",
        child.parent_chunk_id == stem.chunk_id,
        f"child.parent={child.parent_chunk_id} stem={stem.chunk_id}",
    )
    check(
        f"C3_parent_precedes_child[{case.key}]",
        stem.sequence < child.sequence,
        f"stem seq={stem.sequence} child seq={child.sequence}",
    )


#: The fact the C4 query asks for. The distractor must NOT contain it, or the
#: label "irrelevant" would be wrong no matter how the retrieval turned out.
C4_ANSWER_PHRASE = "两数乘积的两倍"


def _check_c4(truth, case, check) -> None:
    """C4: a same-section neighbour that is lexically similar yet unhelpful.

    Three things are verified independently, because "the distractor is
    irrelevant" is a compound claim and only the last part is about relevance:

    1. it is sequence-adjacent to a relevant chunk            (a neighbour),
    2. it shares the query's vocabulary                        (confusable),
    3. it does NOT contain the fact the query asks for         (irrelevant).

    (2) is what separates a real distractor from obviously unrelated filler —
    filler would make precision look good for the wrong reason.
    """
    relevant = _resolve(truth, case.required)
    check(
        f"C4_has_relevant_chunks[{case.key}]",
        bool(relevant),
        f"{len(relevant)} required chunks",
    )
    if not relevant:
        return
    last = max(relevant, key=lambda chunk: chunk.sequence)
    neighbours = _resolve(truth, case.distractor)
    check(
        f"C4_distractor_is_labelled[{case.key}]",
        len(neighbours) == 1,
        f"{len(neighbours)} distractor chunks labelled",
    )
    if len(neighbours) != 1:
        return
    distractor = neighbours[0]

    check(
        f"C4_distractor_same_section[{case.key}]",
        distractor.heading_path == last.heading_path and bool(distractor.heading_path),
        f"{distractor.heading_path} vs {last.heading_path}",
    )
    check(
        f"C4_distractor_adjacent[{case.key}]",
        distractor.sequence == last.sequence + 1,
        f"seq {last.sequence} -> {distractor.sequence}",
    )
    tokens = tokenize_lexical(case.text)
    distractor_coverage = lexical_score(distractor.text, tokens)
    relevant_coverage = lexical_score(last.text, tokens)
    check(
        f"C4_distractor_shares_vocabulary[{case.key}]",
        relevant_coverage > 0 and distractor_coverage >= 0.5 * relevant_coverage,
        f"coverage distractor={distractor_coverage:.3f} vs relevant={relevant_coverage:.3f}",
    )
    check(
        f"C4_distractor_lacks_the_answer[{case.key}]",
        C4_ANSWER_PHRASE not in distractor.text,
        f"{C4_ANSWER_PHRASE!r} absent from the distractor",
    )


def _check_cross_section(truth, case, check) -> None:
    """C5: the forbidden chunk is sequence-adjacent but in a DIFFERENT section."""
    for forbidden_key in case.forbidden:
        anchor = truth.anchors.get(forbidden_key)
        if anchor is None:
            check(f"C5_forbidden_resolves[{case.key}:{forbidden_key}]", False, "undeclared anchor")
            continue
        forbidden = truth.chunk(forbidden_key)
        check(
            f"C5_forbidden_resolves[{case.key}:{forbidden_key}]",
            True,
            f"{anchor.doc} seq={forbidden.sequence}",
        )
        predecessors = [
            truth.chunk(key)
            for key in case.relevant
            if truth.anchors[key].doc == anchor.doc
            and truth.chunk(key).sequence + 1 == forbidden.sequence
        ]
        check(
            f"C5_is_sequence_adjacent[{case.key}:{forbidden_key}]",
            bool(predecessors),
            f"predecessor sequences={[c.sequence for c in predecessors]}",
        )
        check(
            f"C5_is_a_different_section[{case.key}:{forbidden_key}]",
            all(c.heading_path != forbidden.heading_path for c in predecessors),
            f"{[c.heading_path for c in predecessors]} vs {forbidden.heading_path}",
        )


# ------------------------------------------------------------------- metrics


def _ngram_redundancy_counts(texts, n: int = 4) -> dict:
    """Character n-gram repetition across the selected text, WITH its counts.

    A bare rate hides what it is made of. The counts are what let a reader see
    that a high RR here comes from a small number of long repeated passages
    (the chunker's overlap window and repeated fixture phrasing) rather than
    from many lightly-similar chunks.
    """
    grams: list[str] = []
    for text in texts:
        compact = "".join((text or "").split())
        grams.extend(compact[i : i + n] for i in range(max(0, len(compact) - n + 1)))
    total = len(grams)
    distinct = len(set(grams))
    return {
        "rate": 1.0 - distinct / total if total else 0.0,
        "total": total,
        "distinct": distinct,
        "duplicate": total - distinct,
        "n": n,
    }


def _shared_characters(texts) -> dict:
    """Characters in selected chunks that also appear in ANOTHER selected chunk.

    This is the mechanism behind a high RR: adjacent pieces of one section
    repeat a fixed character window verbatim, so expanding a hit can add a
    whole chunk whose opening is a copy.
    """
    total = sum(len(text or "") for text in texts)
    counted = 0
    for index, text in enumerate(texts):
        compact = text or ""
        for other_index, other in enumerate(texts):
            if index == other_index or not other:
                continue
            # Longest prefix/suffix overlap is what the chunker produces; a
            # plain containment test also catches a repeated filler sentence.
            for size in range(len(compact), 1, -1):
                if compact[:size] in (other or ""):
                    counted += size
                    break
    return {
        "total_selected_chars": total,
        "chars_also_present_in_another_selected_chunk": counted,
        "share": round(counted / total, 4) if total else 0.0,
    }


def _selected_keys(pack, truth: Truth) -> list[tuple[str, int]]:
    """Chunk identities actually surfaced, expansion included."""
    keys: list[tuple[str, int]] = []
    for evidence in pack.evidences:
        for chunk_id in (evidence.chunk_id, *evidence.expanded_from):
            located = truth.key_of(chunk_id)
            if located is not None and located not in keys:
                keys.append(located)
    return keys


def score_case(pack, case: QueryCase, truth: Truth) -> dict:
    selected = _selected_keys(pack, truth)
    relevant = {(truth.anchors[key].doc, truth.anchors[key].sequence) for key in case.relevant}
    required = {(truth.anchors[key].doc, truth.anchors[key].sequence) for key in case.required}
    forbidden = {(truth.anchors[key].doc, truth.anchors[key].sequence) for key in case.forbidden}
    distractors = {
        (truth.anchors[key].doc, truth.anchors[key].sequence) for key in case.distractor
    }

    # Expansion-attributed ids are tracked separately: an id that only ever
    # arrived through `expanded_from` is a guard failure, while one the kernel
    # matched is a ranking miss. Same chunk, two different defects.
    expanded_ids = {
        truth.key_of(chunk_id)
        for evidence in pack.evidences
        for chunk_id in evidence.expanded_from
    }
    expanded_ids.discard(None)

    selected_set = set(selected)
    if not selected_set:
        # "Nothing selected" is a failure of the pipeline, not a perfect score:
        # an empty selection matches nothing, so precision is zero.
        precision = 0.0
    else:
        precision = len(selected_set & relevant) / len(selected_set)
    recall = len(selected_set & relevant) / len(relevant) if relevant else 0.0

    redundancy = _ngram_redundancy_counts([item.text for item in pack.evidences])
    shared = _shared_characters([item.text for item in pack.evidences])
    return {
        "cp": precision,
        "cr": recall,
        "nr": 1.0 - precision,
        "rr": redundancy["rate"],
        "counts": {
            # Every rate above is one of these divisions. Stated explicitly so
            # the numbers can be re-derived without re-running anything.
            "selected_chunks": len(selected_set),
            "selected_and_relevant": len(selected_set & relevant),
            "relevant_chunks": len(relevant),
            "required_chunks": len(required),
            "required_covered": len(selected_set & required),
            "expanded_from_chunks": len(expanded_ids),
            "cp_denominator": len(selected_set) or None,
            "cr_denominator": len(relevant),
            "counting_unit": "chunk identity (document_key, sequence)",
            "rr_total_4grams": redundancy["total"],
            "rr_distinct_4grams": redundancy["distinct"],
            "rr_duplicate_4grams": redundancy["duplicate"],
            "rr_concrete": (
                f"{redundancy['duplicate']} of {redundancy['total']} character "
                "4-grams in the selected evidence texts are repeats"
            ),
            "rr_is_not_irrelevance": (
                "Redundancy counts repeated TEXT. It says nothing about whether "
                "a chunk is on topic — a highly redundant selection can still be "
                "entirely relevant, and an irrelevant one can be non-redundant. "
                "NR (1 - CP) is the irrelevance number; RR is not it."
            ),
            "shared_characters_between_selected_chunks": shared,
        },
        "required_covered": sorted(f"{doc}#{seq}" for doc, seq in selected_set & required),
        "required_missing": sorted(f"{doc}#{seq}" for doc, seq in required - selected_set),
        "forbidden_selected": sorted(f"{doc}#{seq}" for doc, seq in selected_set & forbidden),
        "expansion_leaks": sorted(
            f"{doc}#{seq}" for doc, seq in expanded_ids & forbidden
        ),
        # Expected, not a defect: the C4 hazard materialising is the point.
        "distractor_selected": sorted(
            f"{doc}#{seq}" for doc, seq in selected_set & distractors
        ),
        "distractor_expansion_pulled": sorted(
            f"{doc}#{seq}" for doc, seq in expanded_ids & distractors
        ),
    }


def observed_relation(pack, case: QueryCase, truth: Truth) -> dict | None:
    """Which way the boundary was actually crossed, as opposed to intended.

    C1 and C2 share the same fixture truth — two adjacent chunks of one section
    — and differ only in which side the kernel matched. That is an OUTCOME, not
    something the fixture can promise, so it is measured and reported instead
    of being asserted. An intended-C2 query that in fact matched the later
    chunk is reported as C1, not quietly relabelled.

    ``None`` for every other case: C3 is a parent/child relation and C4/C5 are
    about a neighbour that must NOT be credited, so forcing them into the
    C1/C2 axis would invent a distinction that does not exist.
    """
    if case.case not in {"C1", "C2"}:
        return None
    spans = {
        (truth.anchors[key].doc, truth.anchors[key].sequence) for key in case.required
    }
    if len(spans) != 2:
        return None
    lower, upper = sorted(spans, key=lambda item: item[1])
    for evidence in pack.evidences:
        matched = truth.key_of(evidence.chunk_id)
        added = {truth.key_of(chunk_id) for chunk_id in evidence.expanded_from}
        if matched is None:
            continue
        if matched == lower and upper in added:
            return {"observed": "C2", "matched": f"{lower[0]}#{lower[1]}", "added": f"{upper[0]}#{upper[1]}"}
        if matched == upper and lower in added:
            return {"observed": "C1", "matched": f"{upper[0]}#{upper[1]}", "added": f"{lower[0]}#{lower[1]}"}
    return {"observed": "NONE", "matched": None, "added": None}


def expansion_guard(pack, case: QueryCase, truth: Truth) -> dict | None:
    """Did the C5 guard actually RUN, and did it hold?

    "No leak" on its own proves nothing: the expander might simply never have
    looked. A neighbour is only demonstrably refused if expansion fired on the
    chunk one sequence earlier, because that call reads ``[seq-1, seq+1]`` and
    therefore had the forbidden chunk in its window. This is that distinction,
    made explicit.
    """
    if not case.forbidden:
        return None
    leaks: list[str] = []
    windows: list[str] = []
    for evidence in pack.evidences:
        located = truth.key_of(evidence.chunk_id)
        if located is None:
            continue
        for key in case.forbidden:
            anchor = truth.anchors[key]
            if located == (anchor.doc, anchor.sequence - 1) and evidence.expanded:
                windows.append(f"{located[0]}#{located[1]}->[{anchor.doc}#{anchor.sequence}]")
    for item in case.forbidden:
        anchor = truth.anchors[item]
        for evidence in pack.evidences:
            for chunk_id in evidence.expanded_from:
                if truth.key_of(chunk_id) == (anchor.doc, anchor.sequence):
                    leaks.append(f"{anchor.doc}#{anchor.sequence}")
    return {
        "windows_that_contained_the_forbidden_chunk": sorted(set(windows)),
        "guard_exercised": bool(windows),
        "leaks": sorted(set(leaks)),
        "holds": not leaks,
    }


async def evaluate(env: dict, truth: Truth) -> dict:
    orchestrator = env["orchestrator"]
    scope = env["scope"]
    results: list[dict] = []

    for case in QUERY_CASES:
        pack = await orchestrator.retrieve_for_turn(OWNER, scope, case.text)
        metrics = score_case(pack, case, truth)
        results.append(
            {
                "key": case.key,
                "query": case.text,
                "case": case.case,
                "expansion_required": case.expansion_required,
                "required": [
                    f"{truth.anchors[key].doc}#{truth.anchors[key].sequence}"
                    for key in case.required
                ],
                "relevant": [
                    f"{truth.anchors[key].doc}#{truth.anchors[key].sequence}"
                    for key in case.relevant
                ],
                "forbidden": [
                    f"{truth.anchors[key].doc}#{truth.anchors[key].sequence}"
                    for key in case.forbidden
                ],
                "retrieval": {
                    "decision": pack.execution.decision,
                    "retrieval_ran": pack.execution.retrieval_ran,
                    "mode": pack.execution.mode,
                    "reranker_used": pack.execution.reranker_used,
                    "expansion_used": pack.execution.expansion_used,
                    "candidates_considered": pack.execution.candidates_considered,
                    "items_returned": pack.execution.items_returned,
                    "degraded_reasons": list(pack.execution.degraded_reasons),
                    "truncated": pack.execution.coverage.truncated,
                },
                "selected": [
                    {
                        "chunk": f"{truth.key_of(evidence.chunk_id)[0]}"
                        f"#{truth.key_of(evidence.chunk_id)[1]}"
                        if truth.key_of(evidence.chunk_id)
                        else "OUT_OF_SCOPE",
                        "chunk_id": str(evidence.chunk_id),
                        "expanded_from": [
                            f"{truth.key_of(chunk_id)[0]}#{truth.key_of(chunk_id)[1]}"
                            if truth.key_of(chunk_id)
                            else "OUT_OF_SCOPE"
                            for chunk_id in evidence.expanded_from
                        ],
                        "chars": len(evidence.text),
                        "score": round(evidence.score, 6),
                        "rerank_score": (
                            round(evidence.rerank_score, 6)
                            if evidence.rerank_score is not None
                            else None
                        ),
                    }
                    for evidence in pack.evidences
                ],
                "metrics": metrics,
                "observed_relation": observed_relation(pack, case, truth),
                "expansion_guard": expansion_guard(pack, case, truth),
            }
        )

    return {"queries": results, "aggregate": aggregate(results)}


def _macro(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def aggregate(results: list[dict]) -> dict:
    expanded = [row for row in results if row["expansion_required"]]
    return {
        "cp_macro": _macro(row["metrics"]["cp"] for row in results),
        "cr_macro": _macro(row["metrics"]["cr"] for row in results),
        "nr_macro": _macro(row["metrics"]["nr"] for row in results),
        "rr_macro": _macro(row["metrics"]["rr"] for row in results),
        "n_queries": len(results),
        "expansion_required_subset": {
            "keys": [row["key"] for row in expanded],
            "cp_macro": _macro(row["metrics"]["cp"] for row in expanded),
            "cr_macro": _macro(row["metrics"]["cr"] for row in expanded),
            "n_queries": len(expanded),
        },
        "expansion_leaks": sorted(
            f"{row['key']}:{item}"
            for row in results
            for item in row["metrics"]["expansion_leaks"]
        ),
        "forbidden_selected_any_route": sorted(
            f"{row['key']}:{item}"
            for row in results
            for item in row["metrics"]["forbidden_selected"]
        ),
        "missing_required": sorted(
            f"{row['key']}:{item}"
            for row in results
            for item in row["metrics"]["required_missing"]
        ),
        "distractor_pulled_by_expansion": sorted(
            f"{row['key']}:{item}"
            for row in results
            for item in row["metrics"]["distractor_expansion_pulled"]
        ),
        # An intended C2 that actually matched the later chunk is C1 in fact.
        # Reported rather than relabelled, so a fixture that never exercises
        # the intended boundary cannot pass as though it did.
        "relation_mismatches": sorted(
            f"{row['key']}:intended {row['case']} observed "
            f"{row['observed_relation']['observed']}"
            for row in results
            if row["observed_relation"]
            and row["observed_relation"]["observed"] != row["case"]
        ),
    }


# ------------------------------------------------ component ablations (F2)


class IdentityReranker:
    """Ablation arm ONLY. Not a production reranker and not a fallback.

    Keeps the kernel's own ordering, so the difference between this arm and
    production is exactly ``ProductionReranker``'s contribution and nothing
    else. It deliberately does not re-sort, re-score or drop anything — an
    "identity" reranker that still filtered would conflate two changes.
    """

    def __init__(self) -> None:
        self.coverage_weight = 0.0

    def rerank(self, query, hits, limit=None):
        rows = [
            RerankedHit(
                hit=hit,
                rerank_score=hit.score,
                coverage=0.0,
                exact_phrase=False,
                section_match=False,
            )
            for hit in hits
        ]
        return rows[:limit] if limit is not None else rows


def _arm_orchestrator(env: dict, *, reranker, expander, metrics) -> ConversationRetrievalOrchestrator:
    return ConversationRetrievalOrchestrator(
        kernel=env["kernel"],
        reranker=reranker,
        expander=expander,
        candidate_limit=DEFAULT_CANDIDATE_LIMIT,
        evidence_limit=DEFAULT_EVIDENCE_LIMIT,
        metrics=metrics,
    )


async def evaluate_ablations(env: dict, truth: Truth) -> dict:
    """Three arms over ONE corpus, ONE query set, identical budgets.

    The only thing that varies between arms is the component under test. The
    kernel, the scope, the candidate limit and the evidence limit are the same
    objects, so a delta cannot be an artefact of re-ingestion or of a budget
    that drifted between runs.
    """
    arms = {
        "production": _arm_orchestrator(
            env,
            reranker=ProductionReranker(),
            expander=ContextExpander(env["repository"]),
            metrics=MathTutorMetrics(),
        ),
        "no_reranker": _arm_orchestrator(
            env,
            reranker=IdentityReranker(),
            expander=ContextExpander(env["repository"]),
            metrics=MathTutorMetrics(),
        ),
        "no_expansion": _arm_orchestrator(
            env,
            reranker=ProductionReranker(),
            expander=None,
            metrics=MathTutorMetrics(),
        ),
    }

    results: dict[str, dict] = {}
    for arm_name, orchestrator in arms.items():
        per_query: dict[str, dict] = {}
        for case in QUERY_CASES:
            pack = await orchestrator.retrieve_for_turn(OWNER, env["scope"], case.text)
            metrics = score_case(pack, case, truth)
            per_query[case.key] = {
                "cp": round(metrics["cp"], 4),
                "cr": round(metrics["cr"], 4),
                "counts": metrics["counts"],
                "expansion_used": pack.execution.expansion_used,
                "required_missing": metrics["required_missing"],
                "visible_without_expansion": _visible_without_expansion(
                    pack, metrics["required_missing"], case, truth
                ),
            }
        results[arm_name] = {
            "per_query": per_query,
            "cp_macro": round(_macro(row["cp"] for row in per_query.values()), 4),
            "cr_macro": round(_macro(row["cr"] for row in per_query.values()), 4),
            "eligible_queries": len(per_query),
        }

    production = results["production"]["per_query"]
    deltas: dict[str, dict] = {}
    for arm_name, arm in results.items():
        if arm_name == "production":
            continue
        deltas[arm_name] = {
            "cp_macro_delta": round(arm["cp_macro"] - results["production"]["cp_macro"], 4),
            "cr_macro_delta": round(arm["cr_macro"] - results["production"]["cr_macro"], 4),
            "per_query": {
                key: {
                    "cp_delta": round(row["cp"] - production[key]["cp"], 4),
                    "cr_delta": round(row["cr"] - production[key]["cr"], 4),
                }
                for key, row in arm["per_query"].items()
            },
        }

    no_expansion = results["no_expansion"]["per_query"]
    lost = {
        key: row["required_missing"]
        for key, row in no_expansion.items()
        if row["required_missing"]
    }
    return {
        "status": "MEASURED",
        "design": (
            "Identical corpus, queries, kernel, scope, candidate_limit and "
            "evidence_limit across arms; only the named component differs."
        ),
        "arms": results,
        "deltas_vs_production": deltas,
        "no_reranker_reading": _gain_reading(
            deltas.get("no_reranker", {}).get("cp_macro_delta", 0.0),
            deltas.get("no_reranker", {}).get("cr_macro_delta", 0.0),
        ),
        "no_expansion_reading": _gain_reading(
            deltas.get("no_expansion", {}).get("cp_macro_delta", 0.0),
            deltas.get("no_expansion", {}).get("cr_macro_delta", 0.0),
        ),
        # A label like DECLINE_ON_THIS_SET is a sign, not a size. Without the
        # eligible count next to it, a 0.0055 CP move on 5 queries reads as a
        # finding when it is one chunk-selection difference.
        "materiality": {
            "no_reranker": _materiality(results, deltas, "no_reranker"),
            "no_expansion": _materiality(results, deltas, "no_expansion"),
            "queries_changed_no_reranker": [
                key
                for key, row in deltas.get("no_reranker", {}).get("per_query", {}).items()
                if row["cp_delta"] or row["cr_delta"]
            ],
            "queries_changed_no_expansion": [
                key
                for key, row in deltas.get("no_expansion", {}).get("per_query", {}).items()
                if row["cp_delta"] or row["cr_delta"]
            ],
        },
        "no_expansion_lost_required": lost,
        "no_expansion_visible_elsewhere": {
            key: row["visible_without_expansion"]
            for key, row in no_expansion.items()
            if row["visible_without_expansion"]
        },
        "interpretation_guard": (
            "A null or negative delta is a result. Neither arm was re-tuned, "
            "re-filtered or re-scored to manufacture a decline."
        ),
    }


def _materiality(arm_results: dict, deltas: dict, arm: str) -> dict:
    """Turn a macro delta into a count of selections, which is what moved."""
    per_query = arm_results[arm]["per_query"]
    changed = [
        key
        for key, row in deltas.get(arm, {}).get("per_query", {}).items()
        if row["cp_delta"] or row["cr_delta"]
    ]
    selections = sum(
        row["counts"]["selected_chunks"] for row in arm_results["production"]["per_query"].values()
    )
    return {
        "eligible_queries": len(per_query),
        "queries_that_changed": changed,
        "production_total_selections": selections,
        "reading": (
            f"{len(changed)} of {len(per_query)} queries moved, across "
            f"{selections} production selections. CP is a per-query ratio of "
            "chunk counts, so a delta of this size is a handful of selections."
        ),
    }


def _gain_reading(cp_delta: float, cr_delta: float) -> str:
    if cp_delta > 0.001 or cr_delta > 0.001:
        return "GAIN_ON_THIS_SET"
    if cp_delta < -0.001 or cr_delta < -0.001:
        return "DECLINE_ON_THIS_SET"
    return "NO_GAIN_ON_THIS_SET"


def _visible_without_expansion(pack, missing: list[str], case: QueryCase, truth: Truth) -> list[dict]:
    """Was a "lost" required fact still readable elsewhere in the selection?

    Without this, a required chunk missing from the no-expansion arm looks like
    an information loss when the fact may simply have arrived through another
    selected chunk — or through the chunker's overlap window, which repeats the
    tail of one piece at the head of the next. Reporting the loss without
    checking is how a non-loss gets counted as one.
    """
    found: list[dict] = []
    by_key = {f"{anchor.doc}#{anchor.sequence}": anchor for anchor in truth.anchors.values()}
    for item in missing:
        anchor = by_key.get(item)
        if anchor is None:
            continue
        for evidence in pack.evidences:
            located = truth.key_of(evidence.chunk_id)
            if located is None or f"{located[0]}#{located[1]}" == item:
                continue
            if anchor.must_contain in evidence.text:
                found.append(
                    {
                        "missing_chunk": item,
                        "fact": anchor.must_contain,
                        "visible_in": f"{located[0]}#{located[1]}",
                        "route": "another selected chunk or its overlap window",
                    }
                )
                break
    return found


# ------------------------------------------------------ fixture mutations


def _mutate(case: QueryCase, **changes) -> QueryCase:
    values = {
        "key": case.key,
        "text": case.text,
        "case": case.case,
        "required": case.required,
        "relevant": case.relevant,
        "forbidden": case.forbidden,
        "distractor": case.distractor,
        "expansion_required": case.expansion_required,
    }
    values.update(changes)
    return QueryCase(**values)


def _fixture_mutations() -> tuple[tuple[str, tuple, tuple, str], ...]:
    """(name, anchors, cases, the check that MUST fire).

    Each entry is a deliberately broken fixture. A self-check that cannot be
    made to fail is not a check, so these run every time and are recorded
    alongside the result rather than being a one-off manual experiment.
    """
    base = ANCHORS
    broken_anchor = tuple(
        Anchor("disc.definition", "disc", 0, "判别式定义为 Δ = b^2 - 4ac")
        if anchor.key == "disc.definition"
        else anchor
        for anchor in base
    )
    no_applicable = tuple(a for a in base if a.key != "disc.applicable_object")
    missing = tuple(a for a in base if a.key != "neighbour.distractor")

    cases = _cases_by_key()
    not_subset = tuple(
        _mutate(cases["Q01"], required=("disc.definition",), relevant=("disc.applicable_object",))
        if case.key == "Q01"
        else case
        for case in QUERY_CASES
    )
    fake_c5 = tuple(
        _mutate(cases["Q03"], forbidden=("disc.definition",))
        if case.key == "Q03"
        else case
        for case in QUERY_CASES
    )
    no_distractor = tuple(
        _mutate(cases["Q04"], distractor=())
        if case.key == "Q04"
        else case
        for case in QUERY_CASES
    )
    return (
        (
            "anchor_points_at_the_wrong_sequence",
            broken_anchor,
            QUERY_CASES,
            "anchor_text_present[disc.definition]",
        ),
        (
            "anchor_removed_from_relevant",
            no_applicable,
            QUERY_CASES,
            "label_resolves[Q01:disc.applicable_object]",
        ),
        ("required_not_a_subset_of_relevant", base, not_subset, "required_subset_of_relevant[Q01]"),
        ("forbidden_is_not_sequence_adjacent", base, fake_c5, "C5_is_sequence_adjacent[Q03:disc.definition]"),
        ("c4_distractor_undeclared", base, no_distractor, "C4_distractor_is_labelled[Q04]"),
        ("c4_distractor_anchor_removed", missing, QUERY_CASES, "label_resolves[Q04:neighbour.distractor]"),
    )


def _cases_by_key() -> dict[str, QueryCase]:
    return {case.key: case for case in QUERY_CASES}


async def verify_fixture_guards(tmp: Path) -> dict:
    """Every self-check, made to fail on purpose, one injection at a time."""
    results: list[dict] = []
    for name, anchors, cases, expected_check in _fixture_mutations():
        # Each injection gets a fresh ingest so a mutated ANCHOR cannot leak
        # into the next one through a shared manifest.
        env = await build(tmp / f"guard-{name}")
        try:
            truth = Truth(env["manifest"], anchors, env["other_manifest"])
            checks = run_selfcheck(truth, cases)
        finally:
            await env["engine"].dispose()
        failed = [item["check"] for item in checks if not item["ok"]]
        results.append(
            {
                "name": name,
                "expected_check": expected_check,
                "observed_failures": failed,
                "fired": expected_check in failed,
            }
        )
    unfired = [row["name"] for row in results if not row["fired"]]
    return {
        "status": "MEASURED",
        "method": (
            "Each injection breaks one fixture property; the named self-check "
            "must appear in the failure set. Injections are fixture mutations "
            "and are reported separately from citation mutations and from "
            "component ablations."
        ),
        "injections": results,
        "unfired": unfired,
        "verdict": (
            "OK — every injected fixture defect was caught by the check that "
            "exists for it"
            if not unfired
            else f"ALARM — {len(unfired)} injected defect(s) went undetected"
        ),
    }


# ------------------------------------------------------ answer-quality export


async def answer_quality_export(env: dict, truth: Truth) -> dict:
    """What a model WOULD have seen, saved for later human review.

    No generator runs, so this is not answer-quality evaluation and is not
    labelled as any. It captures the exact visible context per query — the
    thing a reviewer needs in order to judge an answer later — and it contains
    no generated text, so there is nothing here that could be mistaken for a
    measured output.
    """
    items: list[dict] = []
    for case in QUERY_CASES:
        pack = await env["orchestrator"].retrieve_for_turn(OWNER, env["scope"], case.text)
        items.append(
            {
                "query_key": case.key,
                "query": case.text,
                "rewritten_query": pack.rewritten_query,
                "context_fingerprint": pack.query_fingerprint,
                "visible_context": [
                    {
                        "source_id": evidence.source_id,
                        "document": (
                            f"{truth.key_of(evidence.chunk_id)[0]}"
                            f"#{truth.key_of(evidence.chunk_id)[1]}"
                            if truth.key_of(evidence.chunk_id)
                            else "OUT_OF_SCOPE"
                        ),
                        "text": evidence.text,
                        "text_hash": evidence.text_hash,
                        "expanded_from": [str(chunk_id) for chunk_id in evidence.expanded_from],
                    }
                    for evidence in pack.evidences
                ],
                "citation_candidates": [
                    {
                        "source_id": evidence.source_id,
                        "document_id": str(evidence.document_id),
                        "sequence": evidence.sequence,
                    }
                    for evidence in pack.evidences
                ],
            }
        )
    return {
        "status": "EXPORTED_FOR_REVIEW",
        "answers_generated": 0,
        "generator": None,
        "reviewed": False,
        "labels_from": None,
        "note": (
            "No approved generator ran. These are the inputs a generator would "
            "receive, not answers. An UNREVIEWED export does not close "
            "answer-quality evaluation, and nothing here is a score. When a "
            "generator is approved, its saved outputs are evaluated separately "
            "with labels marked human or judge-estimated."
        ),
        "items": items,
    }


# ------------------------------------------------- semantic evaluation mode


def semantic_status() -> dict:
    """Whether a real entailment model may be used, and under what terms.

    Deliberately conservative. This returns a BLOCKED status unless an
    operator has explicitly authorised a provider; it never inspects the
    environment for credentials, never prints any, never selects a paid
    provider on its own and never downloads a model. Those are all ways an
    evaluation run could quietly become a cost or a leak.
    """
    configured = _approved_semantic_provider()
    if configured is None:
        return {
            "status": "BLOCKED_PROVIDER",
            "blocker": (
                "No explicitly approved provider for semantic checking. Set "
                "MATHTUTOR_EVAL_PROVIDER to an operator-authorised provider id "
                "to enable this section. The runner does not sniff the "
                "environment for credentials, pick a paid provider, or fetch a "
                "model."
            ),
            "real_decisions": 0,
            "semantic_rates": None,
            "note": (
                "Rates are null, not zero. Zero real decisions is an absence of "
                "evidence, and a 0.0 would read as a measured failure."
            ),
        }
    return {
        "status": "READY",
        "provider": configured,
        "real_decisions": 0,
        "semantic_rates": None,
    }


def _approved_semantic_provider() -> str | None:
    import os

    value = (os.environ.get("MATHTUTOR_EVAL_PROVIDER") or "").strip()
    return value or None


# --------------------------------------------- official benchmark reuse (F2)


def official():
    """The ONE official benchmark module.

    Imported rather than reimplemented. Every retrieval number in this artefact
    comes from `recall_at_k` / `mrr_at_k` / `ndcg_at_k` / `hit_rate_at_k` and
    the ranking helper defined there, so easy and hard sets are on one footing
    and a change to the official definitions moves both.
    """
    tests_dir = ROOT / "tests"
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    import test_rag_production_benchmark as module

    return module


METRIC_KEYS = ("recall@1", "recall@3", "recall@5", "mrr@3", "mrr@5",
               "ndcg@3", "ndcg@5", "hit@1", "hit@3", "hit@5")


async def official_retrieval_metrics(bench: dict, queries, *, owner: str = OWNER) -> dict:
    """Retrieval metrics over a bench dict, using the OFFICIAL definitions.

    ``queries`` yields ``(key, text, relevant (document_key, sequence) pairs)``.
    """
    module = official()
    per_query: dict[str, dict] = {}
    # Validate setup independently of retrieval output: a valid zero is a miss.
    queries = list(queries)
    repository = bench["repository"]
    scope = {str(value) for value in bench["scope"]}
    visible = {}
    for document_id in bench["scope"]:
        document = await repository.get_document(owner, document_id)
        if document is None or not document.is_retrievable():
            raise BenchmarkInvalid("scope owner, ingestion or visibility validation failed")
        visible[str(document_id)] = {
            chunk.sequence for chunk in await repository.list_retrievable_chunks(owner, document_id)
        }
    for _, _, pairs in queries:
        for key, sequence in pairs:
            document_id = str(bench["documents"][key]["document_id"])
            if document_id not in scope or sequence not in visible.get(document_id, set()):
                raise BenchmarkInvalid("reference does not exist in the bound visible scope")
    for key, text, relevant_pairs in queries:
        relevant = frozenset(
            module._identity(bench, doc, seq) for doc, seq in relevant_pairs
        )
        _pack, ranked = await module._rank(bench, text, owner=owner)
        row = {
            metric: round(
                {
                    "recall@1": module.recall_at_k,
                    "recall@3": module.recall_at_k,
                    "recall@5": module.recall_at_k,
                    "mrr@3": module.mrr_at_k,
                    "mrr@5": module.mrr_at_k,
                    "ndcg@3": module.ndcg_at_k,
                    "ndcg@5": module.ndcg_at_k,
                    "hit@1": module.hit_rate_at_k,
                    "hit@3": module.hit_rate_at_k,
                    "hit@5": module.hit_rate_at_k,
                }[metric](ranked, relevant, int(metric.split("@")[1])),
                4,
            )
            for metric in METRIC_KEYS
        }
        row["counts"] = {
            "ranked_returned": len(ranked),
            "relevant_expected": len(relevant),
            "relevant_retrieved_at_5": len(set(ranked[:5]) & relevant),
            "counting_unit": "chunk identity (document_id:sequence), matched chunk only",
        }
        per_query[key] = row

    aggregate = {
        metric: round(sum(row[metric] for row in per_query.values()) / len(per_query), 4)
        if per_query
        else None
        for metric in METRIC_KEYS
    }
    return {
        "per_query": per_query,
        "aggregate": aggregate,
        "eligible_queries": len(per_query),
        "definition_source": "tests/test_rag_production_benchmark.py",
        "ranked_identity": (
            "evidence.document_id:evidence.sequence — the MATCHED chunk only. "
            "Text widened by context expansion is not a separate ranked item "
            "here; the hard-set context metrics count it separately."
        ),
    }


async def evaluate_easy(tmp: Path) -> dict:
    """The legacy easy subset: the official corpus and its authored seed queries.

    Nothing about this run is redefined locally — corpus, queries, chunking,
    ranking and all four metric families come from the official benchmark.
    """
    module = official()
    env = await module.build_benchmark(tmp / "easy")
    try:
        bench = {
            "documents": env["documents"],
            "scope": env["scope"],
            "repository": env["repository"],
            "orchestrator": env["orchestrator"],
        }
        queries = [
            (query.key, query.text, query.relevant) for query in module.QUERIES
        ]
        # The easy corpus is ingested by the official fixture under its own
        # owner; querying with this module's OWNER would return nothing.
        metrics = await official_retrieval_metrics(bench, queries, owner=module.OWNER)

        # The official fixture's own ground-truth check, run as a precondition
        # rather than trusted: an easy-set number computed against a stale
        # reference is worse than no number.
        mismatches = []
        for query in module.QUERIES:
            for key, sequence in query.relevant:
                chunks = env["documents"][key]["chunks"]
                if sequence >= len(chunks):
                    mismatches.append(f"{query.key}:{key}:{sequence} missing")
                elif query.contains not in chunks[sequence].text:
                    mismatches.append(f"{query.key}:{key}:{sequence} lacks {query.contains!r}")
        documents = {
            key: {
                "document_id": str(entry["document_id"]),
                "chunk_count": len(entry["chunks"]),
                "parser_version": str(
                    getattr(entry["chunks"][0], "parser_version", "") if entry["chunks"] else ""
                ),
            }
            for key, entry in env["documents"].items()
        }
        return {
            "status": "MEASURED",
            "corpus": "tests/test_rag_production_benchmark.py::CORPUS",
            "queries": "tests/test_rag_production_benchmark.py::QUERIES",
            "documents": documents,
            "corpus_chunks": sum(entry["chunk_count"] for entry in documents.values()),
            "ground_truth_mismatches": mismatches,
            "ground_truth_ok": not mismatches,
            "metrics": metrics,
        }
    finally:
        await env["engine"].dispose()


# ------------------------------------------------- claims and citations (F2)


_FACT_QUOTES = {
    "disc": "判别式定义为 Δ = b^2 - 4ac，它决定方程实数根的个数",
    "weida": "x1 + x2 = -b/a，x1 * x2 = c/a",
}

#: Which query surfaces which document, and the title the hit must carry.
_SURFACE_SPECS = {
    "disc": ("判别式定义为 Δ = b^2 - 4ac", "判别式.md"),
    "weida": ("韦达定理 根与系数的关系", "韦达定理.md"),
}


@dataclass(frozen=True)
class ClaimCase:
    """One claim plus the citation judgement it should provoke.

    ``cited`` and ``required`` are about the CITATION, not about truth: which
    sources the answer named versus which sources the claim actually needs.
    That is what makes precision and recall computable without an entailment
    model, and it is deliberately NOT a faithfulness number.

    ``quotes`` maps each cited document to the text offered as its support.
    It is per-source on purpose: reusing one document's quote for another
    document's evidence is itself a citation error, and a fixture that made
    that mistake would have reported a correct rejection as a defect.
    """

    key: str
    quotes: tuple[tuple[str, str], ...]
    kind: str
    required: tuple[str, ...]
    expect: str  # "accept" | "reject"
    #: One of COHORTS. Attribution quality and operational validity are
    #: different questions and are never averaged into a single number.
    cohort: str
    note: str

    @property
    def cited(self) -> tuple[str, ...]:
        return tuple(key for key, _ in self.quotes)


COHORT_VALID = "valid_attribution"
COHORT_MISATTRIBUTED = "incorrect_attribution"
COHORT_MALFORMED = "malformed_or_unauthorized"
COHORTS = (COHORT_VALID, COHORT_MISATTRIBUTED, COHORT_MALFORMED)


CLAIM_CASES: tuple[ClaimCase, ...] = (
    ClaimCase(
        key="CC1_verbatim",
        quotes=(("disc", _FACT_QUOTES["disc"]),),
        kind="quote",
        required=("disc",),
        expect="accept",
        cohort=COHORT_VALID,
        note="A verbatim quotation of a range that was actually read.",
    ),
    ClaimCase(
        key="CC2_over_cited",
        quotes=(("disc", _FACT_QUOTES["disc"]), ("weida", _FACT_QUOTES["weida"])),
        kind="summary",
        required=("disc",),
        expect="accept",
        cohort=COHORT_MISATTRIBUTED,
        note=(
            "Cites one source too many. Accepted by the validator (both ranges "
            "were read and both quotes are verbatim) — the excess is exactly "
            "what citation precision is for, and no validator can see it."
        ),
    ),
    ClaimCase(
        key="INJ1_tampered_quote",
        quotes=(("disc", "判别式定义为 Δ = b^2 + 4ac，它决定方程实数根的个数"),),
        kind="quote",
        required=("disc",),
        expect="reject",
        cohort=COHORT_MISATTRIBUTED,
        note="Quote mutated by one sign; the range was read but does not contain this text.",
    ),
    ClaimCase(
        key="INJ2_fabricated_source",
        quotes=(("disc", _FACT_QUOTES["disc"]),),
        kind="quote",
        required=("disc",),
        expect="reject",
        cohort=COHORT_MALFORMED,
        note="source_id that was never surfaced — an unauthorized operation, not a wording error.",
    ),
    ClaimCase(
        key="INJ3_quote_kind_mismatch",
        quotes=(("disc", _FACT_QUOTES["disc"]),),
        kind="quote",
        required=("disc",),
        expect="reject",
        cohort=COHORT_MISATTRIBUTED,
        note="Declared as a verbatim quotation but the claim text paraphrases it.",
    ),
)


def _body_of(key: str) -> str:
    return next(doc.body for doc in HARD_DOCS if doc.key == key)


async def build_knowledge_harness(tmp: Path) -> dict:
    """A real ProductState over real SQLite, seeded with the SAME fixture text.

    The knowledge path (authored notes) is a different code path from the
    import path the retrieval metrics use, so the citation fixture is built
    here rather than reusing `build`.
    """
    from mathtutor.api.product_state import ProductState
    from mathtutor.application.verification_backend import InProcessVerificationBackend
    from mathtutor.infrastructure.schema import metadata

    engine = create_db_engine(tmp / "claims.db")
    async with engine.begin() as db:
        await db.run_sync(metadata.create_all)
    state = ProductState(
        engine=engine,
        data_dir=tmp,
        verification_backend=InProcessVerificationBackend(),
    )
    await state.conversations.ensure(OWNER, "conv-a")
    await state.conversations.ensure(OWNER, "conv-b")

    space = await state.knowledge.create_space(OWNER, "hard-set")
    documents: dict[str, dict] = {}
    for index, doc in enumerate(HARD_DOCS):
        documents[doc.key] = await state.knowledge.save_markdown(
            OWNER,
            space["space_id"],
            title=doc.filename,
            body=doc.body,
            operation_id=f"hard:{index}",
        )
    await state.knowledge.configure(
        OWNER, "conv-a", space_ids=[space["space_id"]], save_space_id=space["space_id"]
    )
    return {"state": state, "engine": engine, "space": space, "documents": documents}


async def _tools(state, cid: str):
    from mathtutor.application.knowledge_tools import KnowledgeTools

    generation = await state.knowledge.generation(OWNER)
    return KnowledgeTools(state, OWNER, cid, generation=generation)


async def _surface(tools, *, query: str, title: str, needle: str, call_id: str):
    """Search, then read the surfaced range — never a hand-picked offset.

    ``read_source`` deliberately refuses ranges that were not first returned by
    ``search_knowledge`` ("cannot guess a document id or a range"), so a fixture
    that computed its own offsets would be testing a code path no model can
    reach. The consequence is honest and worth stating: the read range is the
    chunk the kernel chose, not a range chosen to fit the quote.
    """
    search = await tools.execute("search_knowledge", {"query": query}, f"s-{call_id}")
    if not search["ok"]:
        raise BenchmarkInvalid(f"search failed for {query!r}: {search.get('message')}")
    hits = [hit for hit in search["result"]["hits"] if hit["title"] == title]
    if not hits:
        raise BenchmarkInvalid(f"no hit titled {title!r} for query {query!r}")
    hit = hits[0]
    read = await tools.execute(
        "read_source",
        {key: hit[key] for key in ("document_id", "version", "start", "end")},
        f"r-{call_id}",
    )
    if not read["ok"]:
        raise BenchmarkInvalid(f"read failed for {title!r}: {read.get('message')}")
    result = read["result"]
    if needle not in result["text"]:
        raise BenchmarkInvalid(
            f"surfaced range for {title!r} does not contain the fixture quote "
            f"{needle[:24]!r} — the claim this fixture builds would be unsupported "
            "by construction, so the ground truth would be wrong"
        )
    return result


async def evaluate_citations(env: dict) -> dict:
    from mathtutor.application.knowledge import KnowledgeError
    from mathtutor.application.knowledge_tools import Claim, Evidence

    state = env["state"]
    documents = env["documents"]
    tools = await _tools(state, "conv-a")

    # --- 1. surface real ranges through the real tool path ---------------
    surfaced: dict[str, dict] = {}
    for key, (query, title) in _SURFACE_SPECS.items():
        surfaced[key] = await _surface(
            tools, query=query, title=title, needle=_FACT_QUOTES[key], call_id=f"cite-{key}"
        )

    def claim_from(case: ClaimCase, *, text: str | None = None, source_ids=None):
        evidence = [
            Evidence(
                source_id=(source_ids or {}).get(key, surfaced[key]["source_id"]),
                quote=quote,
            )
            for key, quote in case.quotes
        ]
        default_text = case.quotes[0][1]
        return Claim(text=text if text is not None else default_text,
                     kind=case.kind, evidence=evidence)

    # --- 2. citation precision / recall over the labelled claims ---------
    per_claim: list[dict] = []
    accepted: list[str] = []
    rejected: list[str] = []
    wrongful: list[str] = []

    for case in CLAIM_CASES:
        cited_keys = list(case.cited)
        required_keys = list(case.required)
        precision = len(set(cited_keys) & set(required_keys)) / len(cited_keys) if cited_keys else 0.0
        recall = len(set(cited_keys) & set(required_keys)) / len(required_keys) if required_keys else 0.0
        row = {
            "key": case.key,
            "cohort": case.cohort,
            "kind": case.kind,
            "cited": cited_keys,
            "required": required_keys,
            "citation_links": len(cited_keys),
            "correct_link_count": len(set(cited_keys) & set(required_keys)),
            "total_link_count": len(cited_keys),
            "aggregation_eligible": case.cohort in (COHORT_VALID, COHORT_MISATTRIBUTED),
            "correct_link_definition": "cited source key belongs to required source keys; not semantic or quote validity",
            "citation_precision": precision,
            "citation_recall": recall,
            "expect": case.expect,
            "note": case.note,
        }
        try:
            if case.key == "INJ2_fabricated_source":
                claim = claim_from(case, source_ids={"disc": "src-" + "0" * 24 + "-never-surfaced"})
            elif case.key == "INJ3_quote_kind_mismatch":
                claim = claim_from(case, text="判别式由方程的系数决定")
            else:
                claim = claim_from(case)
            # A `summary` claim additionally requires the bounded entailment
            # check. It is installed ONLY for CC2, so INJ4 can observe the
            # fail-closed path when no checker exists.
            tools.support_checker = (lambda summaries: _always([])) if case.kind == "summary" else None
            await tools.validate_claims([claim])
            outcome = "accept"
            accepted.append(case.key)
        except KnowledgeError as error:
            outcome = "reject"
            rejected.append(case.key)
            row["rejection"] = str(error)
        row["outcome"] = outcome
        if outcome != case.expect:
            wrongful.append(f"{case.key}: expected {case.expect}, got {outcome}")
        per_claim.append(row)

    tools.support_checker = None

    # --- 3. fail-closed checks with no entailment backend ----------------
    fail_closed: list[dict] = []
    for key, build in (
        ("summary_without_checker",
         lambda: claim_from(next(c for c in CLAIM_CASES if c.key == "CC2_over_cited"))),
    ):
        try:
            await tools.validate_claims([build()])
            fail_closed.append({"key": key, "rejected": False})
        except KnowledgeError as error:
            fail_closed.append({"key": key, "rejected": True, "reason": str(error)})

    # A checker that says "not supported" must also block the synthesis.
    tools.support_checker = lambda summaries: _always(summaries, value=False)
    try:
        await tools.validate_claims([claim_from(next(c for c in CLAIM_CASES if c.key == "CC2_over_cited"))])
        fail_closed.append({"key": "summary_unsupported_by_checker", "rejected": False})
    except KnowledgeError as error:
        fail_closed.append({"key": "summary_unsupported_by_checker", "rejected": True, "reason": str(error)})
    tools.support_checker = None

    # --- 4. historical receipt lifecycle ---------------------------------
    receipt_id = surfaced["disc"]["receipt_id"]
    lifecycle: list[dict] = []

    async def probe(key: str, cid: str, start, end, expectation: str):
        """``expectation`` is what a CORRECT system does — not what we hope for.

        Separate buckets, because "the legitimate read still works" and "an
        illegitimate read is refused" are different properties, and one rate
        over both would be uninterpretable: refusing everything would score
        the same as refusing exactly the right things.
        """
        try:
            await state.knowledge.read_citation_receipt(OWNER, cid, receipt_id, start, end)
            got = "accept"
        except KnowledgeError as error:
            lifecycle.append(
                {"key": key, "expectation": expectation, "outcome": "reject", "reason": str(error)}
            )
            if expectation != "reject":
                lifecycle[-1]["unexpected"] = True
            return
        lifecycle.append({"key": key, "expectation": expectation, "outcome": got})
        if expectation == "reject":
            lifecycle[-1]["unexpected"] = True

    legit = "accept"
    blocked = "reject"
    start, end = surfaced["disc"]["start"], surfaced["disc"]["end"]
    await probe("exact_range", "conv-a", start, end, legit)
    await probe("widened_range", "conv-a", start, end + 1, blocked)
    await probe("shifted_start", "conv-a", start - 1, end, blocked)
    await probe("other_conversation", "conv-b", start, end, blocked)

    # Deletion is physical here, so the receipt must stop verifying.
    await state.knowledge.forget_document(OWNER, documents["disc"]["document_id"])
    await probe("after_deletion", "conv-a", start, end, blocked)

    legitimate = [row for row in lifecycle if row["expectation"] == "accept"]
    unauthorized = [row for row in lifecycle if row["expectation"] == "reject"]
    unexpected = [row["key"] for row in lifecycle if row.get("unexpected")]
    # Attribution includes valid + incorrect cohorts; operational validity is
    # separate. Source-key precision does not measure quotation correctness.
    quality = [row for row in per_claim if row["cohort"] == "valid_attribution"]
    misattributed = [row for row in per_claim if row["cohort"] == "incorrect_attribution"]
    operational = [row for row in per_claim if row["cohort"] == "malformed_or_unauthorized"]
    return {
        "status": "MEASURED",
        "path": (
            "real KnowledgeService + KnowledgeTools over real SQLite; notes "
            "authored from the same fixture bodies the retrieval metrics use, "
            "because the note path and the import path are different code."
        ),
        "claims": per_claim,
        "cohorts": {
            cohort: {
                "claim_cases": len(rows),
                "citation_links": sum(row["citation_links"] for row in rows),
                "keys": [row["key"] for row in rows],
            }
            for cohort, rows in (
                (name, [row for row in per_claim if row["cohort"] == name]) for name in COHORTS
            )
        },
        # Both counts, because they answer different questions: a cohort of one
        # claim carrying four links is one attribution decision and four
        # citation decisions, and quoting either alone misleads.
        "totals": {
            "claim_cases": len(per_claim),
            "citation_links": sum(row["citation_links"] for row in per_claim),
        },
        "attribution": {
            "cohorts": [COHORT_VALID, COHORT_MISATTRIBUTED],
            "claim_cases": len(quality) + len(misattributed),
            "citation_links": sum(
                row["citation_links"] for row in quality + misattributed
            ),
            "precision_macro": _macro(
                row["citation_precision"] for row in quality + misattributed
            ),
            "recall_macro": _macro(row["citation_recall"] for row in quality + misattributed),
            "valid_cases": [row["key"] for row in quality],
            "invalid_cases": [row["key"] for row in misattributed],
        },
        "operational": {
            "cohort": COHORT_MALFORMED,
            "claim_cases": len(operational),
            "citation_links": sum(row["citation_links"] for row in operational),
            "rejection_rate": (
                _macro(
                    1.0 if row["outcome"] == "reject" else 0.0
                    for row in operational
                    if row["expect"] == "reject"
                )
                if operational
                else None
            ),
            "wrongful_admissions": [
                row["key"] for row in operational if row["outcome"] != row["expect"]
            ],
        },
        "misattribution_cases": [row["key"] for row in misattributed],
        "operational_probe_cases": [row["key"] for row in operational],
        "what_precision_means": {
            "citation_precision_macro": (
                "ATTRIBUTION against reference evidence: of the sources this "
                "claim cited, the share the annotator marked as required. It is "
                "NOT operational validity and NOT semantic-check accuracy."
            ),
            "operational_validity": (
                "Measured separately, as accept/reject by the real validator on "
                "the malformed_or_unauthorized cohort. A citation can be "
                "operationally valid and still mis-attributed (CC2 is exactly "
                "that), and neither number is production semantic-check accuracy."
            ),
        },
        "accepted": accepted,
        "rejected": rejected,
        "expected_disagreements": wrongful,
        "fail_closed": fail_closed,
        "receipt_lifecycle": lifecycle,
        "historical_receipt_validation_rate": (
            sum(1 for row in legitimate if row["outcome"] == "accept") / len(legitimate)
            if legitimate
            else 0.0
        ),
        "unauthorized_historical_read_rejection_rate": (
            sum(1 for row in unauthorized if row["outcome"] == "reject") / len(unauthorized)
            if unauthorized
            else 0.0
        ),
        "receipt_probes": {"legitimate": len(legitimate), "unauthorized": len(unauthorized)},
        "unexpected_lifecycle_outcomes": unexpected,
    }


async def _always(_summaries, *, value: bool = True) -> bool:
    """A protocol stub, NOT a judgement about meaning.

    It exists so the summary branch can be exercised at all. A stub that
    returns the gold label proves the PROTOCOL is wired; it proves nothing
    about whether real entailment would have agreed, and no number derived
    from it may be reported as faithfulness.
    """
    return value


FAITHFULNESS_NOT_MEASURED = {
    "status": "NOT_MEASURED",
    "reason": (
        "Content support is an entailment question and no entailment model "
        "ships with the runtime: ``support_check`` in tutor_runtime requires a "
        "model provider, and the shipped product runs without one. A stub that "
        "returns the ground-truth labels would exercise the protocol and prove "
        "nothing about semantics, so no faithfulness rate is reported."
    ),
    "what_is_measured_instead": (
        "Legal-citation structure (source was surfaced, quote is verbatim in "
        "that range, body_hash still matches) is fully deterministic and is "
        "measured under `citation`."
    ),
    "taxonomy": {
        "LEGAL_CITATION": "measured — structural checks pass",
        "CONTENT_SUPPORT": "UNKNOWN — needs an entailment model",
        "WRONGFUL_ADMISSION": "measured — injected corruptions that were ACCEPTED",
        "PARTIAL_SUPPORT": "UNKNOWN — needs an entailment model",
        "UNKNOWN": "reported as a count, never folded into a rate",
    },
}


NOT_MEASURED = {
    "status": "NOT_MEASURED_IN_THIS_INCREMENT",
    "reason": (
        "Claim fixtures (claim text + expected supporting evidence ids) do not "
        "exist yet, so no faithfulness or citation number can be produced "
        "without inventing one."
    ),
}

#: How a number here was computed. Kept next to the artefact so a reader does
#: not have to reverse-engineer the definitions from the scores.
METRIC_DEFINITIONS = {
    "selected_context": (
        "The union of every evidence's own chunk_id and every id in its "
        "expanded_from. Expansion changes what the model reads, so it is "
        "charged to precision and recall like any other selection."
    ),
    "context_precision": "|selected ∩ relevant| / |selected|; 0.0 when nothing was selected.",
    "context_recall": "|selected ∩ relevant| / |relevant|.",
    "noise_ratio": "1 − context_precision.",
    "redundancy_rate": (
        "1 − (distinct character 4-grams / total character 4-grams) over the "
        "selected evidence texts. Overlap-based chunking repeats a fixed "
        "window across adjacent pieces, so a redundancy near 1 means the "
        "budget is being spent on duplicated text."
    ),
    "macro": "Unweighted mean across queries. Reported separately for the expansion-required subset.",
}


async def isolation_probe(env: dict, truth: Truth) -> dict:
    """Scope isolation, verified against a byte-identical foreign document.

    The other owner's `disc` file has the same bytes as OWNER's, so if any of
    its chunk ids appear the cause cannot be a content difference.
    """
    foreign_ids = {
        str(chunk.chunk_id)
        for entry in truth.other_manifest.values()
        for chunk in entry.chunks
    }
    observed: list[str] = []
    searched = 0
    for case in QUERY_CASES:
        pack = await env["orchestrator"].retrieve_for_turn(
            OWNER, [env["manifest"]["disc"].document_id], case.text
        )
        searched += 1
        for evidence in pack.evidences:
            for chunk_id in (evidence.chunk_id, *evidence.expanded_from):
                if str(chunk_id) in foreign_ids:
                    observed.append(f"{case.key}:{chunk_id}")
    own_ids = {str(chunk.chunk_id) for chunk in truth.manifest["disc"].chunks}
    return {
        "foreign_owner": OTHER_OWNER,
        "foreign_chunk_count": len(foreign_ids),
        "queries_run_with_disc_scope": searched,
        "own_disc_chunk_count": len(own_ids),
        "leaks": observed,
        "ok": not observed,
        # Meaningful only once the self-check has confirmed the two owners hold
        # chunk-for-chunk identical text.
        "text_identical_across_owners": (
            [c.text for c in truth.manifest["disc"].chunks]
            == [c.text for c in truth.other_manifest["disc"].chunks]
            if truth.other_manifest
            else False
        ),
    }


# ---------------------------------------------------------------------- main


async def run_evaluate(env: dict, truth: Truth, tmp: Path) -> dict:
    checks = run_selfcheck(truth, QUERY_CASES)
    failed = [item for item in checks if not item["ok"]]
    artifact: dict = {
        "schema": "mathtutor.rag-evaluation/2",
        "generated_by": "scripts/rag_hard_set_probe.py",
        "run_provenance": source_fingerprint(),
        "budgets": budgets(),
        "corpus": {
            "documents": [
                {
                    "key": doc.key,
                    "filename": doc.filename,
                    "document_id": str(env["manifest"][doc.key].document_id),
                    "chunk_count": len(env["manifest"][doc.key].chunks),
                }
                for doc in HARD_DOCS
            ],
            "chunk_manifest": manifest_rows(env["manifest"]),
            "note": "Synthetic fixtures only. No student data, no user PDF text.",
        },
        "annotation_policy": ANNOTATION_POLICY,
        "selfcheck": {
            "status": "OK" if not failed else "BENCHMARK_INVALID",
            "checks": checks,
            "failures": [item["check"] for item in failed],
        },
        "hard": None,
        "easy": None,
        "context": NOT_MEASURED,
        "faithfulness": FAITHFULNESS_NOT_MEASURED,
        "citation": NOT_MEASURED,
        "citation_mutations": NOT_MEASURED,
        "fixture_mutations": NOT_MEASURED,
        "ablations": NOT_MEASURED,
        "semantic": semantic_status(),
        "answer_quality": None,
    }

    if failed:
        # No numbers at all when the fixture cannot support them. A pretty
        # metric computed against an untrue ground truth is worse than none.
        artifact["hard"] = {"status": "BENCHMARK_INVALID", "queries": []}
        return artifact

    corpus_chunks = sum(len(entry.chunks) for entry in env["manifest"].values())
    artifact["hard"] = await evaluate(env, truth)
    artifact["isolation"] = await isolation_probe(env, truth)
    artifact["easy"] = await evaluate_easy(tmp)
    artifact["ablations"] = await evaluate_ablations(env, truth)
    artifact["fixture_mutations"] = await verify_fixture_guards(tmp)
    artifact["answer_quality"] = await answer_quality_export(env, truth)
    # The same retrieval definitions, run over the hard corpus, so easy and
    # hard can be read side by side without switching definitions.
    artifact["hard"]["metrics"] = await official_retrieval_metrics(
        {
            "repository": env["repository"],
            "documents": {
                key: {"document_id": entry.document_id, "chunks": entry.chunks}
                for key, entry in env["manifest"].items()
            },
            "scope": env["scope"],
            "orchestrator": env["orchestrator"],
        },
        [
            (
                case.key,
                case.text,
                tuple(
                    (truth.anchors[anchor].doc, truth.anchors[anchor].sequence)
                    for anchor in case.relevant
                ),
            )
            for case in QUERY_CASES
        ],
    )
    # Where does RR actually come from? Measuring the corpus itself settles it:
    # if the fixture text is already ~90% self-repetitive before retrieval
    # touches it, then RR is mostly a property of the FIXTURE, and quoting it
    # as a product defect would be wrong.
    corpus_texts = [chunk.text for entry in env["manifest"].values() for chunk in entry.chunks]
    corpus_rr = _ngram_redundancy_counts(corpus_texts)
    artifact["context"] = {
        "status": "MEASURED",
        "definitions": METRIC_DEFINITIONS,
        "rr_attribution": {
            "corpus_rr": round(corpus_rr["rate"], 4),
            "corpus_counts": corpus_rr,
            "reading": (
                f"The CORPUS itself scores RR={corpus_rr['rate']:.3f} before any "
                "retrieval. These fixtures repeat a sentence block many times on "
                "purpose, because that is what forces `_split_group_text` to cut "
                "at all. So RR here mostly measures the fixture's own "
                "self-similarity, plus the chunker's fixed overlap window. It is "
                "NOT a product quality finding and must not be quoted as one."
            ),
            "overlap_contribution": (
                "The chunker repeats `overlap_chars` (100) at the head of each "
                "piece; per-query shared-character shares are reported in each "
                "query's counts."
            ),
        },
        "macro": artifact["hard"]["aggregate"],
        "corpus_chunks": corpus_chunks,
        "candidate_limit": env["orchestrator"].candidate_limit,
        "evidence_limit": env["orchestrator"].evidence_limit,
        "discrimination_caveat": (
            f"The corpus holds {corpus_chunks} chunks and the evidence limit is "
            f"{env['orchestrator'].evidence_limit}, so a pack can hold nearly "
            "the whole corpus. Context precision is therefore bounded by pack "
            "size rather than by ranking quality, and a high recall here is "
            "close to guaranteed. These numbers are a floor and a structural "
            "alarm, not a quality claim."
        ),
    }
    artifact["overall"] = {
        "cp_macro": artifact["hard"]["aggregate"]["cp_macro"],
        "cr_macro": artifact["hard"]["aggregate"]["cr_macro"],
        "nr_macro": artifact["hard"]["aggregate"]["nr_macro"],
        "rr_macro": artifact["hard"]["aggregate"]["rr_macro"],
        "scope": "hard set only; easy set not measured in this increment",
        "isolation_ok": artifact["isolation"]["ok"],
        "expansion_leaks": artifact["hard"]["aggregate"]["expansion_leaks"],
    }
    return artifact


async def attach_citations(artifact: dict, tmp: Path) -> None:
    """Claims / citations / mutation alarms, appended to a valid artefact.

    Run separately from `run_evaluate` because it needs its own database: the
    note path and the file-import path are different code, and silently sharing
    one store would let a defect in one hide behind the other.
    """
    harness = await build_knowledge_harness(tmp)
    try:
        result = await evaluate_citations(harness)
        artifact["citation"] = result
        artifact["citation_mutations"] = {
            "status": "MEASURED",
            "scope": (
                "Citation-layer injections only. Kept separate from "
                "fixture_mutations (benchmark self-checks) and from ablations "
                "(component removal): three different things, three verdicts."
            ),
            "injected": [
                row["key"] for row in result["claims"] if row["key"].startswith("INJ")
            ],
            "wrongful_admissions": result["expected_disagreements"],
            "fail_closed_checks": result["fail_closed"],
            "receipt_probes_with_unexpected_outcomes": result["unexpected_lifecycle_outcomes"],
            "verdict": (
                "OK — every injected corruption was rejected and every "
                "expectation matched"
                if not result["expected_disagreements"]
                and not result["unexpected_lifecycle_outcomes"]
                and all(row["rejected"] for row in result["fail_closed"])
                else "ALARM — an injected corruption was not handled as annotated"
            ),
        }
        artifact["overall"]["citation_attribution_precision"] = result["attribution"][
            "precision_macro"
        ]
        artifact["overall"]["citation_attribution_recall"] = result["attribution"]["recall_macro"]
        artifact["overall"]["citation_attribution_claim_cases"] = result["attribution"][
            "claim_cases"
        ]
        artifact["overall"]["unauthorized_historical_read_rejection_rate"] = result[
            "unauthorized_historical_read_rejection_rate"
        ]
    finally:
        await harness["state"].shutdown_runtime()
        await harness["engine"].dispose()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        env = await build(tmp)
        try:
            truth = Truth(env["manifest"], ANCHORS, env["other_manifest"])
            if args.evaluate:
                try:
                    artifact = await run_evaluate(env, truth, tmp)
                except BenchmarkInvalid as error:
                    print(f"BENCHMARK_INVALID — {error}", file=sys.stderr)
                    return 2
                if artifact["selfcheck"]["status"] == "OK":
                    await attach_citations(artifact, tmp)
                if artifact["selfcheck"]["status"] != "OK":
                    print(
                        "BENCHMARK_INVALID — fixture cannot support its own claims:",
                        file=sys.stderr,
                    )
                    for item in artifact["selfcheck"]["failures"]:
                        print(f"  - {item}", file=sys.stderr)
                if args.json:
                    print(json.dumps(artifact, ensure_ascii=False, indent=1))
                else:
                    print_summary(artifact)
                ARTEFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
                ARTEFACT_PATH.write_text(
                    json.dumps(artifact, ensure_ascii=False, indent=1), encoding="utf-8"
                )
                print(f"\nwrote {ARTEFACT_PATH}", file=sys.stderr)
                return 0 if artifact["selfcheck"]["status"] == "OK" else 2

            rows = manifest_rows(env["manifest"])
            if args.json:
                print(json.dumps({"manifest": rows}, ensure_ascii=False, indent=1))
            else:
                for row in rows:
                    parent = " child" if row["parent_chunk_id"] else ""
                    print(
                        f"{row['doc']:8} seq={row['sequence']} type={row['chunk_type']:10}"
                        f" chars={row['chars']:5} terminal={row['ends_terminal']!s:5}"
                        f"{parent} :: {row['preview']}"
                    )
        finally:
            await env["engine"].dispose()
    return 0


def print_summary(artifact: dict) -> None:
    print(f"selfcheck: {artifact['selfcheck']['status']}")
    if artifact["selfcheck"]["status"] == "OK":
        for row in artifact["hard"]["queries"]:
            metrics = row["metrics"]
            print(
                f"{row['key']} [{row['case']}] CP={metrics['cp']:.3f} CR={metrics['cr']:.3f}"
                f" expansion_used={row['retrieval']['expansion_used']}"
                f" selected={[item['chunk'] for item in row['selected']]}"
                f" expanded_from={[item['expanded_from'] for item in row['selected']]}"
            )
            if metrics["required_missing"]:
                print(f"    REQUIRED MISSING: {metrics['required_missing']}")
            if metrics["forbidden_selected"]:
                print(
                    "    FORBIDDEN PRESENT (retrieval noise, priced into CP):"
                    f" {metrics['forbidden_selected']}"
                )
            relation = row.get("observed_relation")
            if relation:
                print(
                    f"    intended {row['case']}, observed {relation['observed']}"
                    f" (matched {relation['matched']}, added {relation['added']})"
                )
            if metrics["distractor_expansion_pulled"]:
                print(
                    "    DISTRACTOR PULLED BY EXPANSION (expected for C4, priced"
                    f" into CP): {metrics['distractor_expansion_pulled']}"
                )
            guard = row["expansion_guard"]
            if guard:
                print(
                    f"    C5 guard exercised={guard['guard_exercised']}"
                    f" holds={guard['holds']} leaks={guard['leaks']}"
                    f" windows={guard['windows_that_contained_the_forbidden_chunk']}"
                )
        agg = artifact["hard"]["aggregate"]
        print(
            f"\nmacro  CP={agg['cp_macro']:.3f} CR={agg['cr_macro']:.3f}"
            f" NR={agg['nr_macro']:.3f} RR={agg['rr_macro']:.3f}"
        )
        subset = agg["expansion_required_subset"]
        print(
            f"expansion-required subset {subset['keys']}"
            f" CP={subset['cp_macro']:.3f} CR={subset['cr_macro']:.3f}"
        )
        print(f"expansion leaks (C5): {agg['expansion_leaks'] or 'none'}")
        print(f"distractor pulled by expansion (C4): {agg['distractor_pulled_by_expansion'] or 'none'}")
        print(f"intent/observation mismatches: {agg['relation_mismatches'] or 'none'}")
        print(f"isolation ok={artifact['isolation']['ok']}")

    easy = artifact.get("easy")
    if easy and easy.get("status") == "MEASURED":
        agg = easy["metrics"]["aggregate"]
        print(
            f"\neasy   {easy['metrics']['eligible_queries']} queries / "
            f"{easy['corpus_chunks']} chunks  "
            f"R@5={agg['recall@5']:.3f} MRR@5={agg['mrr@5']:.3f} "
            f"nDCG@5={agg['ndcg@5']:.3f} Hit@1={agg['hit@1']:.3f}"
        )

    hard_metrics = artifact["hard"].get("metrics")
    if hard_metrics:
        agg = hard_metrics["aggregate"]
        print(
            f"hard   {hard_metrics['eligible_queries']} queries  "
            f"R@5={agg['recall@5']:.3f} MRR@5={agg['mrr@5']:.3f} "
            f"nDCG@5={agg['ndcg@5']:.3f} Hit@1={agg['hit@1']:.3f}"
        )

    ablations = artifact.get("ablations")
    if ablations and ablations.get("status") == "MEASURED":
        print("\nablations (identical corpus / queries / budgets)")
        for name, arm in ablations["arms"].items():
            print(f"  {name:<14} CP={arm['cp_macro']:.4f} CR={arm['cr_macro']:.4f}")
        for name, delta in ablations["deltas_vs_production"].items():
            print(
                f"  {name:<14} dCP={delta['cp_macro_delta']:+.4f}"
                f" dCR={delta['cr_macro_delta']:+.4f}"
            )
        print(f"  no_reranker reading:  {ablations['no_reranker_reading']}")
        print(f"  no_expansion reading: {ablations['no_expansion_reading']}")

    citation = artifact.get("citation")
    if citation and citation.get("status") == "MEASURED":
        attribution = citation["attribution"]
        operational = citation["operational"]
        print(
            f"\ncitation attribution (valid+incorrect) "
            f"P={attribution['precision_macro']:.3f}"
            f" R={attribution['recall_macro']:.3f}"
            f"  cases={attribution['claim_cases']} links={attribution['citation_links']}"
        )
        print(
            f"  operational probes: cases={operational['claim_cases']}"
            f" links={operational['citation_links']}"
            f" rejection={operational['rejection_rate']}"
        )
        print(
            f"  receipt validation={citation['historical_receipt_validation_rate']:.3f}"
            f"  unauthorized rejection={citation['unauthorized_historical_read_rejection_rate']:.3f}"
        )
    for section in ("citation_mutations", "fixture_mutations"):
        payload = artifact.get(section)
        if payload and payload.get("status") == "MEASURED":
            print(f"  {section}: {payload['verdict']}")
    print(f"  semantic: {artifact['semantic']['status']}")
    print(f"  faithfulness: {artifact['faithfulness']['status']}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
