"""An inquiry keeps its sources, learner responses and next step together."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from mathtutor.application.exploration_evidence import (
    EvidencePlan,
    SourceBatch,
    build_evidence_spans,
    build_source_snapshots,
    compile_evidence_plan,
)
from mathtutor.application.exploration_learning import (
    LearningObservation,
    build_learning_plan,
    check_feedback,
    explain_check,
    grade_check,
    public_check,
)
from mathtutor.infrastructure.zhihu import (
    ZhihuClient,
    ZhihuError,
    localize_reading_question,
)
from mathtutor.repositories.exploration_repository import (
    ExplorationConflict,
    ExplorationRepository,
)

POLICY = "zhihu_inquiry_v1"


class ExplorationService:
    def __init__(self, engine, secret_store, *, client=None):
        self.repository = ExplorationRepository(engine)
        self.client = client or ZhihuClient(secret_store)

    async def _load(self, owner, inquiry_id, revision=None):
        row = await self.repository.get(owner, inquiry_id)
        if row is None:
            raise LookupError("这个探索问题已不存在。")
        if row["payload"].get("policy") != POLICY:
            raise ExplorationConflict("这份探索记录使用了不同规则，暂不能继续修改。")
        if revision is not None and row["revision"] != revision:
            raise ExplorationConflict("此问题已有更新，请重新打开后继续。")
        return row

    @staticmethod
    def _learning(payload, language):
        return build_learning_plan(payload["question"], payload["goal"], payload["observations"], language=language)

    def public(self, row, language="zh"):
        payload = row["payload"]
        last_check = payload.get("last_check")
        feedback = payload.get("last_feedback", "")
        if last_check and payload.get("last_correctness"):
            check_id = last_check["check_id"]
            last_check = public_check(check_id, language).model_dump(mode="json")
            feedback = check_feedback(check_id, payload["last_correctness"], language)
        evidence = EvidencePlan.model_validate(payload["evidence"])
        evidence = evidence.model_copy(update={
            "cards": tuple(card.model_copy(update={"reading_question": localize_reading_question(card.reading_question, language)})
                           for card in evidence.cards),
            "comparisons": tuple(item.model_copy(update={"reading_question": localize_reading_question(item.reading_question, language)})
                                 for item in evidence.comparisons),
        })
        return {"inquiry_id": row["inquiry_id"], "revision": row["revision"], "updated_at": row["updated_at"],
                "question": payload["question"], "goal": payload["goal"], "reflection": payload["reflection"],
                "evidence": evidence,
                "learning": self._learning(payload, language), "ai_status": payload["ai_status"],
                "organization_attempts": payload["organization_attempts"],
                "last_feedback": feedback, "last_check": last_check,
                "last_correctness": payload.get("last_correctness"),
                "observation_count": len(payload["observations"])}

    async def read(self, owner, inquiry_id, language="zh"):
        return self.public(await self._load(owner, inquiry_id), language)

    async def create(self, owner, *, inquiry_id, generation, question, goal, language="zh"):
        previous = await self.repository.get(owner, inquiry_id)
        if previous:
            if previous["payload"]["question"] != question or previous["payload"]["goal"] != goal:
                raise ExplorationConflict("同一个探索请求不能替换问题，请重新开始。")
            return self.public(previous, language)
        await self.repository.can_create(owner, generation)
        result = await self.client.search(str(owner), question)
        batch = build_source_snapshots(result["Items"], request_id=result["SearchHashId"],
                                       retrieved_at=datetime.now(UTC).isoformat(), max_sources=6)
        evidence = compile_evidence_plan(batch, question=question, max_cards=6)
        payload = {"policy": POLICY, "question": question, "goal": goal, "reflection": "",
                   "observations": [], "evidence": evidence.model_dump(mode="json"),
                   "ai_status": "not_requested", "organization_attempts": 0,
                   "last_feedback": "", "last_check": None, "last_correctness": None}
        row = await self.repository.save(owner, inquiry_id, payload, expected_revision=0,
                                         expected_generation=generation)
        return self.public(row, language)

    async def organize(self, owner, inquiry_id, *, revision, language="zh"):
        row = await self._load(owner, inquiry_id, revision)
        payload = deepcopy(row["payload"])
        if payload["organization_attempts"] >= 2:
            raise ExplorationConflict("本次问题已整理两次，现有材料与阅读建议仍可使用。")
        evidence = EvidencePlan.model_validate(payload["evidence"])
        if not evidence.sources:
            raise ExplorationConflict("还没有可供整理的来源，请换一个具体问题。")
        batch = SourceBatch(sources=evidence.sources, rejected=evidence.source_rejections,
                            input_limited=any(gap.code == "source_limit_reached" for gap in evidence.gaps))
        spans = build_evidence_spans(batch)
        by_source = [[span for span in spans if span.source_id == source.source_id]
                     for source in batch.sources]
        reading_spans = [group[index] for index in range(max(map(len, by_source)))
                         for group in by_source if index < len(group)][:18]
        payload["organization_attempts"] += 1
        reserved = await self.repository.save(owner, inquiry_id, payload, expected_revision=revision)
        try:
            candidate = await self.client.propose(str(owner), question=payload["question"], goal=payload["goal"],
                spans=[{"span_id": span.span_id, "text": span.text, "context": span.context}
                       for span in reading_spans], language=language)
            organized = compile_evidence_plan(batch, candidate, question=payload["question"], max_cards=6)
            payload["evidence"] = organized.model_dump(mode="json")
            payload["ai_status"] = "unavailable" if organized.rejected_candidate_items else "ready"
        except ZhihuError:
            payload["ai_status"] = "unavailable"
        row = await self.repository.save(owner, inquiry_id, payload, expected_revision=reserved["revision"])
        return self.public(row, language)

    async def reflect(self, owner, inquiry_id, *, revision, reflection, language="zh"):
        row = await self._load(owner, inquiry_id, revision)
        payload = deepcopy(row["payload"])
        payload["reflection"] = reflection
        return self.public(await self.repository.save(owner, inquiry_id, payload, expected_revision=revision), language)

    async def check(self, owner, inquiry_id, *, revision, check_id, answer=None, show_explanation=False, language="zh"):
        row = await self._load(owner, inquiry_id, revision)
        payload = deepcopy(row["payload"])
        plan = self._learning(payload, language)
        if plan.check is None or plan.check.check_id != check_id:
            raise ExplorationConflict("检查题已变化，请使用当前题目。")
        if len(payload["observations"]) >= 40:
            raise ExplorationConflict("本次理解检查已结束，可以记录疑点或开始新的探索。")
        payload["last_check"] = plan.check.model_dump(mode="json")
        if show_explanation:
            observation = LearningObservation(event_id=str(uuid4()), event_type="answer_exposed",
                concept_id=plan.check.concept_id, item_id=check_id, assistance="answer_seen",
                occurred_at=datetime.now(UTC).isoformat())
            payload["last_feedback"] = explain_check(check_id, language)
            payload["last_correctness"] = "explanation"
        else:
            result = grade_check(check_id, answer or "", observation_id=str(uuid4()),
                                 prior_observations=payload["observations"], language=language)
            observation = result.observation
            payload["last_feedback"] = result.feedback
            payload["last_correctness"] = result.correctness
        payload["observations"].append(observation.model_dump(mode="json"))
        return self.public(await self.repository.save(owner, inquiry_id, payload, expected_revision=revision), language)
