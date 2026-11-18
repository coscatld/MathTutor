"""Nonblocking discovery of public resources, scoped to one learner."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from contextlib import nullcontext
from datetime import UTC, datetime

from mathtutor.application.exploration_evidence import build_source_snapshots
from mathtutor.application.learning_actions import (
    POLICY, goal_label, goal_options, load_catalog, plan_learning_actions, validate_goal,
)
from mathtutor.infrastructure.zhihu import ZhihuError
from mathtutor.learning.skill_graph import SKILLS
from mathtutor.repositories.recommendation_repository import RecommendationRepository, budget_exhausted

_TOPIC_TERMS = {
    "probability": ("概率", "统计", "贝叶斯"),
    "algorithms": ("算法", "数据结构"),
    "research_methods": ("论文阅读", "论文", "科研方法"),
}


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp, UTC).isoformat() if timestamp else None


def _source_time(value):
    if type(value) is not int or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


class RecommendationsService:
    def __init__(self, engine, student_state, client, *, catalog=None, clock=time.time, timeout=32):
        self.repository = RecommendationRepository(engine)
        self.student_state = student_state
        self.client = client
        self.catalog = catalog if catalog is not None else load_catalog()
        self.catalog_hash = hashlib.sha256(json.dumps(self.catalog, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        self.clock, self.timeout = clock, timeout
        self.tasks = {}
        self.running = set()
        self.closed = False

    def _cache_key(self, owner, row, plan):
        return hashlib.sha256(json.dumps([str(owner), row["generation"], row["goal"],
            plan["profile_revision"], self.catalog_hash, POLICY], ensure_ascii=False).encode()).hexdigest()

    async def plan_for(self, owner, goal, language="zh"):
        history = await self.student_state.events(str(owner))
        return plan_learning_actions(history, validate_goal(goal), self.catalog, language=language)

    async def _snapshot(self, owner, language):
        async with self.repository.engine.connect() as conn:
            row = await self.repository.get(owner, conn=conn)
            history = await self.student_state.events(str(owner), conn=conn)
        plan = plan_learning_actions(history, row["goal"], self.catalog, language=language)
        stamp = (len(history), max((event.event_seq for event in history), default=0))
        return row, plan, stamp

    def _view(self, owner, row, plan, *, language="zh", status=None):
        matching = row["cache_key"] == self._cache_key(owner, row, plan)
        cached = row["payload"] if matching and row["payload"] else None
        now = self.clock()
        current_status = status or row["status"]
        if not row["enabled"]:
            current_status = "disabled"
        elif row["lease_until"] > now and row["lease_key"] == self._cache_key(owner, row, plan):
            current_status = "running"
        elif current_status in {"running", "cached"} and (not cached or row["expires_at"] <= now):
            current_status = "idle"
        return {"enabled": bool(row["enabled"]), "goal": row["goal"], "goals": goal_options(language),
                "status": current_status, "updated_at": _iso(row["updated_at"]) if cached else None,
                "expires_at": _iso(row["expires_at"]) if cached else None, "plan": plan, "discovery": cached}

    async def get(self, owner, language="zh"):
        row, plan, _ = await self._snapshot(owner, language)
        return self._view(owner, row, plan, language=language)

    async def configure(self, owner, *, enabled, goal, language="zh"):
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        row = await self.repository.configure(owner, enabled=enabled, goal=validate_goal(goal))
        task = self.tasks.get(str(owner))
        if task and task[0] != row["lease_token"]:
            task[1].cancel()
        return await self.get(owner, language)

    async def _local_start(self, owner, row, plan, language):
        if self.closed or not row["enabled"]:
            return self._view(owner, row, plan, language=language)
        key = self._cache_key(owner, row, plan)
        now = self.clock()
        if ((row["cache_key"] == key and row["expires_at"] > now)
                or (row["lease_key"] == key and row["lease_until"] > now)):
            return self._view(owner, row, plan, language=language)
        if budget_exhausted(row, now):
            await self.repository.mark_limited(owner, generation=row["generation"], cache_key=key, now=now)
            return await self.get(owner, language)
        return None

    async def start(self, owner, language="zh", *, owner_guard=None):
        guard = owner_guard or nullcontext
        async with guard():
            row, plan, _ = await self._snapshot(owner, language)
            local = await self._local_start(owner, row, plan, language)
            if local is not None:
                return local
        configuration_status = None
        try:
            async with asyncio.timeout(min(self.timeout, 2)):
                configuration = await self.client.configuration(str(owner))
            if not isinstance(configuration, dict) or type(configuration.get("configured")) is not bool:
                raise ValueError("Invalid discovery configuration")
            if not configuration["configured"]:
                configuration_status = "not_configured"
        except Exception:
            configuration_status = "failed"
        async with guard():
            row, plan, stamp = await self._snapshot(owner, language)
            local = await self._local_start(owner, row, plan, language)
            if local is not None:
                return local
            if configuration_status:
                return self._view(owner, row, plan, language=language, status=configuration_status)
            key = self._cache_key(owner, row, plan)
            token = await self.repository.reserve(owner, generation=row["generation"], cache_key=key, now=self.clock())
            if token:
                if self.closed:
                    await self.repository.fail(owner, token, "idle")
                    return await self.get(owner, language)
                previous = self.tasks.get(str(owner))
                if previous:
                    previous[1].cancel()
                task = asyncio.create_task(self._discover(str(owner), token, row["generation"], key, plan, stamp))
                self.tasks[str(owner)] = (token, task)
                self.running.add(task)
                task.add_done_callback(self.running.discard)
            return await self.get(owner, language)

    async def _discover(self, owner, token, generation, key, plan, stamp):
        try:
            async with asyncio.timeout(self.timeout):
                response = await self.client.search(owner, plan["query"], count=6)
            retrieved_at = _iso(self.clock())
            batch = build_source_snapshots(response["Items"], request_id=response.get("SearchHashId", ""),
                                           retrieved_at=retrieved_at, max_sources=6)
            target = plan["target"]
            terms = [goal_label(target)]
            if target in SKILLS:
                terms.extend(SKILLS[target].aliases)
            terms.extend(_TOPIC_TERMS.get(target, ()))
            resources = []
            reviewed_urls = {item["url"].split("?")[0] for item in self.catalog["resources"]}
            for source in batch.sources:
                if (source.duplicate_of or source.truncated or len(source.text.strip()) < 80
                        or source.original_url.split("?")[0] in reviewed_urls
                        or not any(term.casefold() in (source.title + source.text).casefold() for term in terms)):
                    continue
                raw = next((item for item in response["Items"] if str(item.get("ContentID")) == source.content_id), {})
                source_time = _source_time(raw.get("EditTime"))
                resources.append({"resource_id": source.source_id, "title": source.title, "author": source.author,
                    "url": source.original_url, "summary": source.text, "review_status": "automatically_screened",
                    "source_time": source_time,
                    "source_time_kind": "published_or_updated" if source_time is not None else "unknown",
                    "provenance": {"retrieved_at": retrieved_at, "request_id": source.request_id,
                                   "excerpt_sha256": source.raw_excerpt_sha256, "excerpt": source.raw_excerpt}})
                if len(resources) == 3:
                    break
            await self.repository.finish(owner, token=token, generation=generation, cache_key=key,
                payload={"query": plan["query"], "retrieved_at": retrieved_at, "resources": resources,
                         "status": "ready" if resources else "empty"}, expected_stamp=stamp, now=self.clock())
        except asyncio.CancelledError:
            await self.repository.fail(owner, token, "idle")
            raise
        except ZhihuError as error:
            status = {"rate_limited": "rate_limited", "credential_invalid": "not_configured",
                      "not_configured": "not_configured"}.get(error.kind, "failed")
            await self.repository.fail(owner, token, status)
        except Exception:
            await self.repository.fail(owner, token)
        finally:
            if self.tasks.get(owner, (None,))[0] == token:
                self.tasks.pop(owner, None)

    async def delete(self, owner):
        await self.repository.delete(owner)
        current = self.tasks.get(str(owner))
        if current:
            current[1].cancel()

    async def close(self):
        self.closed = True
        tasks = list(self.running)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
