"""Phase 6 检索评测固定语料（确定性、纯内存、无网络）。

固定的中文数学概念文档集，覆盖任务要求的四类干扰 + 两类阻断：

1. 同义表达：「加法交换律」（规范术语）vs「交换加数位置和不变」
   （口语改写）—— 词面不同、指向同一概念；
2. 多文档干扰：同一主题（加法/二次方程）有多个文档，其中「加法
   结合律」与「加法交换律」共享关键词「加法」却是不同概念；
3. 同一关键词不同概念：「分数」既指分数运算（技能），也指分数的
   历史（无技能编码的百科条目）；
4. 用户禁用文档（retrieval_enabled=false，owner 匹配、词面与 query
   高度重合 → 若泄漏必被词法/向量召回）—— INVARIANT D 的评测面证据；
5. 跨 owner 文档（文本与规范条目逐字相同 → 向量相似度理论上限）——
   owner 隔离的评测面证据；
6. curriculum stage 过滤：小学「简易方程」vs 初中「一元二次方程」
   共享关键词「方程」，stage 过滤必须只放行匹配阶段。

所有条目都是 :class:`RetrievalItem` 投影（application 层契约对象），
与任何数据库无关 —— benchmark 只喂给 MetadataFirstRetriever。ground
truth 以 item_id 的 frozenset 表达；`retrieval_enabled=false` /
跨 owner 条目**不在**任何 ground truth 里（它们在任何链路贡献都为零）。
"""

from __future__ import annotations

from dataclasses import dataclass

from mathtutor.application.practice_release import (
    mapping_id_for_concept,
    mapping_id_for_skill,
)
from mathtutor.application.retrieval_router import RetrievalItem
from mathtutor.learning.skills import (
    CONCEPT_LINEAR_EQUATIONS,
    CONCEPT_NUMBER_OPERATIONS,
    CONCEPT_QUADRATIC_EQUATIONS,
    SKILL_ARITHMETIC,
    SKILL_LINEAR_EQUATION,
    SKILL_QUADRATIC_EQUATION,
)

# ---------------------------------------------------------------- owners

OWNER_A = "student-a"
OWNER_B = "student-b"  # 干扰 owner：任何链路都不得返回其条目

# ------------------------------------------------------------- item ids

ADD_COMMUTATIVE_CANON = "add-commutative-canon"
ADD_COMMUTATIVE_REWORD = "add-commutative-reword"
ADD_ASSOCIATIVE_DISTRACTOR = "add-associative-distractor"
FRACTION_ARITHMETIC = "fraction-arithmetic"
FRACTION_HISTORY = "fraction-history"
QUADRATIC_FORMULA = "quadratic-formula"
QUADRATIC_DISCRIMINANT = "quadratic-discriminant"
SIMPLE_EQUATION_PRIMARY = "simple-equation-primary"
TRIG_HIGH = "trig-high"
DISABLED_ADD_COMMUTATIVE = "disabled-add-commutative"
FOREIGN_ADD_COMMUTATIVE = "foreign-add-commutative"

# 与规范条目逐字相同的文本（向量相似度理论上限 1.0）。
_COMMUTATIVE_TEXT = "加法交换律：两个数相加，交换加数的位置，和不变。例如 3+5=5+3。"

_ARITH_SKILLS = (SKILL_ARITHMETIC,)
_ARITH_CONCEPTS = (CONCEPT_NUMBER_OPERATIONS,)
_ARITH_MAPPINGS = (
    str(mapping_id_for_skill(SKILL_ARITHMETIC)),
    str(mapping_id_for_concept(CONCEPT_NUMBER_OPERATIONS)),
)


