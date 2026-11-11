"""Bounded learning episodes: response patterns, independent recall and transfer.

Only the server chooses the current item, clock and evidence grade.  These
records never update mastery/DKT.  A finite item catalog also bounds saved
history; read/resume cannot reset exposure or the first opportunity.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from mathtutor.learning import diagnostic_probes as probes
from mathtutor.learning.knowledge_tracing.schema import learning_loop_episodes as episodes
from mathtutor.repositories.sqlite_runtime import ensure_student

POLICY = "learning_loop_v1"
MAX_RECEIPTS = 64


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Learning clock must include a timezone")
    return value.astimezone(timezone.utc).isoformat()


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


class LearningLoopService:
    def __init__(self, engine, *, clock=None):
        self.engine = engine
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self):
        return _date(_iso(self.clock()))

    @staticmethod
    def _domain(domain):
        if domain not in probes.DOMAINS:
            raise ValueError("Unsupported learning-loop domain")

    async def _load(self, conn, sid, domain):
        return (await conn.execute(select(episodes.c.payload).where(
            episodes.c.student_id == str(sid), episodes.c.domain == domain))).scalar_one_or_none()

    async def read(self, sid, *, conn=None):
        if conn is None:
            async with self.engine.connect() as db:
                return await self.read(sid, conn=db)
        now = self._now()
        rows = []
        for domain in probes.DOMAINS:
            labels = probes.DOMAIN_LABELS[domain]
            payload = await self._load(conn, sid, domain)
            rows.append({"domain": domain, "label_zh": labels["zh"], "label_en": labels["en"],
                         "episode": self._public(payload, now) if payload else None})
        return {"schema_version": POLICY, "server_time": _iso(now), "domains": rows}

    def _public(self, payload, now):
        compatible = payload.get("policy") == POLICY and payload.get("probe_policy") == probes.POLICY_VERSION
        # A different catalog cannot interpret old probe IDs. Preserve those
        # records, but never run them through today's rule engine on reads.
        diagnostic = probes.diagnostic_state(payload["domain"], payload["diagnosis"]) if compatible else {
            "status": "uncertain", "supported_rule": None, "answered": len(payload.get("diagnosis", []))}
        supported = diagnostic["supported_rule"]
        if payload.get("diagnostic_interrupted") or payload.get("pattern_retracted"):
            diagnostic = {**diagnostic, "status": "uncertain"}
            supported = None
        labels = probes.RULE_LABELS.get(supported) or {
            "zh": "当前证据还不能区分错因，可以继续用新题检查。",
            "en": "The evidence does not yet distinguish a cause; continue with a fresh problem.",
        }
        if not compatible:
            labels = {"zh": "题库已更新，已有记录保留，暂不能继续本轮检查。",
                      "en": "The catalog changed. Your saved records are preserved, but this episode cannot continue."}
        question = probes.public_probe(probes.get_probe(payload["current_probe"])) if compatible and payload["current_probe"] else None
        due = payload["due_at"]
        return {"episode_id": payload["episode_id"], "domain": payload["domain"],
                "phase": payload["phase"] if compatible else "exhausted", "question": question,
                "due_at": due, "can_start": bool(compatible and payload["phase"] == "waiting" and due and now >= _date(due)),
                "diagnostic": {"status": diagnostic["status"], "answered": diagnostic["answered"],
                               "label_zh": labels["zh"], "label_en": labels["en"]},
                "evidence": dict(payload["evidence"]), "review_round": payload["review_round"],
                "feedback": deepcopy(payload.get("feedback"))}

    @staticmethod
    def _issue(payload, phase, probe):
        if probe is None:
            payload.update(phase="exhausted", current_probe=None, due_at=None)
            return
        if probe.probe_id in payload["served_ids"] or len(payload["served_ids"]) >= probes.MAX_CATALOG_SIZE:
            raise ValueError("Repeated or over-budget learning item")
        payload["served_ids"].append(probe.probe_id)
        payload.update(phase=phase, current_probe=probe.probe_id, current_helped=False, due_at=None)

    @classmethod
    def _followup(cls, payload, phase):
        purpose = "transfer" if phase == "transfer" else "review"
        cls._issue(payload, phase, probes.choose_followup(payload["domain"], purpose, payload["served_ids"]))

    async def _save(self, conn, sid, domain, original, updated):
        # Cancellation delivered before the durable mutation aborts the transaction.
        await asyncio.sleep(0)
        changed = await conn.execute(episodes.update().where(
            episodes.c.student_id == str(sid), episodes.c.domain == domain,
            episodes.c.payload == original).values(payload=updated))
        if changed.rowcount != 1:
            raise ValueError("Learning progress changed; reload before continuing")
        await asyncio.sleep(0)

    async def start(self, sid, domain):
        self._domain(domain)
        now = self._now()
        async with self.engine.begin() as conn:
            original = await self._load(conn, sid, domain)
            if original is None:
                await ensure_student(conn, student_id=str(sid))
                payload = {"policy": POLICY, "probe_policy": probes.POLICY_VERSION, "episode_id": str(uuid4()),
                    "domain": domain, "phase": "diagnose", "current_probe": None, "current_helped": False,
                    "due_at": None, "updated_at": _iso(now), "diagnosis": [], "served_ids": [],
                    "exposed_ids": [], "attempts": [], "receipts": [], "feedback": None,
                    "review_round": 0, "evidence": {"independent_practice": 0, "delayed_review": 0, "structural_transfer": 0}}
                self._issue(payload, "diagnose", probes.choose_probe(domain, ()))
                await asyncio.sleep(0)
                await conn.execute(insert(episodes).values(student_id=str(sid), domain=domain, payload=payload)
                    .on_conflict_do_nothing())
            else:
                self._compatible(original)
                if original["phase"] == "waiting" and original["due_at"] and now >= _date(original["due_at"]):
                    updated = deepcopy(original)
                    updated["review_due_at"] = original["due_at"]
                    self._followup(updated, "review")
                    updated.update(updated_at=_iso(now), feedback=None)
                    await self._save(conn, sid, domain, original, updated)
            return await self.read(sid, conn=conn)

    @staticmethod
    def _compatible(payload):
        if payload.get("policy") != POLICY or payload.get("probe_policy") != probes.POLICY_VERSION:
            raise ValueError("Saved learning episode uses an incompatible policy")

    async def submit(self, sid, *, domain, episode_id, probe_id, request_id, answer=None, help_requested=False):
        self._domain(domain)
        now = self._now()
        kind = "help" if help_requested else "answer"
        fingerprint = hashlib.sha256(json.dumps([kind, episode_id, probe_id, answer], ensure_ascii=False).encode()).hexdigest()
        async with self.engine.begin() as conn:
            original = await self._load(conn, sid, domain)
            if not original or original["episode_id"] != episode_id:
                raise ValueError("This learning episode is unavailable or belongs to another learner")
            self._compatible(original)
            receipt = next((r for r in original["receipts"] if r["request_id"] == request_id), None)
            if receipt:
                if receipt["fingerprint"] != fingerprint:
                    raise ValueError("A submitted request cannot be changed")
                return await self.read(sid, conn=conn)
            if original["current_probe"] != probe_id or original["phase"] not in {"diagnose", "practice", "review", "transfer"}:
                raise ValueError("This question has already changed; reload before continuing")
            if now < _date(original["updated_at"]):
                raise ValueError("The system clock moved backwards; try again after it catches up")
            probe = probes.get_probe(probe_id)
            if probe.domain != domain:
                raise ValueError("Question belongs to a different learning domain")
            updated = deepcopy(original)
            phase = original["phase"]
            if help_requested:
                if probe_id not in updated["exposed_ids"]:
                    updated["exposed_ids"].append(probe_id)
                updated["current_helped"] = True
                updated["feedback"] = {"kind": "help", "probe_id": probe_id, "statement": probe.statement, "independent": False, **probes.feedback_for(probe)}
                if phase == "diagnose":
                    # Teaching invalidates the fixed-rule assumption across diagnostic probes.
                    updated["diagnostic_interrupted"] = True
                    self._followup(updated, "practice")
            else:
                assessed = probes.assess_response(probe_id, answer)
                independent = not original["current_helped"] and probe_id not in original["exposed_ids"]
                result = assessed["correctness"]
                if result == "unknown":
                    updated["feedback"] = {"kind": "unknown", "probe_id": probe_id, "statement": probe.statement}
                else:
                    event = {"probe_id": probe_id, "phase": phase, "answer": assessed["normalized_answer"],
                        "correctness": result, "independent": independent, "occurred_at": _iso(now),
                        "relation": probe.relation}
                    updated["attempts"].append(event)
                    if len(updated["attempts"]) > probes.MAX_CATALOG_SIZE:
                        raise ValueError("Learning history budget exceeded")
                    updated["feedback"] = {"kind": result, "probe_id": probe_id, "statement": probe.statement,
                        "independent": independent, **probes.feedback_for(probe)}
                    if phase == "diagnose":
                        updated["diagnosis"].append({"probe_id": probe_id, "answer": assessed["normalized_answer"], "independent": independent})
                        next_probe = probes.choose_probe(domain, updated["diagnosis"], updated["served_ids"])
                        if next_probe is not None:
                            self._issue(updated, "diagnose", next_probe)
                            updated["feedback"] = {"kind": "recorded", "probe_id": probe_id, "statement": probe.statement}
                        else:
                            self._followup(updated, "practice")
                    else:
                        pattern = probes.diagnostic_state(domain, original["diagnosis"])["supported_rule"]
                        if phase != "transfer" and independent and pattern and pattern not in assessed["matching_rules"]:
                            updated["pattern_retracted"] = True
                        self._advance(updated, phase, independent and result == "correct", now)
                    if updated["feedback"]["kind"] != "recorded" and probe_id not in updated["exposed_ids"]:
                        updated["exposed_ids"].append(probe_id)
            updated["receipts"] = [*updated["receipts"], {"request_id": request_id, "fingerprint": fingerprint}][-MAX_RECEIPTS:]
            updated["updated_at"] = _iso(now)
            await self._save(conn, sid, domain, original, updated)
            return await self.read(sid, conn=conn)

    @classmethod
    def _advance(cls, payload, phase, independent_success, now):
        if not independent_success:
            # A fresh problem and a new independent attempt are needed. Old
            # success timestamps remain historical evidence, not current mastery.
            cls._followup(payload, "practice")
            return
        if phase == "practice":
            payload["evidence"]["independent_practice"] += 1
            payload.update(phase="waiting", current_probe=None, due_at=_iso(now + timedelta(days=1)))
        elif phase == "review":
            if not payload.get("review_due_at") or now < _date(payload["review_due_at"]):
                raise ValueError("A delayed review cannot be certified before its due time")
            payload["evidence"]["delayed_review"] += 1
            cls._followup(payload, "transfer")
        elif phase == "transfer":
            payload["evidence"]["structural_transfer"] += 1
            payload["review_round"] += 1
            if payload["review_round"] >= 2:
                payload.update(phase="complete", current_probe=None, due_at=None)
            else:
                payload.update(phase="waiting", current_probe=None, due_at=_iso(now + timedelta(days=3)))

    async def export_summary(self, sid):
        public = await self.read(sid)
        return [{"domain": row["domain"], "phase": row["episode"]["phase"],
                 "due_at": row["episode"]["due_at"], "review_round": row["episode"]["review_round"],
                 "diagnostic_status": row["episode"]["diagnostic"]["status"],
                 "evidence": row["episode"]["evidence"]}
                for row in public["domains"] if row["episode"]]
