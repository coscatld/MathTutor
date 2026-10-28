import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {projectProblemContext} from "../features/math-tutor/lib/teaching-contract";
import {allowedInputsToButtons, buildEnvelope} from "../features/math-tutor/lib/protocol";
import PracticeOfferCard from "../features/math-tutor/desktop/components/PracticeOfferCard";

test("only public response-mode and exposure facts survive hydration", () => {
  const context = projectProblemContext({problem_id:"p",response_mode:"free_response",observation_kind:"independent_transfer",options_exposed:false,answer_key:"private"});
  assert.equal(context?.response_mode,"free_response");
  assert.equal(context?.options_exposed,false);
  assert.ok(!JSON.stringify(context).includes("private"));
  assert.equal(projectProblemContext({problem_id:"p",response_mode:"invented"})?.response_mode,undefined);
});

test("option exposure is an explicit capability with no answer payload", () => {
  assert.deepEqual(allowedInputsToButtons(["request_options"]).map(x=>x.command),["request_options"]);
  assert.equal(JSON.parse(buildEnvelope("request_options",{},"session")).command,"request_options");
  assert.equal(allowedInputsToButtons([]).some(x=>x.command==="request_options"),false);
});

test("one diagnostic choice success is visible when independent and assisted counts are zero", () => {
  const html=renderToStaticMarkup(<PracticeOfferCard offer={{offer_id:"o",parent_cycle_id:"p",status:"ACCEPTED",skill_labels:[],concept_labels:[],difficulty:"2",offered_at:"",expires_at:"",display_status:"completed",response_mode:"single_choice",observation_kind:"diagnostic",result_summary:{independent_correct:0,first_free_response:0,diagnostic_correct:1,helped:0,observations:1}}} accepting={false} onStart={()=>{}} />);
  assert.match(html,/1 次诊断选择答对/);
  assert.match(html,/0 次首次独立自由作答/);
  assert.match(html,/再尝试一道未见新题/);
});