def build_corpus() -> list[RetrievalItem]:
    """固定语料（每次调用返回等价的全新 RetrievalItem 集合）。"""
    return [
        RetrievalItem(
            item_id=ADD_COMMUTATIVE_CANON,
            text=_COMMUTATIVE_TEXT,
            source_type="curriculum",
            owner_scope=OWNER_A,
            retrieval_enabled=True,
            stage="primary",
            grade=3,
            skill_codes=_ARITH_SKILLS,
            concept_codes=_ARITH_CONCEPTS,
            mapping_ids=_ARITH_MAPPINGS,
        ),
        RetrievalItem(
            item_id=ADD_COMMUTATIVE_REWORD,
            text="交换两个加数的位置，它们的和不变，这就是加法交换律。",
            source_type="curriculum",
            owner_scope=OWNER_A,
            retrieval_enabled=True,
            stage="primary",
            grade=3,
            skill_codes=_ARITH_SKILLS,
            concept_codes=_ARITH_CONCEPTS,
            mapping_ids=_ARITH_MAPPINGS,
        ),
        RetrievalItem(
            item_id=ADD_ASSOCIATIVE_DISTRACTOR,
            text="加法结合律：三个数相加，先把前两个数相加，或先把后两个数相加，和不变。",
            source_type="curriculum",
            owner_scope=OWNER_A,
            retrieval_enabled=True,
            stage="primary",
            grade=3,
            skill_codes=_ARITH_SKILLS,
            concept_codes=_ARITH_CONCEPTS,
            mapping_ids=_ARITH_MAPPINGS,
        ),
        RetrievalItem(
            item_id=FRACTION_ARITHMETIC,
            text="分数运算：同分母分数相加，分母不变，只把分子相加，结果要约分化简。",
            source_type="curriculum",
            owner_scope=OWNER_A,
            retrieval_enabled=True,
            stage="primary",
            grade=5,
            skill_codes=_ARITH_SKILLS,
            concept_codes=_ARITH_CONCEPTS,
            mapping_ids=_ARITH_MAPPINGS,
        ),
        RetrievalItem(
            item_id=FRACTION_HISTORY,
            text="分数的历史：分数最早出现在古埃及的纸草书中，用来表示部分与整体的关系。",
            source_type="curriculum",
            owner_scope=OWNER_A,
            retrieval_enabled=True,
            stage="primary",
            grade=5,
            # 无技能/概念编码：百科性条目，纯文本级干扰。
            skill_codes=(),
            concept_codes=(),
            mapping_ids=(),
        ),
        RetrievalItem(
            item_id=QUADRATIC_FORMULA,
            text="一元二次方程的求根公式：x = (-b ± √(b²-4ac)) / (2a)，其中 a≠0。",
            source_type="curriculum",
            owner_scope=OWNER_A,
            retrieval_enabled=True,
            stage="middle",
            grade=9,
            skill_codes=(SKILL_QUADRATIC_EQUATION,),
            concept_codes=(CONCEPT_QUADRATIC_EQUATIONS,),
            mapping_ids=(
                str(mapping_id_for_skill(SKILL_QUADRATIC_EQUATION)),
                str(mapping_id_for_concept(CONCEPT_QUADRATIC_EQUATIONS)),
            ),
        ),
        RetrievalItem(
            item_id=QUADRATIC_DISCRIMINANT,
            text="一元二次方程的判别式 Δ = b²-4ac：大于零有两个实根，等于零一个实根，小于零无实根。",
            source_type="curriculum",
            owner_scope=OWNER_A,
            retrieval_enabled=True,
            stage="middle",
            grade=9,
            skill_codes=(SKILL_QUADRATIC_EQUATION,),
            concept_codes=(CONCEPT_QUADRATIC_EQUATIONS,),
            mapping_ids=(
                str(mapping_id_for_skill(SKILL_QUADRATIC_EQUATION)),
                str(mapping_id_for_concept(CONCEPT_QUADRATIC_EQUATIONS)),
            ),
        ),
        RetrievalItem(
            item_id=SIMPLE_EQUATION_PRIMARY,
            text="简易方程：小学阶段用字母 x 表示未知数，例如 3+x=5，解得 x=2。",
            source_type="curriculum",
            owner_scope=OWNER_A,
            retrieval_enabled=True,
            stage="primary",
            grade=5,
            skill_codes=(SKILL_LINEAR_EQUATION,),
            concept_codes=(CONCEPT_LINEAR_EQUATIONS,),
            mapping_ids=(
                str(mapping_id_for_skill(SKILL_LINEAR_EQUATION)),
                str(mapping_id_for_concept(CONCEPT_LINEAR_EQUATIONS)),
            ),
        ),
        RetrievalItem(
            item_id=TRIG_HIGH,
            text="高中三角函数：sin、cos、tan 由直角三角形锐角定义，高中扩展到任意角的单位圆定义。",
            source_type="curriculum",
            owner_scope=OWNER_A,
            retrieval_enabled=True,
            stage="high",
            grade=11,
            skill_codes=(),
            concept_codes=(),
            mapping_ids=(),
        ),
        # ---- 阻断条目：任何链路（含向量/reranker）都绝不允许出现 ----
        RetrievalItem(
            item_id=DISABLED_ADD_COMMUTATIVE,
            text="加法交换律口诀：两数相加，交换位置，和不变。",
            source_type="user_document",
            owner_scope=OWNER_A,
            retrieval_enabled=False,  # INVARIANT D：用户关闭检索的文档
            stage="primary",
            grade=3,
            skill_codes=_ARITH_SKILLS,
            concept_codes=_ARITH_CONCEPTS,
            mapping_ids=_ARITH_MAPPINGS,
        ),
        RetrievalItem(
            item_id=FOREIGN_ADD_COMMUTATIVE,
            text=_COMMUTATIVE_TEXT,  # 与规范条目逐字相同 → 向量相似度 1.0
            source_type="user_document",
            owner_scope=OWNER_B,  # 别的学生：owner 隔离必须阻断
            retrieval_enabled=True,
            stage="primary",
            grade=3,
            skill_codes=_ARITH_SKILLS,
            concept_codes=_ARITH_CONCEPTS,
            mapping_ids=_ARITH_MAPPINGS,
        ),
    ]


