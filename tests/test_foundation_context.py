import ast
from fractions import Fraction
from itertools import product

import pytest

from mathtutor.application.exploration_evidence import build_source_snapshots, text_hash
from mathtutor.application.foundation_references import FRACTION_UNITS, fraction_foundations
from mathtutor.application.network_qa import AnswerDraft, AnswerReview, NetworkQA, answer_payload, choose_network_task, render_answer
from mathtutor.application.verification_backend import InProcessVerificationBackend
from mathtutor.learning.skill_graph import GRAPH_VERSION, SKILLS
from mathtutor.question_bank.service import QuestionBankService


def exact(source):
    def value(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Fraction(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -value(node.operand)
        if isinstance(node, ast.BinOp):
            left, right = value(node.left), value(node.right)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, ast.Div): return left / right
        raise ValueError("Unsupported development arithmetic")
    return value(ast.parse(source, mode="eval").body)


def test_whole_fraction_curriculum_family_and_original_conditions_are_preserved():
    bank = QuestionBankService()
    expected = {"curriculum:" + row["id"] for point, rows in bank.references.items()
                if point.startswith(FRACTION_UNITS) for row in rows}
    refs = fraction_foundations()
    assert set(refs) == expected | {"review:fraction-domain"}
    assert len(expected) >= 26
    for reference_id in expected:
        row = refs[reference_id]
        assert row["id"] == reference_id and row["version"] == "k12-original-v2"
        assert row["conditions"] == SKILLS["fraction_operations"].definition
        assert row["conditions_version"] == GRAPH_VERSION
        assert row["provider"] == "mathtutor" and row["text_sha256"] == text_hash(row["text"])
        assert row["student_steps_auto_verified"] is False
    addition = refs["review:fraction-domain"]
    assert "added in this iteration" in addition["authorship"]
    assert "not human expert certification" in addition["review_scope"]


def test_all_family_numeric_checks_pass_independent_fraction_evaluation():
    checked = 0
    for row in fraction_foundations().values():
        if not row["answer_check"]:
            continue
        left, right = row["answer_check"].split("=")
        assert exact(left) == exact(right), row["id"]
        assert exact(left) != exact(right) + 1
        checked += 1
    assert checked >= 20


def test_rational_domain_boundaries_and_operations_over_positive_negative_and_zero_values():
    for a, b, c, d in product(range(-2, 3), repeat=4):
        if not b or not d:
            with pytest.raises(ZeroDivisionError):
                Fraction(a, b) + Fraction(c, d)
            continue
        left, right = Fraction(a, b), Fraction(c, d)
        assert left + right == Fraction(a * d + b * c, b * d)
        assert left - right == Fraction(a * d - b * c, b * d)
        assert left * right == Fraction(a * c, b * d)
        if c:
            assert left / right == Fraction(a * d, b * c)
        else:
            with pytest.raises(ZeroDivisionError):
                left / right
    with pytest.raises(ZeroDivisionError):
        1 / Fraction(0)


def fixture():
    task = choose_network_task("分数乘法如何理解？")
    batch = build_source_snapshots([{"ContentID": "12", "ContentType": "Answer", "Title": "合成开发资料",
        "ContentText": "这是一段开发用的材料。", "Url": "https://www.zhihu.com/answer/12"}])
    _, spans, references = answer_payload(task, batch)
    return task, batch, spans, references


def review(**changes):
    return AnswerReview(claims=[{"claim_id": "c1", "supported": True, "conditions_preserved": True,
        "attribution_correct": True, "relevant": True, "relation_correct": True,
        "math_consistency": "not_applicable", **changes}])


def draft(**changes):
    return AnswerDraft(claims=[{"claim_id": "c1", "kind": "ai_inference", "text": "分数相乘时分子相乘、分母相乘。",
        "reference_ids": ["curriculum:g6a-u1-p2-ref-1"], "math": [{"expression": "a/b*c/d", "answer": ""}], **changes}])


async def test_empty_math_answer_stays_unverified_and_authored_reference_is_replayable():
    task, batch, spans, references = fixture()
    proposed = draft()
    shown, audit = await NetworkQA(None, InProcessVerificationBackend()).gate(proposed, review(), spans, references)
    assert shown[0].text == proposed.claims[0].text
    assert audit[0]["math"] == "unsupported"
    assert audit[0]["math_checks"] == [{"expression": "a/b*c/d", "answer": "", "status": "not_submitted", "reason": "empty_answer"}]
    reference = audit[0]["authored_references"][0]
    assert reference == references["curriculum:g6a-u1-p2-ref-1"]
    assert text_hash(reference["text"]) == reference["text_sha256"]
    rendered = render_answer(shown, batch, task.language, audit)
    assert "MathTutor 原创数学基础" in rendered and "数学表述待核对" in rendered
    assert "知乎" not in rendered and "https://www.zhihu.com" not in rendered


@pytest.mark.parametrize("check", [review(supported=False), review(math_consistency="contradicted")])
async def test_empty_math_answer_does_not_override_semantic_rejection(check):
    _, _, spans, references = fixture()
    shown, _ = await NetworkQA(None, InProcessVerificationBackend()).gate(draft(), check, spans, references)
    assert not shown


async def test_automatic_formula_refutation_still_runs_when_requested_answer_is_empty():
    _, _, spans, references = fixture()
    proposed = draft(text="3+4=8", math=[{"expression": "3+4", "answer": ""}])
    shown, audit = await NetworkQA(None, InProcessVerificationBackend()).gate(proposed, review(), spans, references)
    assert not shown and audit[0]["math"] == "incorrect"
    assert audit[0]["math_checks"][0]["reason"] == "empty_answer"


@pytest.mark.parametrize("math", [[{"expression": "a/b", "answer": None}], [{"expression": "a/b"}],
    [{"expression": "a/b", "answer": "", "verified": True}], [{"expression": "", "answer": ""}]])
def test_other_invalid_math_fields_still_fail_closed(math):
    with pytest.raises(ValueError):
        draft(math=math)


def test_public_operation_query_keeps_current_subquestion_without_private_content():
    task = choose_network_task("那分数相乘呢？PRIVATE_PERSON_123", prior_question="分数相加为何需要通分？")
    assert "加法" in task.query and "乘法" in task.query
    assert "PRIVATE" not in task.query and "123" not in task.query
    assert "除法" not in choose_network_task("为什么分数 2/3 可以表示二份三分之一？").query
    assert "除法" in choose_network_task("分数除法应该怎么学？").query
