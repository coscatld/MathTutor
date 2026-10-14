"""Replay a recorded conversation up to one turn in a throwaway database.

    PYTHONPATH=src python scripts/replay_turn.py --db path/to/math_tutor.db \
        --conversation <conversation_id> --turn <turn_id> [--output report.json]

Requests are rebuilt from conversation_messages (what the student typed, or
the button label) plus the command recorded in turn_traces. The original
database is opened read-only and never modified. The replay uses the template
writer unless --mode live is given, so model wording will differ; the point is
to see whether the deterministic path (state, actions, errors, formula checks)
reproduces. Offers are re-bound to the replayed session's own active offer.
"""
import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

PAYLOAD_KEY = {"send_message": "text", "submit_problem": "text", "clarify_problem": "text",
               "clarify_attempt": "text", "submit_attempt": "answer"}


def load_turns(db: Path, conversation: str, until: str) -> list[dict]:
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        traces = {r["turn_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM turn_traces WHERE conversation_id = ?", (conversation,))}
        students = conn.execute(
            "SELECT event_key, content FROM conversation_messages WHERE conversation_id = ? AND role = 'student' "
            "ORDER BY created_at", (conversation,)).fetchall()
    turns = []
    for row in students:
        turn_id = row["event_key"].removeprefix("student:")
        trace = traces.get(turn_id)
        if trace is None:
            continue
        command = trace["command"] or "send_message"
        payload = {PAYLOAD_KEY[command]: row["content"]} if command in PAYLOAD_KEY else {}
        turns.append({"turn_id": turn_id, "command": command, "payload": payload,
                      "original": {k: trace[k] for k in ("status", "finish_reason", "error_code")}
                      | {"actions": json.loads(trace["actions"]), "details": json.loads(trace["details"])}})
        if turn_id == until:
            return turns
    raise SystemExit(f"turn {until} has no trace in conversation {conversation}")


def main() -> int:
    from mathtutor.application.math_claims import certify
    from mathtutor.application.verification_backend import InProcessVerificationBackend
    from mathtutor.evaluation.tutor_multiturn import _client, _send, _turn_view
    import asyncio

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--conversation", required=True)
    parser.add_argument("--turn", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    turns = load_turns(args.db, args.conversation, args.turn)
    session = f"replay-{args.conversation}"
    results = []
    with tempfile.TemporaryDirectory(prefix="mt-replay-") as tmp, \
            _client(Path(tmp) / "replay.db", None) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        for index, turn in enumerate(turns):
            payload = dict(turn["payload"])
            if turn["command"] in {"accept_practice_offer", "decline_practice_offer"}:
                offer = client.get(f"/api/v2/math-tutor/sessions/{session}").json().get("active_offer") or {}
                payload["offer_id"] = offer.get("offer_id", "")
            view = _turn_view(_send(ws, session, turn["command"], f"replay-{index}", payload))
            for delivery in view["deliveries"]:
                ws.send_json({"type": "delivery_presented", "delivery_id": delivery})
            refuted = asyncio.run(certify(view["text"], InProcessVerificationBackend())).refuted
            replayed = {"status": view["status"], "actions": list(dict.fromkeys(view["actions"])),
                        "error_code": (view["errors"] or [""])[0], "formulas_refuted": len(refuted)}
            original = turn["original"]
            same = (original["status"] == replayed["status"] and original["error_code"] == replayed["error_code"]
                    and set(original["actions"]) == set(replayed["actions"]))
            results.append({"turn_id": turn["turn_id"], "command": turn["command"], "original": original,
                            "replayed": replayed, "reproduced": same})
    target = results[-1]
    report = {"conversation": args.conversation, "turn": args.turn, "target_reproduced": target["reproduced"],
              "turns": results}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