# ------------------------------------------------------------ queries


@dataclass(frozen=True)
class BenchmarkQuery:
    """一条评测 query + ground truth（relevant 为 item_id frozenset）。

    ``stage``/``grade`` 为 None 表示该维度不过滤；owner 恒为 OWNER_A。
    """

    query: str
    relevant_ids: frozenset[str]
    stage: str | None = None
    grade: int | None = None
    skill_codes: tuple[str, ...] = ()
    concept_codes: tuple[str, ...] = ()
    mapping_ids: tuple[str, ...] = ()


BENCHMARK_QUERIES: tuple[BenchmarkQuery, ...] = (
    # 同义表达：规范术语 query 必须命中两条同概念文档；结合律是干扰。
    BenchmarkQuery(
        query="加法交换律",
        relevant_ids=frozenset({ADD_COMMUTATIVE_CANON, ADD_COMMUTATIVE_REWORD}),
        stage="primary",
    ),
    # 同义表达（反向）：口语改写 query 也必须命中规范条目。
    BenchmarkQuery(
        query="交换加数的位置 和不变",
        relevant_ids=frozenset({ADD_COMMUTATIVE_CANON, ADD_COMMUTATIVE_REWORD}),
        stage="primary",
    ),
    # 同一关键词不同概念：分数运算 vs 分数历史。
    BenchmarkQuery(
        query="分数怎么相加",
        relevant_ids=frozenset({FRACTION_ARITHMETIC}),
        stage="primary",
    ),
    BenchmarkQuery(
        query="分数最早出现在什么时候",
        relevant_ids=frozenset({FRACTION_HISTORY}),
        stage="primary",
    ),
    # 多文档干扰：同一主题两条 chunk 都相关。
    BenchmarkQuery(
        query="一元二次方程的求根公式",
        relevant_ids=frozenset({QUADRATIC_FORMULA, QUADRATIC_DISCRIMINANT}),
        stage="middle",
    ),
    # curriculum stage 过滤：小学 stage 下共享「方程」关键词的初中条目
    # 必须被过滤层排除，即使词法/向量都能召回它。
    BenchmarkQuery(
        query="方程",
        relevant_ids=frozenset({SIMPLE_EQUATION_PRIMARY}),
        stage="primary",
        grade=5,
    ),
    # 技能过滤：只放行 ARITHMETIC 技能条目。
    BenchmarkQuery(
        query="加法",
        relevant_ids=frozenset({ADD_COMMUTATIVE_CANON, ADD_COMMUTATIVE_REWORD}),
        skill_codes=_ARITH_SKILLS,
    ),
)

# 所有链路都必须零贡献的条目（禁用 + 跨 owner）。
ZERO_CONTRIBUTION_IDS: frozenset[str] = frozenset(
    {DISABLED_ADD_COMMUTATIVE, FOREIGN_ADD_COMMUTATIVE}
)


__all__ = [
    "ADD_ASSOCIATIVE_DISTRACTOR",
    "ADD_COMMUTATIVE_CANON",
    "ADD_COMMUTATIVE_REWORD",
    "BENCHMARK_QUERIES",
    "BenchmarkQuery",
    "DISABLED_ADD_COMMUTATIVE",
    "FOREIGN_ADD_COMMUTATIVE",
    "FRACTION_ARITHMETIC",
    "FRACTION_HISTORY",
    "OWNER_A",
    "OWNER_B",
    "QUADRATIC_DISCRIMINANT",
    "QUADRATIC_FORMULA",
    "SIMPLE_EQUATION_PRIMARY",
    "TRIG_HIGH",
    "ZERO_CONTRIBUTION_IDS",
    "build_corpus",
]
