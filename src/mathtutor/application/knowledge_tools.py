"""Typed application tools. Text from documents can never grant capabilities."""
from __future__ import annotations

import asyncio
import json
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from mathtutor.application.knowledge import KnowledgeError, digest
from mathtutor.infrastructure.knowledge_schema import drafts
from mathtutor.domain.evidence import RetrievalExecution, RetrievalHop, text_hash
from mathtutor.domain.dual_channel_gate import (
    MathState, SourceState, Treatment, decide, math_state_from_correctness)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Search(Strict):
    query: str = Field(min_length=1, max_length=1000)
    section: str = Field(default="问答", max_length=120)
    plan: list[str] = Field(default_factory=list, max_length=4)


class Read(Strict):
    document_id: UUID
    version: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)


class Empty(Strict):
    pass


class ReadCitation(Strict):
    """Historical citation read. A DIFFERENT mode from active ``read_source``.

    The range must equal the receipt's range exactly — a receipt proves a
    range was surfaced, it does not grant a wider read.
    """
    receipt_id: str = Field(min_length=1, max_length=80)
    start: int = Field(ge=0)
    end: int = Field(ge=1)


class Verify(Strict):
    expression: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=500)


class Evidence(Strict):
    source_id: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1, max_length=1800)


class Claim(Strict):
    text: str = Field(min_length=1, max_length=1800)
    kind: Literal["quote", "summary"] = Field(description=(
        "quote 仅用于逐字摘录：必须恰有一条 evidence 且 text == evidence[0].quote，"
        "不得添加‘资料指出’等前缀或改写。凡解释、概括、改写均标 summary，并接受证据支持检查。"
        "没有资料支持的结论不要放进 claims；缺失信息写入 uncertainties。"))
    evidence: list[Evidence] = Field(min_length=1, max_length=4)


class Section(Strict):
    heading: str = Field(min_length=1, max_length=120)
    claims: list[Claim] = Field(min_length=1, max_length=5)


class Draft(Strict):
    title: str = Field(min_length=1, max_length=100)
    sections: list[Section] = Field(min_length=1, max_length=4)
    conflicts: list[str] = Field(default_factory=list, max_length=8)
    suggestions: list[str] = Field(default_factory=list, max_length=5)


class Save(Strict):
    draft_id: str = Field(min_length=1, max_length=80)


class MathAssertion(Strict):
    """A mathematical conclusion the answer relies on, submitted for the math channel."""
    expression: str = Field(min_length=1, max_length=500, description="题目或方程，如 3x-5=10")
    answer: str = Field(min_length=1, max_length=500, description="回答中给出的结论，如 x=5")
    claim_index: int | None = Field(default=None, ge=0, le=11, description=(
        "该结论所在 claim 的下标；不属于任何 claim 时省略"))


class Final(Strict):
    claims: list[Claim] = Field(default_factory=list, max_length=12)
    uncertainties: list[str] = Field(default_factory=list, max_length=8)
    math_assertions: list[MathAssertion] = Field(default_factory=list, max_length=8, description=(
        "回答中每个数学结论都要列出，由确定性验证器核验；未列出的数学结论不得写进 claims"))


class ToolReceipt(Strict):
    ok: bool
    tool: str
    call_id: str
    result: dict | None = None
    code: str | None = None
    message: str | None = None


SCHEMAS = {"search_knowledge": Search, "read_source": Read, "read_citation": ReadCitation,
           "read_learning_context": Empty, "verify_math": Verify, "draft_note": Draft,
           "save_note": Save, "propose_practice": Empty}
DESCRIPTIONS = {
    "search_knowledge": "仅在会话显式范围内检索。整理任务先提供完整章节 plan，再逐 section 检索；结果不是已读取的证据。",
    "read_source": "读取实际版本及字符区间，返回可引用 source_id；只能读取 search_knowledge 的命中。",
    "read_citation": "重新校验一条历史引用凭证并读取其原始区间；区间必须与凭证完全一致，"
                     "不得扩大。资料被删除后凭证失效。",
    "read_learning_context": "读取合法证据摘要与明确偏好，不返回题目答案，不写掌握事实。",
    "verify_math": "用已有隔离数学验证器检验给定表达式和候选答案，不标记学生成功。",
    "draft_note": "按冻结计划生成有来源的摘录/总结草稿，单列冲突与延伸建议，持久预览。",
    "save_note": "将已验证草稿保存为新笔记，仅当用户明确授权。不能覆盖旧笔记。",
    "propose_practice": "仅当用户明确要求时，经既有练习 ReleaseGate 提案，不能直接发布模型题目。",
}


