"""Certainty disclosure survives the real delivery, journal and history paths."""
import asyncio
from mathtutor.api.product_state import get_product_state
from mathtutor.pedagogy.tutor_writer import TutorWriterCandidate
from mathtutor.infrastructure.generative_gateway import CompletionResult, ModelRole
from test_tutor_p0 import client_at, send, summary


NOTICE = "> 本段讲解未经逐句数学核验。"


class UnverifiedWriter:
    async def write(self, **kwargs):
        return TutorWriterCandidate(
            text="等式两边同时减去相同的数，能保持等式成立。你想先去掉哪个常数？",
            writer_version="unverified-test-writer",
        )


def test_model_prose_is_disclosed_before_delivery_and_retained_after_restart(tmp_path):
    db = tmp_path / "explanation.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        get_product_state().controller.writer = UnverifiedWriter()
        frames = send(ws, "request_hint", "hint")
        visible = [f["payload"]["student_message"] for f in frames if f["event_type"] == "assistant_delta"][-1]
        assert visible.startswith(NOTICE)
        assert visible.count(NOTICE) == 1
        saved = next(m for m in summary(client)["messages"] if m.get("turn_id") == "hint")
        assert saved["content"] == visible
        assert send(ws, "request_hint", "hint") == frames
    with client_at(db) as client:
        restored = next(m for m in summary(client)["messages"] if m.get("turn_id") == "hint")
        assert restored["content"] == visible


def test_verified_template_material_does_not_acquire_a_model_notice(tmp_path):
    with client_at(tmp_path / "template.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        send(ws, "request_hint", "hint")
        saved = next(m for m in summary(client)["messages"] if m.get("turn_id") == "hint")
        assert NOTICE not in saved["content"]


def test_knowledge_explanation_keeps_prose_certainty_separate_from_source_receipts(tmp_path):
    class SourceResponse:
        async def respond(self, *args, **kwargs):
            return "资料中的引文可以追溯，但整段数学讲解还需要单独核对。"

    db = tmp_path / "knowledge-notice.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        asyncio.run(state.knowledge.configure("local-admin", "p0", space_ids=[]))
        state.controller.knowledge_qa = SourceResponse()
        frames = send(ws, "send_message", "source-explanation", {"text": "解释这份资料"})
        visible = next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]["final_text"]
        assert visible.startswith(NOTICE)
        assert send(ws, "send_message", "source-explanation", {"text": "解释这份资料"}) == frames
    with client_at(db) as client:
        assert next(m for m in summary(client)["messages"] if m.get("turn_id") == "source-explanation")["content"] == visible


def test_greeting_is_warm_but_a_generated_math_claim_still_requires_disclosure(tmp_path):
    class Response:
        provider_id, model = "offline", "greeting-test"
        def __init__(self):
            self.responses = iter(["你好，同学！", "你好，a=0时一定还是一元一次方程。"])
        async def complete(self, *args, **kwargs):
            return CompletionResult(text=next(self.responses), provider_id=self.provider_id,
                                    model=self.model, finish_reason="stop", input_tokens=10, output_tokens=10)

    with client_at(tmp_path / "greeting.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, Response())
        send(ws, "send_message", "greet", {"text": "你好"})
        assert summary(client)["messages"][-1]["content"] == "你好，同学！"
        send(ws, "send_message", "claim", {"text": "你好"})
        assert summary(client)["messages"][-1]["content"].startswith(NOTICE)
