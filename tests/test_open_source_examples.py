"""Contributed examples use real import, edit, permission and run paths.

Only the reviewed Fraction calculator executes, after explicit code consent.
These offline checks are not a model-quality or OS-sandbox evaluation.
"""
import importlib.util
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3

from mathtutor.application.question_packs import parse_pack, REFERENCE_NOTICE
from mathtutor.question_bank.service import QuestionBankService
from test_tutor_p0 import client_at

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
BASE = "/api/v2/math-tutor/desktop"
PLUGINS = BASE + "/community/plugins"
LEARNING_TABLES = ("attempts", "mastery_evidence", "learning_events", "learning_predictions", "student_state_snapshots")


def builder(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


teaching_builder = builder("open_source_teaching_builder", EXAMPLES / "community-plugins/build_bundle.py")
code_builder = builder("open_source_code_builder", EXAMPLES / "code-plugins/build_bundle.py")


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def learning_counts(db):
    with closing(sqlite3.connect(db)) as connection:
        return {table: connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                for table in LEARNING_TABLES}


def upload_plugin(client, path, operation_id):
    return ok(client.post(PLUGINS + "/import", files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
                          data={"operation_id": operation_id}))["plugin"]


def test_shared_example_imports_as_reference_and_exports_the_current_edited_body(tmp_path):
    source_path = EXAMPLES / "question-packs/grade10-quadratic-functions.json"
    original = source_path.read_bytes()
    questions = {row["id"]: row for row in json.loads(original)["questions"]}
    db = tmp_path / "shared.db"
    with client_at(db) as client:
        before = learning_counts(db)
        imported = ok(client.post(BASE + "/community/documents/import",
            files=[("files", (source_path.name, original, "application/json"))],
            data={"operation_id": "contributed-question-pack"}))
        assert imported["kind"] == "question-pack" and imported["imported_count"] == 3
        sid = imported["space_id"]
        notes = ok(client.get(BASE + f"/knowledge/libraries/{sid}/notes"))
        assert len(notes) == len(questions) == 3
        current_bodies = {}
        for index, note in enumerate(notes):
            source = ok(client.get(BASE + "/knowledge/sources/" + note["document_id"]))
            question = questions[source["provenance"]["question_id"]]
            assert source["provenance"]["answer_verified"] is False
            assert question["stem"] in source["body"] and question["answer"] in source["body"]
            assert question["explanation"] in source["body"] and REFERENCE_NOTICE in source["body"]
            body = source["body"] + "\n个人补充：先完成配方，再核对结论。\n"
            relative_path = note["provenance"]["relative_path"]
            ok(client.post(BASE + f"/knowledge/libraries/{sid}/notes", json={
                "document_id": note["document_id"], "expected_version": source["version"],
                "title": source["title"], "body": body, "relative_path": relative_path,
                "operation_id": "edit-contributed-" + str(index)}))
            current_bodies[relative_path] = body
        response = client.get(BASE + f"/content/libraries/{sid}/export")
        assert response.status_code == 200, response.text
        exported = parse_pack(response.content, "edited-reference-library.zip")
        assert {note.path: note.body for note in exported.notes} == current_bodies
        scope = ok(client.get(BASE + "/knowledge/conversations/not-mounted-by-example"))
        assert scope["space_ids"] == [] and scope["document_ids"] == []
        assert learning_counts(db) == before
    assert source_path.read_bytes() == original


def test_teaching_example_bundles_and_imports_then_reads_real_grade10_questions(tmp_path):
    manifest = EXAMPLES / "community-plugins/grade10-practice.plugin.json"
    output = tmp_path / "grade10-practice-1.0.0.mathtutor"
    assert teaching_builder.main([str(manifest), "--output", str(output)]) == 0
    bank = QuestionBankService()
    references = {row["id"]: row for rows in bank.references.values() for row in rows}
    db = tmp_path / "teaching.db"
    with client_at(db) as client:
        before = learning_counts(db)
        installed = upload_plugin(client, output, "contributed-teaching")
        pid = installed["plugin"]["id"]
        assert pid == "example.grade10-practice" and not installed["enabled"]
        assert installed["consented_permissions"] == []
        assert client.post(PLUGINS + f"/{pid}/run", json={}).status_code == 409
        assert client.put(PLUGINS + f"/{pid}/enabled", json={"enabled": True}).status_code == 409
        ok(client.put(PLUGINS + f"/{pid}/enabled", json={"enabled": True, "consent_permissions": ["question_bank"]}))
        result = ok(client.post(PLUGINS + f"/{pid}/run", json={}))
        assert result["status"] == "ok" and result["authority"] == "reference_only" and result["read_only"] is True
        assert result["data"]["actual_count"] == result["data"]["requested_count"] == 6
        assert result["data"]["answers_included"] is False
        for question in result["data"]["questions"]:
            assert question["grade"] == 10 and question["text"] == references[question["id"]]["text"]
            assert "reference_answer" not in question and "explanation" not in question
            assert question["verification"]["student_steps_auto_verified"] is False
        assert learning_counts(db) == before


def test_vertex_example_requires_code_consent_and_returns_exact_reviewed_results(tmp_path):
    directory = EXAMPLES / "code-plugins/quadratic-vertex"
    output = tmp_path / "quadratic-vertex-1.0.0.zip"
    assert code_builder.main([str(directory), "--include", "README.md", "--output", str(output)]) == 0
    db = tmp_path / "vertex.db"
    with client_at(db) as client:
        before = learning_counts(db)
        installed = upload_plugin(client, output, "contributed-vertex")
        pid = installed["plugin"]["id"]
        assert pid == "example.quadratic-vertex" and installed["command"] == "vertex"
        assert not installed["enabled"] and installed["consented_permissions"] == []
        assert client.post(PLUGINS + f"/{pid}/run", json={"text": "1 -4 3"}).status_code == 409
        assert client.put(PLUGINS + f"/{pid}/enabled", json={"enabled": True,
            "consent_permissions": ["question_bank"]}).status_code == 409
        assert client.put(PLUGINS + f"/{pid}/enabled", json={"enabled": True}).status_code == 409
        ok(client.put(PLUGINS + f"/{pid}/enabled", json={"enabled": True,
            "consent_permissions": ["execute_local_code"]}))
        # Hand-calculated anchors cover integer, fractional and concave cases.
        cases = [("1 -4 3", "2", "-1", 4), ("2 1 -3", "-1/4", "-25/8", 25),
                 ("-2 8 1", "2", "9", 72)]
        for index, (text, x, y, discriminant) in enumerate(cases):
            result = ok(client.post(PLUGINS + f"/{pid}/run", json={
                "text": text, "operation_id": "vertex-anchor-" + str(index)}))
            assert result["read_only"] is False and result["sandboxed"] is False
            assert result["authority"] == "reference_only"
            actual = result["data"]["data"]
            assert (actual["vertex_x"], actual["vertex_y"], actual["discriminant"]) == (x, y, discriminant)
        invalid = ok(client.post(PLUGINS + f"/{pid}/run", json={"text": "0 1 2", "operation_id": "not-quadratic"}))
        assert "0 < |a|" in invalid["data"]["text"] and "data" not in invalid["data"]

        # A real versioned ZIP upgrade must not inherit previous code trust.
        upgraded_directory = tmp_path / "upgraded"
        shutil.copytree(directory, upgraded_directory)
        metadata_path = upgraded_directory / "plugin.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata.update(version="1.0.1", changelog="1.0.1：演示升级后重新确认本地代码授权。")
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        upgraded_output = tmp_path / "quadratic-vertex-1.0.1.zip"
        assert code_builder.main([str(upgraded_directory), "--include", "README.md", "--output", str(upgraded_output)]) == 0
        upgraded = upload_plugin(client, upgraded_output, "contributed-vertex-upgrade")
        assert upgraded["plugin"]["version"] == "1.0.1" and not upgraded["enabled"]
        assert upgraded["consented_permissions"] == []
        assert client.post(PLUGINS + f"/{pid}/run", json={"text": "1 -4 3"}).status_code == 409
        assert learning_counts(db) == before