class KnowledgeTools:
    def __init__(self, state, owner, cid, *, generation, save_space="", allow_save=False,
                 practice=None, synthesize=False):
        self.state, self.knowledge, self.owner, self.cid = state, state.knowledge, owner, cid
        self.generation, self.save_space, self.allow_save = generation, save_space, allow_save
        self.practice, self.synthesize = practice, synthesize
        self.plan, self.searched_sections = [], set()
        self.search_hits, self.reads, self.receipts = {}, {}, []
        self.saved, self.draft_results = [], []
        self.practice_result = None
        self.support_checker = None
        self.gate_log = []
        self.retrieval_execution = RetrievalExecution()

    def definitions(self):
        return [{"type": "function", "function": {"name": name, "description": DESCRIPTIONS[name],
                "parameters": schema.model_json_schema()}} for name, schema in SCHEMAS.items()]

    async def execute(self, name, arguments, call_id):
        try:
            if name not in SCHEMAS:
                receipt = ToolReceipt(ok=False, code="UNKNOWN_TOOL", tool=str(name), call_id=call_id).model_dump(exclude_none=True)
                self.receipts.append(receipt)
                return receipt
            parsed = SCHEMAS[name].model_validate(arguments)
            if await self.knowledge.generation(self.owner) != self.generation:
                raise KnowledgeError("资料范围已变化，旧任务不能继续读取或保存。")
            result = await asyncio.wait_for(self._dispatch(name, parsed), timeout=20)
            receipt = {"ok": True, "tool": name, "call_id": call_id, "result": result}
        except ValidationError:
            receipt = {"ok": False, "code": "INVALID_ARGUMENTS", "tool": name, "call_id": call_id}
        except (KnowledgeError, ValueError) as exc:
            receipt = {"ok": False, "code": "REJECTED", "tool": name, "call_id": call_id, "message": str(exc)[:300]}
        except TimeoutError:
            receipt = {"ok": False, "code": "TOOL_TIMEOUT", "tool": name, "call_id": call_id}
        except asyncio.CancelledError:
            raise
        except Exception:
            receipt = {"ok": False, "code": "TOOL_FAILED", "tool": name, "call_id": call_id}
        receipt = ToolReceipt.model_validate(receipt).model_dump(exclude_none=True)
        self.receipts.append(receipt)
        self._record_tool_metric(name, receipt)
        return receipt

    def _record_tool_metric(self, name, receipt):
        """Count executed retrieval tools.

        ``tool_search_calls`` against ``rag_retrieval_requested_total`` is how
        "did the agent need to go beyond the system-side initial retrieval?"
        becomes visible. Recorded for both outcomes: a REJECTED search still
        means the model tried, and that distinction is the diagnostic.
        """
        metrics = getattr(self.state, "metrics", None)
        if metrics is None:
            return
        try:
            metrics.record_tool_call(str(name))
        except Exception:
            # Telemetry is never allowed to break a tool call.
            pass

    async def seed_evidence(self, pack):
        """Make system-side initial evidence readable, without weakening the
        hit restriction.

        Phase C retrieves before the model is called, but ``read_source``
        accepts only ``(document_id, version, start, end)`` tuples that a
        search actually produced. Without this the initial evidence would be
        context the model can see but never cite, forcing a redundant search
        for anything it wants to quote.

        The offsets are DERIVED here (a versioned body is the chunks joined by
        newlines) and then verified against the body before being registered —
        a derived range is only trusted once it demonstrably addresses the
        exact text. Nothing is registered on a mismatch, so the guarantee that
        the model cannot conjure a range is unchanged: every accepted tuple
        still points at text that exists.

        Returns how many evidences became readable.
        """
        if pack is not None:
            self.retrieval_execution = pack.execution
        if pack is None or not getattr(pack, "evidences", None):
            return 0
        repository = getattr(self.state, "document_repository", None)
        if repository is None:
            return 0

        seeded = 0
        for evidence in pack.evidences:
            try:
                chunks = await repository.list_chunks(self.owner, evidence.document_id)
            except Exception:
                continue
            ordered = sorted(chunks, key=lambda chunk: chunk.sequence)
            offsets: dict[int, int] = {}
            cursor = 0
            for chunk in ordered:
                offsets[chunk.sequence] = cursor
                cursor += len(chunk.text) + 1  # snapshot() joins with "\n"

            target = next(
                (chunk for chunk in ordered if chunk.chunk_id == evidence.chunk_id), None
            )
            if target is None:
                continue
            # The evidence must actually be THIS chunk, or a bounded projection
            # of it: a plain or pack-truncated evidence is a prefix of the
            # chunk, an expanded one contains it. Without this check a caller
            # could pair arbitrary text with a real chunk id and register a
            # range whose read-back says something else entirely.
            if not (
                target.text.startswith(evidence.text) or target.text in evidence.text
            ):
                continue
            start = offsets[target.sequence]
            end = start + len(target.text)
            try:
                row = await self.knowledge.snapshot(self.owner, str(evidence.document_id))
            except Exception:
                continue
            body = row.get("body", "")
            # Fail closed: register only ranges that address this exact text.
            if start < 0 or end > len(body) or body[start:end] != target.text:
                continue
            self.search_hits[
                (str(evidence.document_id), row["version"], start, end)
            ] = "初始检索"
            seeded += 1
        return seeded

    async def _dispatch(self, name, args):
        if name == "search_knowledge":
            if args.plan:
                if any(not x.strip() or len(x) > 120 for x in args.plan) or len(set(args.plan)) != len(args.plan):
                    raise KnowledgeError("章节计划无效。")
                if self.plan and self.plan != args.plan:
                    raise KnowledgeError("章节计划已冻结。")
                self.plan = args.plan
            if self.synthesize and (not self.plan or args.section not in self.plan):
                raise KnowledgeError("整理任务须先给出章节计划，并按章节检索。")
            result = await self.knowledge.search(self.owner, self.cid, args.query)
            hop = RetrievalHop(
                hop_index=self.retrieval_execution.hop_count + 1,
                kind="AGENT_SEARCH", result_count=len(result["hits"]),
                query_fingerprint=text_hash(args.query),
            )
            self.retrieval_execution = self.retrieval_execution.model_copy(
                update={"hops": (*self.retrieval_execution.hops, hop)}
            )
            result["retrieval_hop"] = hop.model_dump()
            self.searched_sections.add(args.section)
            for hit in result["hits"]:
                self.search_hits[(hit["document_id"], hit["version"], hit["start"], hit["end"])] = args.section
            return result
        if name == "read_source":
            key = (str(args.document_id), args.version, args.start, args.end)
            if key not in self.search_hits:
                raise KnowledgeError("先检索，再读取真实命中区间；不能猜测资料 ID 或范围。")
            result = await self.knowledge.read_source(self.owner, self.cid, *key)
            source_id = "s-" + digest([key, result["body_hash"]])[:24]
            result.update(source_id=source_id, section=self.search_hits[key])
            self.reads[source_id] = result
            # Issue a server-side receipt for exactly this range. It grants no
            # new authority; it lets the citation stay VERIFIABLE after the
            # document is later disabled, which active retrieval cannot.
            receipt_id = await self.knowledge.issue_citation_receipt(
                self.owner, self.cid, did=args.document_id, version=args.version,
                start=args.start, end=args.end, body_hash=result["body_hash"],
                source_id=source_id, generation=self.generation)
            result["receipt_id"] = receipt_id
            return result
        if name == "read_citation":
            # Historical mode: no search_hits requirement (the range was
            # surfaced in an EARLIER turn), but exact-range equality, owner,
            # conversation and immutable-hash checks all still apply.
            return await self.knowledge.read_citation_receipt(
                self.owner, self.cid, args.receipt_id, args.start, args.end)
        if name == "read_learning_context":
            summary = await self.state.student_state.summary(self.owner) if self.state.student_state else {}
            review = await self.state.stage_review.read(self.owner) if getattr(self.state, "stage_review", None) else None
            return {"evidence": summary, "stage_review": review, "mastery_probability": None,
                    "model_status": "unsupported_target", "read_only": True}
        if name == "verify_math":
            from mathtutor.application.math_verification import ExpressionNotVerifiable, assess_answer, verified_problem
            try:
                problem, candidate = await verified_problem(self.state.verification_backend, args.expression)
            except ExpressionNotVerifiable:
                raise KnowledgeError("该表达式未通过数学验证。") from None
            assessed = await assess_answer(self.state.verification_backend, problem, candidate, args.answer)
            return {"correctness": assessed.correctness.value, "learning_fact_written": False}
        if name == "draft_note":
            if not self.plan or [s.heading for s in args.sections] != self.plan or not set(self.plan).issubset(self.searched_sections):
                raise KnowledgeError("草稿必须覆盖已计划并检索的章节。")
            for section in args.sections:
                if any(self.reads.get(e.source_id, {}).get("section") != section.heading for c in section.claims for e in c.evidence):
                    raise KnowledgeError("章节引用必须来自该章节实际读取的证据。")
            claims = [c for s in args.sections for c in s.claims]
            await self.validate_claims(claims)
            markdown = "# " + args.title + "\n\n" + "\n\n".join(
                "## " + section.heading + "\n\n" + self.render_claims(section.claims) for section in args.sections)
            markdown += "\n\n## 冲突与未确定事项\n" + ("\n".join("- " + x for x in args.conflicts) or "- 当前检索未识别到冲突；不代表资料不存在冲突。")
            markdown += "\n\n## 延伸建议（非原文结论）\n" + ("\n".join("- " + x for x in args.suggestions) or "- 暂无。")
            draft_id = "d-" + digest([self.cid, args.model_dump(), self.generation])[:32]
            payload = {"draft_id": draft_id, "title": args.title, "markdown": markdown, "plan": self.plan,
                "sources": list(self.reads.values()), "generation": self.generation, "conversation_id": self.cid}
            async with self.knowledge.engine.begin() as db:
                await self.knowledge.guard_generation(db, self.owner, self.generation)
                await db.execute(insert(drafts).values(student_id=self.owner, draft_id=draft_id,
                    generation=self.generation, payload=payload).on_conflict_do_nothing())
            self.draft_results.append(payload)
            return {"draft_id": draft_id, "preview": markdown, "saved": False}
        if name == "save_note":
            if not self.allow_save or not self.save_space:
                raise KnowledgeError("用户尚未明确授权保存新笔记或指定目标库；草稿可先预览。")
            async with self.knowledge.engine.connect() as db:
                row = (await db.execute(select(drafts).where(drafts.c.student_id == self.owner,
                    drafts.c.draft_id == args.draft_id, drafts.c.generation == self.generation))).mappings().first()
            if not row or row["payload"]["conversation_id"] != self.cid:
                raise KnowledgeError("草稿不存在、已过期或属于其他会话。")
            payload = row["payload"]
            for source in payload["sources"]:
                actual = await self.knowledge.read_source(self.owner, self.cid, source["document_id"], source["version"], source["start"], source["end"])
                if actual["body_hash"] != source["body_hash"]:
                    raise KnowledgeError("引用版本不一致。")
            result = await self.knowledge.save_markdown(self.owner, self.save_space,
                title=payload["title"], body=payload["markdown"], operation_id="save-draft:" + args.draft_id,
                expected_generation=self.generation, provenance={"origin": "ai_synthesis", "sources": payload["sources"]})
            self.saved.append(result)
            return {**result, "saved": True}
        if name == "propose_practice":
            if self.practice is None:
                raise KnowledgeError("当前没有用户授权的合法练习提案。")
            if self.practice_result is None:
                self.practice_result = await self.practice()
            return self.practice_result
        raise KnowledgeError("未授权工具。")

    async def validate_claims(self, claims):
        summaries = []
        for claim in claims:
            for evidence in claim.evidence:
                source = self.reads.get(evidence.source_id)
                if not source or evidence.quote not in source["text"]:
                    raise KnowledgeError("引用未读取、版本不一致或原文摘录不匹配。")
                actual = await self.knowledge.read_source(self.owner, self.cid, source["document_id"], source["version"], source["start"], source["end"])
                if actual["body_hash"] != source["body_hash"]:
                    raise KnowledgeError("引用版本已变化。")
            if claim.kind == "quote":
                if len(claim.evidence) != 1 or claim.text != claim.evidence[0].quote:
                    raise KnowledgeError("原文摘录必须逐字对应实际读取区间。")
            else:
                summaries.append({"claim": claim.text, "evidence": [e.quote for e in claim.evidence]})
        # Lexical similarity is never treated as entailment. A separate bounded
        # model check must explicitly support each synthesis; otherwise abstain.
        if summaries:
            flags = await self._support_flags(summaries)
            if flags is None or not all(flags):
                raise KnowledgeError("总结的证据覆盖不足；请删除推断或改用逐字摘录。")

    async def _citation_state(self, claim) -> SourceState:
        """Local quote/version/verbatim checks; no model call."""
        for evidence in claim.evidence:
            source = self.reads.get(evidence.source_id)
            if not source or evidence.quote not in source["text"]:
                return SourceState.REJECTED
            try:
                actual = await self.knowledge.read_source(self.owner, self.cid, source["document_id"],
                                                          source["version"], source["start"], source["end"])
            except KnowledgeError:
                return SourceState.REJECTED
            if actual["body_hash"] != source["body_hash"]:
                return SourceState.REJECTED
        if claim.kind == "quote":
            ok = len(claim.evidence) == 1 and claim.text == claim.evidence[0].quote
            return SourceState.QUOTE_OK if ok else SourceState.REJECTED
        return SourceState.SUMMARY_OK

    async def _support_flags(self, summaries) -> list[bool] | None:
        """One batch entailment check. None means fail-closed (malformed or missing)."""
        if self.support_checker is None:
            return None
        result = await self.support_checker(summaries)
        if result is True:
            return [True] * len(summaries)
        if result is False:
            return [False] * len(summaries)
        if (
            isinstance(result, list)
            and len(result) == len(summaries)
            and all(value is True or value is False for value in result)
        ):
            return result
        return None

    async def source_state(self, claim) -> SourceState:
        """Source channel for ONE claim, non-raising (same checks as validate_claims)."""
        local = await self._citation_state(claim)
        if local is not SourceState.SUMMARY_OK or claim.kind != "summary":
            return local
        flags = await self._support_flags(
            [{"claim": claim.text, "evidence": [e.quote for e in claim.evidence]}]
        )
        if flags is None or not flags[0]:
            return SourceState.REJECTED
        return SourceState.SUMMARY_OK

    async def math_state(self, expression: str, answer: str) -> MathState:
        """Math channel, non-raising: parser + solver + verifier + attempt verifier.

        Anything the deterministic pipeline cannot establish stays
        UNSUPPORTED / UNDETERMINED — the model is never asked to settle it.
        """
        from uuid import uuid4
        from mathtutor.domain.problem import MathProblem
        from mathtutor.learning.attempt_parser import parse_student_attempt
        from mathtutor.security.scopes import student_uuid
        from mathtutor.solving.parser import parse_problem
        from mathtutor.solving.solver import solve_problem
        try:
            raw = parse_problem(expression).problem
            if raw is None:
                return MathState.UNSUPPORTED
            problem = MathProblem.canonicalize(problem_type=raw.problem_type, normalized_ast=raw.normalized_ast,
                                               display_latex=raw.display_latex)
            candidate = solve_problem(problem, raw).candidate
            verdict = await self.state.verification_backend.verify(problem, candidate)
            if verdict.verdict != "VERIFIED":
                return MathState.UNSUPPORTED
            attempt = parse_student_attempt(attempt_submission_id=uuid4(), student_id=student_uuid(self.owner),
                                            cycle_id=uuid4(), raw_text=answer, attempt_index=1)
            assessed = await self.state.verification_backend.verify_attempt(attempt, problem, candidate)
        except Exception:
            return MathState.UNSUPPORTED
        return math_state_from_correctness(assessed.correctness)

    def render_claims(self, claims, notes=None):
        import re
        from urllib.parse import quote
        def literal(value):
            # Entity escaping preserves literal source characters without
            # creating \\[...\\] delimiters for the existing math renderer.
            return re.sub(r"([\\`*_{}\[\]()<>#+.!|~$&-])", lambda m: f"&#{ord(m.group())};", value)
        pieces = []
        for index, claim in enumerate(claims):
            refs = []
            for e in claim.evidence:
                source = self.reads[e.source_id]
                url = (f"/math-tutor/knowledge?conversation={quote(self.cid, safe='')}&source={source['document_id']}"
                       f"&version={source['version']}&start={source['start']}&end={source['end']}")
                title = literal(source["title"])
                refs.append(f"[{title} · v{source['version']} · L{source['line_start']}–{source['line_end']}]({url})")
            label = "原文摘录" if claim.kind == "quote" else "AI 总结（已做证据覆盖检查，仍需核对）"
            note = (notes or {}).get(index)
            pieces.append(f"**{label}**" + (f" · {note}" if note else "")
                          + f"\n\n{literal(claim.text)}\n\n来源：" + "、".join(refs))
        return "\n\n".join(pieces)

    async def gate_final(self, final):
        """Run both channels over a final answer and apply the merge table.

        Returns (claims to show, per-claim notes, standalone lines, notices).
        Also records every decision in ``self.gate_log`` for audit.
        """
        severity = [MathState.INCORRECT, MathState.UNDETERMINED, MathState.UNSUPPORTED,
                    MathState.PARTIAL, MathState.CORRECT]
        per_claim: dict[int, MathState] = {}
        standalone = []
        for assertion in final.math_assertions:
            state = await self.math_state(assertion.expression, assertion.answer)
            index = assertion.claim_index
            if index is not None and index < len(final.claims):
                previous = per_claim.get(index)
                if previous is None or severity.index(state) < severity.index(previous):
                    per_claim[index] = state
            else:
                standalone.append((assertion, state))
        citation_states = [await self._citation_state(claim) for claim in final.claims]
        pending = [
            (index, {"claim": claim.text, "evidence": [e.quote for e in claim.evidence]})
            for index, claim in enumerate(final.claims)
            if claim.kind == "summary" and citation_states[index] is not SourceState.REJECTED
        ]
        flags_by_index: dict[int, bool] = {}
        if pending:
            flags = await self._support_flags([payload for _, payload in pending])
            if flags is None:
                raise KnowledgeError("总结的证据覆盖不足；请删除推断或改用逐字摘录。")
            flags_by_index = {index: flag for (index, _), flag in zip(pending, flags)}
        shown, notes, notices, lines = [], {}, [], []
        dropped_summaries = 0
        for index, claim in enumerate(final.claims):
            source = citation_states[index]
            if claim.kind == "summary" and source is not SourceState.REJECTED:
                source = SourceState.SUMMARY_OK if flags_by_index.get(index) else SourceState.REJECTED
            math = per_claim.get(index, MathState.NONE)
            decision = decide(source, math)
            self.gate_log.append({"claim_index": index, "source": source.value, "math": math.value,
                                  "treatment": decision.treatment.value})
            if decision.treatment is Treatment.WITHHOLD:
                if claim.kind == "summary" and citation_states[index] is not SourceState.REJECTED:
                    dropped_summaries += 1
                    notices.append("已移除 1 条证据不足的总结。")
                    continue
                raise KnowledgeError("引用未读取、版本不一致、原文摘录不匹配或总结证据覆盖不足。")
            if decision.treatment is Treatment.DROP_MATH:
                notices.append("已移除 1 条未通过数学验证的结论。")
                continue
            note = decision.math_label
            if decision.treatment is Treatment.SHOW_SOURCE_MATH_CONFLICT:
                note = "⚠ 来源支持 ≠ 数学正确：这是资料原文，但其中的数学结论未通过验证，请勿直接采用"
            if note:
                notes[len(shown)] = note
            shown.append(claim)
        for assertion, state in standalone:
            decision = decide(SourceState.NONE, state)
            self.gate_log.append({"claim_index": None, "source": "none", "math": state.value,
                                  "treatment": decision.treatment.value})
            if decision.treatment is Treatment.DROP_MATH:
                notices.append("已移除 1 条未通过数学验证的结论。")
            else:
                lines.append(f"- {assertion.expression}：{assertion.answer}（{decision.math_label}）")
        if pending and dropped_summaries == len(pending) and not shown:
            raise KnowledgeError("总结的证据覆盖不足；请删除推断或改用逐字摘录。")
        return shown, notes, lines, notices

    async def finalize(self, text):
        try:
            final = Final.model_validate_json(text)
        except ValidationError as exc:
            raise KnowledgeError("最终回答须是 claims / uncertainties JSON，不得把工具调用当答案。") from exc
        claims, notes, math_lines, notices = await self.gate_final(final)
        rendered = self.render_claims(claims, notes)
        if math_lines:
            rendered += "\n\n数学结论核验：\n" + "\n".join(math_lines)
        if notices:
            rendered += "\n\n" + " ".join(notices)
        if final.uncertainties:
            rendered += "\n\n未确定事项：\n" + "\n".join("- " + x for x in final.uncertainties)
        if not claims and not self.practice_result:
            rendered = "所选资料未提供足够可引用证据，未扩大范围或联网。" + rendered
        if self.practice_result:
            rendered += "\n\n练习提案结果已由现有数学验证与发布流程处理，请查看会话中的练习邀请；未自动开始作答。"
        if self.saved:
            rendered += "\n\n已保存新笔记到指定知识库；新会话显式挂载后可检索。"
        elif self.draft_results:
            rendered += "\n\n笔记草稿已生成，尚未保存到知识库。"
        return rendered.strip()

    def partial_text(self):
        if self.saved:
            return "笔记已保存，但回答未完成。请在知识库查看；重试不会重复保存同一草稿。"
        if self.draft_results:
            return "笔记草稿已保留，尚未保存。可在知识库页面预览后保存。"
        return ""
