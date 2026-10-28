"""Owner-scoped placement facts. This rule policy is NOT a DKT ability score."""
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from mathtutor.application.multiple_choice import make_choices, resolve_choice
from mathtutor.domain.problem import MathProblem
from mathtutor.learning.knowledge_tracing.schema import initial_assessments
from mathtutor.learning.skills import (SKILL_ARITHMETIC, SKILL_LINEAR_EQUATION,
    SKILL_POLYNOMIAL_BASIC, SKILL_QUADRATIC_EQUATION, SKILL_LINEAR_SYSTEM)
from mathtutor.solving.parser import parse_problem
from mathtutor.solving.solver import solve_problem
from mathtutor.solving.verifier import verify as verify_solution
from mathtutor.security.scopes import student_uuid
from mathtutor.repositories.sqlite_runtime import ensure_student

POLICY = "placement_start_v1"
LABELS = {SKILL_ARITHMETIC: "数与运算", SKILL_LINEAR_EQUATION: "一元一次方程",
          SKILL_POLYNOMIAL_BASIC: "整式运算", SKILL_QUADRATIC_EQUATION: "一元二次方程", SKILL_LINEAR_SYSTEM: "二元一次方程组"}
# Authored engineering probes, NOT a calibrated psychometric test.
ITEMS = (
    (SKILL_ARITHMETIC, "8 + 3 * 2"), (SKILL_ARITHMETIC, "2/5 + 1/3"),
    (SKILL_LINEAR_EQUATION, "x + 5 = 12"), (SKILL_LINEAR_EQUATION, "3x - 4 = 11"),
    (SKILL_POLYNOMIAL_BASIC, "2x + 5x"), (SKILL_POLYNOMIAL_BASIC, "(x + 3)^2"),
    (SKILL_QUADRATIC_EQUATION, "x^2 - 6x + 9 = 0"), (SKILL_QUADRATIC_EQUATION, "x^2 - 6x + 8 = 0"),
    (SKILL_LINEAR_SYSTEM, "x+y=7; x-y=1"), (SKILL_LINEAR_SYSTEM, "2x+y=11; x-y=1"),
)
ASSESSMENT_VERSION = hashlib.sha256(json.dumps({"policy": POLICY, "items": ITEMS},
    ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
# Runs saved before resumable placement did not store the item-set fingerprint.
# Only the exact original v1 policy/items may adopt those existing runs.
LEGACY_V1_VERSION = "f8734067330d1230437d4dea78123cecd0f2268ebc5a845d007c69cf5007825b"


def assessment_version(payload):
    return payload.get("assessment_version", LEGACY_V1_VERSION if payload.get("policy_version") == "placement_start_v1" else "")


def compatible(payload):
    return payload.get("policy_version") == POLICY and assessment_version(payload) == ASSESSMENT_VERSION


def item_at(index, run_id):
    skill, statement = ITEMS[index]
    parsed = parse_problem(statement).problem
    problem = MathProblem.canonicalize(problem_type=parsed.problem_type, normalized_ast=parsed.normalized_ast, display_latex=parsed.display_latex)
    candidate = solve_problem(problem, parsed).candidate
    decision = verify_solution(problem, candidate)
    if decision.verdict != "VERIFIED":
        raise ValueError("初评题未通过验证，暂不能展示。")
    choices = make_choices(problem, candidate, salt=f"{POLICY}:{run_id}:{index}")
    return {"index": index, "skill_id": skill, "skill_label": LABELS[skill],
            "statement": statement, "choices": choices}, problem, candidate


def result_for(payload):
    rows = []
    for skill in dict(ITEMS):
        answers = [a for a in payload["answers"] if a["skill_id"] == skill]
        known = [a for a in answers if a["correctness"] != "unknown"]
        correct = sum(a["correctness"] == "correct" for a in known)
        # Unknown is not incorrect. Two checks only select a tentative starting
        # point; no mastery probability or overall student grade is inferred.
        difficulty = 3 if len(known) == 2 and correct == 2 else 1 if len(known) == 2 and correct == 0 else 2
        rows.append({"skill_id": skill, "label": LABELS[skill], "correct": correct,
            "observed": len(known), "unknown": len(answers) - len(known), "starting_difficulty": difficulty,
            "observation": "尚需更多作答确认" if len(known) < 2 else "可尝试提高练习" if difficulty == 3 else "建议先巩固基础" if difficulty == 1 else "建议从标准练习开始"})
    return {"policy_version": POLICY, "source": "rule_based_initial_assessment", "skills": rows,
        "dkt": {"enabled": False, "probability": None, "reason": "unsupported_target_mapping"},
        "notice": "这是少量选择题得到的练习起点，不是能力定级或 DKT 掌握度；后续会根据独立作答调整。"}


class InitialAssessmentService:
    def __init__(self, engine):
        self.engine = engine

    async def read(self, sid, conn=None):
        sid = str(sid)  # same owner key as the facts/privacy repositories
        if conn is None:
            async with self.engine.connect() as db:
                return await self.read(sid, db)
        return (await conn.execute(select(initial_assessments.c.payload).where(initial_assessments.c.student_id == str(sid)))).scalar_one_or_none()

    async def ensure(self, sid):
        sid = str(sid)
        async with self.engine.begin() as conn:
            await ensure_student(conn, student_id=sid)
            payload = {"run_id": str(uuid4()), "status": "pending", "answers": [], "policy_version": POLICY,
                "assessment_version": ASSESSMENT_VERSION}
            await conn.execute(insert(initial_assessments).values(student_id=str(sid), payload=payload).on_conflict_do_nothing())
            return self.public(await self.read(sid, conn))

    def public(self, payload):
        if payload is None:
            return {"status": "not_started", "total": len(ITEMS), "answered": 0}
        status, index = payload["status"], len(payload["answers"])
        return {"run_id": payload["run_id"], "status": status, "total": len(ITEMS), "answered": index,
            "assessment_version": assessment_version(payload), "can_resume": status == "skipped" and compatible(payload),
            "compatibility_notice": None if compatible(payload) else "这份初评的题目或规则版本已更新，暂不能续做。已有作答保留，可继续学习。",
            "question": item_at(index, payload["run_id"])[0] if compatible(payload) and status in {"pending", "in_progress"} and index < len(ITEMS) else None,
            "result": result_for(payload) if status == "completed" else None}

    async def submit(self, sid, *, run_id, index, option_id, version):
        sid = str(sid)
        async with self.engine.begin() as conn:
            payload = await self.read(sid, conn)
            if not payload or run_id != payload["run_id"]:
                raise ValueError("初评已失效或已删除，请重新打开初评页面。")
            if not compatible(payload):
                raise ValueError("这份初评的题目或规则版本已更新，已有作答保留，请重新同步进度。")
            answers = payload["answers"]
            if index < len(answers):
                old = answers[index]
                if old["option_id"] == option_id and old["version"] == version:
                    return self.public(payload)
                raise ValueError("该题已经提交，首次作答不能覆盖。")
            if payload["status"] not in {"pending", "in_progress"} or index != len(answers) or index >= len(ITEMS):
                raise ValueError("题目进度已更新，请刷新后继续。")
            item, problem, candidate = item_at(index, run_id)
            if version != item["choices"]["version"]:
                raise ValueError("题目版本已更新，请刷新后继续。")
            correctness = "unknown"
            if option_id != "unsure":
                answer = resolve_choice(item["choices"], option_id, version)
                # The independent attempt verifier, not option index, grades.
                from mathtutor.learning.attempt_parser import parse_student_attempt
                from mathtutor.learning.attempt_verifier import verify_attempt
                attempt = parse_student_attempt(attempt_submission_id=uuid4(), student_id=student_uuid(sid), cycle_id=uuid4(), raw_text=answer, attempt_index=1)
                correctness = verify_attempt(attempt, problem, candidate).correctness.value
                if correctness not in {"correct", "incorrect"}:
                    raise ValueError("该选项暂不能可靠判分，请稍后重试。")
            updated = {**payload, "answers": [*answers, {"index": index, "skill_id": item["skill_id"], "option_id": option_id,
                "version": version, "correctness": correctness, "occurred_at": datetime.now(timezone.utc).isoformat()}],
                "status": "completed" if index + 1 == len(ITEMS) else "in_progress"}
            changed = await conn.execute(initial_assessments.update().where(initial_assessments.c.student_id == str(sid),
                initial_assessments.c.payload == payload).values(payload=updated))
            if changed.rowcount != 1:
                raise ValueError("进度已更新，请刷新后继续。")
            return self.public(updated)

    async def skip(self, sid, run_id):
        sid = str(sid)
        async with self.engine.begin() as conn:
            payload = await self.read(sid, conn)
            if not payload or payload["run_id"] != run_id:
                raise ValueError("初评已失效，请刷新后继续。")
            if payload["status"] not in {"completed", "skipped"}:
                changed = await conn.execute(initial_assessments.update().where(initial_assessments.c.student_id == str(sid), initial_assessments.c.payload == payload).values(payload={**payload, "status": "skipped"}))
                if changed.rowcount != 1:
                    raise ValueError("初评进度已更新，请刷新后继续。")
        return {"ok": True}

    async def resume(self, sid, *, run_id, version):
        sid = str(sid)
        async with self.engine.begin() as conn:
            payload = await self.read(sid, conn)
            if not payload or payload["run_id"] != run_id:
                raise ValueError("初评已失效或不属于当前学生，请重新打开初评页面。")
            if not compatible(payload) or version != assessment_version(payload):
                raise ValueError("这份初评的题目或规则版本已更新，已有作答保留，请重新同步进度。")
            if payload["status"] in {"pending", "in_progress", "completed"}:
                return self.public(payload)
            if payload["status"] != "skipped":
                raise ValueError("初评进度已更新，请刷新后继续。")
            updated = {**payload, "status": "in_progress" if payload["answers"] else "pending"}
            changed = await conn.execute(initial_assessments.update().where(initial_assessments.c.student_id == sid,
                initial_assessments.c.payload == payload).values(payload=updated))
            if changed.rowcount != 1:
                raise ValueError("初评进度已更新，请刷新后继续。")
            return self.public(updated)

    async def starting_difficulty(self, sid, skills):
        payload = await self.read(sid)
        if not payload or payload["status"] != "completed":
            return None
        values = [r["starting_difficulty"] for r in result_for(payload)["skills"] if r["skill_id"] in skills]
        return min(values) if values else None
