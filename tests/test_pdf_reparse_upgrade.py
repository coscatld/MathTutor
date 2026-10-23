"""Ready PDF reparse through the real HTTP and SQLite path, without live models."""
from contextlib import closing
import sqlite3
import pytest
from test_tutor_p0 import client_at
import mathtutor.infrastructure.document_parser as parser_module

def test_ready_pdf_reparse_uses_current_parser_on_stored_bytes(tmp_path, monkeypatch):
    fitz = pytest.importorskip("fitz", reason="Requires the optional rich parser")
    with fitz.open() as source:
        page = source.new_page()
        page.insert_text((72, 72), "配方法", fontsize=16, fontname="china-s")
        page.insert_text((72, 140), "通过配方求解方程。" * 3, fontsize=11, fontname="china-s")
        payload = source.tobytes()
    db = tmp_path / "pdf.db"
    prefix = "/api/v2/math-tutor/desktop/documents"
    rich = parser_module._pymupdf
    # Seed an existing text-only document with the old parser identity.
    monkeypatch.setattr(parser_module, "_pymupdf", lambda: None)
    monkeypatch.setattr(parser_module, "PARSER_VERSION", "mt-local-parser-v3")
    with client_at(db) as client:
        files = {"file": ("math.pdf", payload, "application/pdf")}
        imported = client.post(prefix + "/import", files=files)
        assert imported.status_code == 200, imported.text
        did = imported.json()["document_id"]
        assert imported.json()["status"] == "ready"
        with closing(sqlite3.connect(db)) as connection:
            assert connection.execute("SELECT parser_version FROM user_documents WHERE document_id = ?", (did,)).fetchone()[0] == "mt-local-parser-v3"
        monkeypatch.setattr(parser_module, "_pymupdf", rich)
        monkeypatch.setattr(parser_module, "PARSER_VERSION", "mt-local-parser-v4")
        duplicate = client.post(prefix + "/import", files=files)
        assert duplicate.json()["document_id"] == did
        with closing(sqlite3.connect(db)) as connection:
            assert connection.execute("SELECT parser_version FROM user_documents WHERE document_id = ?", (did,)).fetchone()[0] == "mt-local-parser-v3"
        disabled = client.patch(prefix + "/" + did + "/retrieval", json={"enabled": False})
        assert disabled.status_code == 200
        result = client.put(prefix + "/" + did)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "ready"
        assert result.json()["retrieval_enabled"] is False
        with closing(sqlite3.connect(db)) as connection:
            assert connection.execute("SELECT parser_version FROM user_documents WHERE document_id = ?", (did,)).fetchone()[0] == "mt-local-parser-v4"
            rows = connection.execute("SELECT section FROM document_chunks WHERE document_id = ?", (did,)).fetchall()
            assert rows and all(row[0] == "配方法" for row in rows), rows
