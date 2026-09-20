"""Offline saved-response regressions: no live model quality claim."""
import json
from pathlib import Path
import pytest
from mathtutor.application.tutor_runtime import complete_tutor, current_turn
from mathtutor.domain.turn_result import TutorTurnResult
from mathtutor.infrastructure.generative_gateway import CompletionResult

ROOT = Path(__file__).resolve().parents[1]
SAVED = ROOT / "tests/fixtures/sanitized_rag_release/degenerate"


@pytest.mark.asyncio
@pytest.mark.parametrize("numbers", [(72,73),(74,75)])
async def test_saved_restart_does_not_fuse_or_hide_generated_error(numbers):
    rows = [json.loads((SAVED / f"request-{n:03}.json").read_text(encoding="utf-8")) for n in numbers]
    class Replay:
        calls = 0
        async def complete(self, *args, **kwargs):
            row = rows[self.calls]
            self.calls += 1
            return CompletionResult(**row["response"])
    turn = TutorTurnResult()
    token = current_turn.set(turn)
    try:
        result = await complete_tutor(Replay(), rows[0]["messages"], **rows[0]["parameters"])
    finally:
        current_turn.reset(token)
    first, second = [r["response"]["text"] for r in rows]
    assert first in result.text and second in result.text
    assert first + second not in result.text
    assert "续写接缝待核对" in result.text
    assert turn.status == "PARTIAL"
    assert turn.error_code == "CONTINUATION_BOUNDARY_UNVERIFIED"
    if numbers[0] == 74:
        assert "一正一负" in second and "一正一负" in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize("first,second,expected,partial", [
    ("完整的一段。", "另一段。", "完整的一段。\n\n另一段。", False),
    ("这是用于测试去重的完整第一段文字。", "这是用于测试去重的完整第一段文字。接下来。", "这是用于测试去重的完整第一段文字。接下来。", False),
    (r"\(x=", r"2\)", None, True),
    (r"\(1.", r"5\)", r"\(1.5\)", False),
    ("(1.", "5)", "(1.5)", False),
    ("方程的根为", "0和-1。", "方程的根为0和-1。", False),
    ("方程的根为", "0和-1。一正一负。", None, True),
    ("(1.", "接着讨论其他问题。", None, True),
    (r"\(1.", "5", None, True),
])
async def test_boundary_policy_does_not_certify_ambiguous_mid_sentence(first, second, expected, partial):
    class Replay:
        results = iter([("length", first), ("stop", second)])
        async def complete(self, *args, **kwargs):
            finish, text = next(self.results)
            return CompletionResult(text=text, finish_reason=finish, provider_id="offline", model="saved")
    turn = TutorTurnResult()
    token = current_turn.set(turn)
    try:
        result = await complete_tutor(Replay(), [], max_tokens=512, temperature=.4)
    finally:
        current_turn.reset(token)
    assert turn.partial is partial
    if expected:
        assert result.text == expected
    else:
        assert first in result.text and second in result.text


def test_saved_c0_final_body_and_partial_status_reach_product_websocket(tmp_path):
    from fastapi.testclient import TestClient
    from mathtutor.api.product_app import create_math_tutor_app
    from mathtutor.api.product_state import get_product_state, reset_product_state
    from mathtutor.security.settings import MathTutorSecuritySettings
    from mathtutor.infrastructure.generative_gateway import ModelRole
    rows=[json.loads((SAVED/f"request-{n:03}.json").read_text(encoding="utf-8")) for n in (74,75)]
    case=next(r for r in json.loads((SAVED/"B-results.json").read_text(encoding="utf-8")) if r["case_id"]=="degenerate:c0")
    class Replay:
        provider_id,model="offline","saved-041"
        calls=0
        async def complete(self, *args, **kwargs):
            row=rows[self.calls]
            self.calls+=1
            return CompletionResult(**row["response"])
    reset_product_state()
    try:
        app=create_math_tutor_app(MathTutorSecuritySettings(environment="development",host="127.0.0.1"),
            auth_enabled=False,db_path=str(tmp_path/"replay.db"))
        provider=Replay()
        with TestClient(app) as client:
            get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER,provider)
            frames=[]
            with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
                ws.send_json(dict(command="send_message",payload=dict(text=case["question"]),session_id="offline-c0"))
                while True:
                    frame=ws.receive_json(); frames.append(frame)
                    if frame["event_type"]=="turn_end": break
            terminal=next(f for f in frames if f["event_type"]=="assistant_partial")
            text=terminal["payload"]["final_text"]
            assert provider.calls==2 and terminal["payload"]["status"]=="PARTIAL"
            assert "续写接缝待核对" in text and "一正一负" in text
            assert all(r["response"]["text"] in text for r in rows)
            stored=client.get("/api/v2/math-tutor/sessions/offline-c0").json()["messages"][-1]
            assert stored["content"]==text and stored["status"]=="PARTIAL"
    finally:
        reset_product_state()


@pytest.mark.parametrize("first,second,finish,expected_status", [
    ("方程的根为", "0和-1。", "stop", "COMPLETED"),
    ("(1.", "5)", "stop", "COMPLETED"),
    (r"\(1.", r"5\)", "stop", "COMPLETED"),
    ("方程的根为", "0和-1。", "length", "PARTIAL"),
    ("方程的根为", "0和-1。一正一负。", "stop", "PARTIAL"),
    ("简单", "刚才说过。", "stop", "PARTIAL"),
])
def test_literal_continuation_delivery_and_persistence(tmp_path, first, second, finish, expected_status):
    from fastapi.testclient import TestClient
    from mathtutor.api.product_app import create_math_tutor_app
    from mathtutor.api.product_state import get_product_state, reset_product_state
    from mathtutor.security.settings import MathTutorSecuritySettings
    from mathtutor.infrastructure.generative_gateway import ModelRole
    class Replay:
        provider_id, model, calls = "offline", "literal-seam", 0
        async def complete(self, *args, **kwargs):
            self.calls += 1
            return CompletionResult(provider_id=self.provider_id, model=self.model,
                text=first if self.calls == 1 else second,
                finish_reason="length" if self.calls == 1 else finish)
    reset_product_state()
    try:
        app = create_math_tutor_app(MathTutorSecuritySettings(environment="development", host="127.0.0.1"),
            auth_enabled=False, db_path=str(tmp_path / "literal.db"))
        provider = Replay()
        with TestClient(app) as client:
            get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
            frames = []
            with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
                ws.send_json(dict(command="send_message", payload=dict(text="请解释二次方程的根。"), session_id="literal"))
                while True:
                    frame = ws.receive_json()
                    frames.append(frame)
                    if frame["event_type"] == "turn_end":
                        break
            terminal = next(f["payload"] for f in frames if f["event_type"] in {"assistant_complete", "assistant_partial"})
            assert terminal["status"] == expected_status and provider.calls == 2
            body = terminal["final_text"]
            assert first in body and second in body
            if expected_status == "COMPLETED":
                assert body == first + second
            saved = client.get("/api/v2/math-tutor/sessions/literal").json()["messages"][-1]
            assert saved["content"] == body and saved["status"] == expected_status
            # Delivery completion must never mint mathematical verification.
            assert terminal.get("verification") != "VERIFIED"
    finally:
        reset_product_state()
