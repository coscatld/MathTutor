"""Compare full materialization and bounded memory selection on synthetic data.

Uses an isolated SQLite file; reports only counts, timing and Python allocation
peaks. No model, credentials, user memory text or production database is read.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import statistics
import tempfile
import time
import tracemalloc
from uuid import UUID

from mathtutor.application.context_assembler import PersonalMemorySourceProvider
from mathtutor.application.memory_context import TRUSTED_MEMORY_SOURCES, select_memory_context
from mathtutor.infrastructure import create_db_engine
from mathtutor.infrastructure.schema import metadata, personal_memory_nodes
from mathtutor.repositories.sqlite_knowledge import SQLiteMemoryRepository
from mathtutor.repositories.sqlite_runtime import ensure_student

OWNER = "synthetic-memory-benchmark"


async def seed(engine, count, scenario):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows=[]
    for index in range(count):
        stamp=(base+timedelta(seconds=index)).isoformat()
        oversized=(scenario=="oversized_latest" and index>=count-40) or (scenario=="scan_limit" and index>=count-300)
        rows.append(dict(memory_id=str(UUID(int=index+1)),student_id=OWNER,memory_type="user_note",subject="synthetic",predicate="note",
            object_json={"value":"x"*1800 if oversized else "synthetic preference"},source_type="MODEL_INFERRED" if scenario=="unconfirmed" else "USER_EXPLICIT",
            confidence=.9,retrieval_enabled=0 if scenario=="disabled" else 1,created_at=stamp,
            updated_at=(base+timedelta(seconds=count+1)).isoformat() if scenario=="recent_edit" and index==0 else stamp,deleted_at=None))
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        await ensure_student(conn,student_id=OWNER)
        for offset in range(0,len(rows),500):
            await conn.execute(personal_memory_nodes.insert(),rows[offset:offset+500])


async def full_selection(repo):
    nodes=await repo.list_retrievable(OWNER,source_types=TRUSTED_MEMORY_SOURCES)
    rows_read=len(nodes)
    if not nodes:
        live=await repo.list_nodes(OWNER)
        rows_read+=len(live)
        return (),rows_read,not any(node.retrieval_enabled for node in live) and bool(live)
    selected=select_memory_context(nodes)
    return tuple(entry.memory_id for entry in selected.entries),rows_read,False


async def bounded_selection(provider):
    outcome=await provider.load_for_tutor(student_id=OWNER)
    selected=tuple(entry.memory_id for entry in outcome.payload.entries) if outcome.payload else ()
    return selected,outcome.selection_stats.rows_read,outcome.disabled_by_user,asdict(outcome.selection_stats)


def percentile95(values):
    ordered=sorted(values)
    return ordered[max(0,math.ceil(len(ordered)*.95)-1)]


async def measure(function,samples):
    await function()  # warm connections/imports before recording allocation
    timings=[];peaks=[];result=None
    for _ in range(samples):
        tracemalloc.start()
        start=time.perf_counter()
        try:
            result=await function()
            timings.append((time.perf_counter()-start)*1000)
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
    return result,{"samples":samples,"selection_p95_ms":round(percentile95(timings),3),"selection_median_ms":round(statistics.median(timings),3),"peak_python_bytes":max(peaks),"rows_materialized":result[1],"selected_count":len(result[0])}


async def main(args):
    results=[]
    with tempfile.TemporaryDirectory(prefix="mathtutor-memory-benchmark-") as directory:
        for scenario,count in [("small",40),("recent_edit",args.rows),("oversized_latest",args.rows),("disabled",args.rows),("unconfirmed",args.rows),("scan_limit",args.rows)]:
            engine=create_db_engine(Path(directory)/f"{scenario}.db")
            try:
                await seed(engine,count,scenario)
                repo=SQLiteMemoryRepository(engine)
                provider=PersonalMemorySourceProvider(repo,page_size=32,max_candidates=256)
                baseline,before=await measure(lambda:full_selection(repo),args.samples)
                bounded,after=await measure(lambda:bounded_selection(provider),args.samples)
                assert bounded[1]<=256
                if scenario!="scan_limit":
                    assert baseline[:1]==bounded[:1] and baseline[2]==bounded[2],scenario
                else:
                    assert bounded[3]["selection_scan_limited"] and not bounded[0]
                results.append({"scenario":scenario,"live_rows":count,"same_selected_records":baseline[0]==bounded[0],"before":before,"after":after,"selection_stats":bounded[3]})
            finally:
                await engine.dispose()
    payload={"schema_version":1,"status":"PASS","scope":"Synthetic, isolated local SQLite. No model calls or user data. Timing includes Python allocation tracing; no production speedup claim.",
        "page_size":32,"max_candidates":256,"matching_index_added":False,"results":results}
    text=json.dumps(payload,ensure_ascii=False,indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text)
    print(text,end="")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows",type=int,default=10000)
    parser.add_argument("--samples",type=int,default=15)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    if args.rows<1000 or args.samples<2:
        parser.error("use at least 1000 rows and 2 samples")
    asyncio.run(main(args))
