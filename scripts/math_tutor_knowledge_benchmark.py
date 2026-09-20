"""Same-fixture engineering comparison. Scripted provider is NOT a quality eval."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from test_knowledge_workbench import ScriptedProvider
from mathtutor.api.product_state import ProductState
from mathtutor.application.verification_backend import InProcessVerificationBackend
from mathtutor.application.knowledge_tools import KnowledgeTools
from mathtutor.application.tutor_runtime import complete_tools
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.schema import metadata


async def measure(baseline):
    variants = []
    for native in (True, False):
        with tempfile.TemporaryDirectory(prefix="mathtutor-kb-benchmark-") as temporary:
            root = Path(temporary)
            engine = create_db_engine(root / "benchmark.db")
            async with engine.begin() as db:
                await db.run_sync(metadata.create_all)
            state = ProductState(engine=engine, data_dir=root, verification_backend=InProcessVerificationBackend())
            try:
                owner = "benchmark-owner"
                for cid in ("A", "B", "C"):
                    await state.conversations.ensure(owner, cid)
                lib = await state.knowledge.create_space(owner, "same-fixture")
                for n, fixture in enumerate(baseline["fixtures"]):
                    await state.knowledge.save_markdown(owner, lib["space_id"], title=fixture["filename"],
                        body=fixture["text"], operation_id=str(n))
                await state.knowledge.configure(owner, "A", space_ids=[lib["space_id"]])
                results = []
                for query in baseline["queries"]:
                    started = time.perf_counter()
                    hits = await state.knowledge.search(owner, "A", query)
                    results.append({"query":query,"hit_count":len(hits["hits"]),"retrieval":hits["retrieval"],
                                    "latency_ms":round((time.perf_counter()-started)*1000,2)})
                provider = ScriptedProvider(native=native,save=True)
                executor = KnowledgeTools(state,owner,"A",generation=await state.knowledge.generation(owner),
                    save_space=lib["space_id"],allow_save=True,synthesize=True)
                response = await complete_tools(provider,[{"role":"user","content":"整理并保存两份笔记"}],
                    executor=executor,structured=not native)
                await state.knowledge.configure(owner,"C",space_ids=[lib["space_id"]])
                found = await state.knowledge.search(owner,"C","检验方法整理")
                saved_id = executor.saved[0]["document_id"] if executor.saved else None
                variants.append({"protocol":"native" if native else "structured", "queries":results,
                    "retrieved_query_count":sum(bool(x["hit_count"]) for x in results),
                    "scripted_task_completed":response.turn_result["finish_reason"]=="FINAL_ANSWER" and any(x["document_id"]==saved_id for x in found["hits"]),
                    "provider_calls":len(provider.calls), "executed_tool_receipts":len(executor.receipts),
                    "new_notes":len(await state.knowledge.list_notes(owner,lib["space_id"]))-2,
                    "citations_from_actual_reads":len(executor.reads),
                    "scripted_usage_only":response.turn_result,
                    "answer_quality":"NOT_RUN", "real_provider_quality":"NOT_RUN",
                    "real_cost":{"calls":0,"tokens":0,"currency_cost":None}})
            finally:
                await state.shutdown_runtime()
                await engine.dispose()
    return {"baseline_commit":baseline["head_sha"],"fixture_sha256":hashlib.sha256(json.dumps(baseline["fixtures"],ensure_ascii=False).encode()).hexdigest(),
        "baseline_retrieved_query_count":baseline["retrieved_query_count"],"baseline_tool_probe":baseline["tool_probe"],
        "variants":variants,"real_provider_quality":"NOT_RUN",
        "limitations":["Hit count is not semantic retrieval accuracy.","Scripted calls establish execution only, not model planning or answer quality.",
                       "No configured project provider was found; no external calls or monetary estimate.",
                       "Legacy probe rejects tools after one call; five new calls perform a different, completed workload. Not a cost-efficiency claim."]}


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--baseline",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    report=asyncio.run(measure(json.loads(args.baseline.read_text(encoding="utf-8"))))
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
