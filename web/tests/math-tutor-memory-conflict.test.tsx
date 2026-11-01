import assert from "node:assert/strict";
import test from "node:test";
import {confirmMemory, DesktopApiError, MemoryConflictError, projectMemoryConflict, toggleMemoryRetrieval, updateMemory} from "../features/math-tutor/desktop/lib/desktop-api";
import type {DesktopMemory} from "../features/math-tutor/desktop/types";
import {mergeMemoryUpdate} from "../features/math-tutor/desktop/lib/memory-state";

const memory: DesktopMemory={memory_id:"fixture-memory",memory_type:"user_note",subject:"用户",predicate:"内容",object_json:{value:"原文保留"},source_type:"USER_EXPLICIT",confidence:.9,retrieval_enabled:false,created_at:"2026-10-30T00:00:00+00:00",updated_at:"2026-10-30T00:00:00.000002+00:00"};

test("memory conflicts project only the same record's public fields and retain original content",()=>{
  assert.deepEqual(projectMemoryConflict({...memory,student_id:"private-owner",mastery:.99,internal_path:"private"},memory.memory_id),memory);
  for(const candidate of [{...memory,memory_id:"another-memory"},{...memory,updated_at:"invalid"},{...memory,retrieval_enabled:"true"},{...memory,confidence:NaN},{...memory,object_json:[]},{...memory,source_type:"untrusted"}]) {
    assert.equal(projectMemoryConflict(candidate,memory.memory_id),null);
  }
});

test("an edit sends the exact microsecond version and exposes the confirmed disabled state on 409",async t=>{
  const inputs: Array<Record<string,unknown>>=[];
  t.mock.method(globalThis,"fetch",async (_url:unknown,init?:RequestInit)=>{
    inputs.push(JSON.parse(String(init?.body)));
    return Response.json({code:"memory_conflict",latest:{...memory,student_id:"hidden"}},{status:409});
  });
  await assert.rejects(updateMemory(memory.memory_id,{object_json:{value:"draft"},expected_updated_at:"2026-10-30T00:00:00.000001+00:00"}),error=>{
    assert.ok(error instanceof MemoryConflictError);assert.deepEqual(error.latest,memory);assert.equal(error.status,409);return true;
  });
  assert.equal(inputs[0].expected_updated_at,"2026-10-30T00:00:00.000001+00:00");
});

test("confirmation and retrieval changes bind the caller's version without adding edit fields",async t=>{
  const requests:Array<{url:string;body:Record<string,unknown>}>=[];
  t.mock.method(globalThis,"fetch",async(url:unknown,init?:RequestInit)=>{
    requests.push({url:String(url),body:JSON.parse(String(init?.body))});return Response.json(memory);
  });
  await confirmMemory(memory.memory_id,memory.updated_at);
  await toggleMemoryRetrieval(memory.memory_id,false,memory.updated_at);
  assert.deepEqual(requests.map(row=>row.body),[{expected_updated_at:memory.updated_at},{enabled:false,expected_updated_at:memory.updated_at}]);
  assert.ok(requests[0].url.endsWith("/confirm"));assert.ok(requests[1].url.endsWith("/retrieval"));
});

test("a malformed or different-record conflict cannot replace a displayed memory",async t=>{
  t.mock.method(globalThis,"fetch",async()=>Response.json({code:"memory_conflict",latest:{...memory,memory_id:"foreign"},detail:"conflict"},{status:409}));
  await assert.rejects(updateMemory(memory.memory_id,{object_json:{value:"draft"},expected_updated_at:memory.updated_at}),error=>{
    assert.ok(error instanceof DesktopApiError);assert.ok(!(error instanceof MemoryConflictError));assert.equal(error.status,409);return true;
  });
});

test("a late older edit receipt cannot reenable a newer disabled view within the same millisecond",()=>{
  const latest={...memory,updated_at:"2026-10-30T00:00:00.000003+00:00",retrieval_enabled:false};
  const stale={...memory,updated_at:"2026-10-30T00:00:00.000002+00:00",retrieval_enabled:true};
  assert.equal(Date.parse(latest.updated_at),Date.parse(stale.updated_at));
  assert.equal(mergeMemoryUpdate([latest],stale)[0],latest);
  assert.equal(mergeMemoryUpdate([latest],{...latest,retrieval_enabled:true})[0],latest);
  const explicitToggle={...latest,retrieval_enabled:true,updated_at:"2026-10-30T00:00:00.000004+00:00"};
  assert.equal(mergeMemoryUpdate([latest],explicitToggle)[0],explicitToggle);
});

test("version merges compare timezone-equivalent timestamps and cannot resurrect deleted rows",()=>{
  const latest={...memory,updated_at:"2026-10-30T08:00:00.000003+08:00"};
  assert.equal(mergeMemoryUpdate([latest],{...memory,updated_at:"2026-10-30T00:00:00.000002Z",retrieval_enabled:true})[0],latest);
  assert.deepEqual(mergeMemoryUpdate([],memory),[]);
  assert.equal(mergeMemoryUpdate([memory],{...memory,updated_at:"invalid"})[0],memory);
});
