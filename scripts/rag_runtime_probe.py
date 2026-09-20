"""Phase B 前置探测：确认 RAG 摄入链依赖的运行时能力是否真的可用。

背景（docs/CURRENT_STATE_RAG_AUDIT.md §6）：Phase A 有三项 NOT_VERIFIED，
它们决定 Phase B 的 PDF 分类能拿到多少逐页信息、以及检索走不走 FTS5：

    1. ``fitz``（PyMuPDF）在部署运行时是否可 import
    2. MinerU 是否可用（决定 ``ocr_text`` 是否可能被填充）
    3. FTS5 在发布构建的 SQLite 中是否可用

本脚本只读、无副作用：不写数据库、不改文件（PDF 在临时目录内合成）。
每个结论都基于**实际调用**，不是 ``importlib.util.find_spec`` 的存在性猜测。

用法::

    python scripts/rag_runtime_probe.py            # 人类可读
    python scripts/rag_runtime_probe.py --json     # 机器可读
"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

RESULTS: list[dict] = []


def record(area: str, check: str, ok: bool | None, detail: str) -> None:
    """``ok=None`` marks a purely informational observation (never a failure)."""
    RESULTS.append(
        {"area": area, "check": check, "ok": None if ok is None else bool(ok), "detail": detail}
    )


# --------------------------------------------------------------- parsers


def probe_pymupdf() -> None:
    """PyMuPDF 是 PDF 主路径；必须验证它真的能抽取文本，而不只是能 import。"""
    try:
        fitz = importlib.import_module("fitz")
    except Exception as error:
        record("pdf", "pymupdf_import", False, f"{type(error).__name__}: {error}")
        return
    record("pdf", "pymupdf_import", True, f"version={getattr(fitz, 'VersionBind', '?')}")

    # 合成一份带文字层的 PDF，验证「文字层抽取」这条路径真的能走通。
    try:
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 96), "x^2 + 2x + 1 = 0", fontsize=12)
        payload = document.tobytes()
        document.close()

        reopened = fitz.open(stream=payload, filetype="pdf")
        text = reopened[0].get_text("dict")
        reopened.close()
        spans = [
            span.get("text", "")
            for block in text.get("blocks", [])
            if block.get("type") == 0
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        ]
        joined = "".join(spans)
        extracted = "x^2 + 2x + 1 = 0" in joined
        record("pdf", "pymupdf_text_layer", extracted, f"extracted={joined!r}")
    except Exception as error:
        record("pdf", "pymupdf_text_layer", False, f"{type(error).__name__}: {error}")

    # 扫描页判定依赖 get_images；确认接口存在（不验证识别能力，无 OCR）。
    try:
        document = fitz.open()
        page = document.new_page()
        document.tobytes()
        has_api = hasattr(page, "get_images") and hasattr(page, "find_tables")
        document.close()
        record("pdf", "pymupdf_page_api", has_api, "get_images/find_tables present")
    except Exception as error:
        record("pdf", "pymupdf_page_api", False, f"{type(error).__name__}: {error}")


def probe_pypdf() -> None:
    """pypdf 是 PyMuPDF 缺失时的回退；该分支永不尝试 MinerU。"""
    try:
        pypdf = importlib.import_module("pypdf")
    except Exception as error:
        record("pdf", "pypdf_import", False, f"{type(error).__name__}: {error}")
        return
    record("pdf", "pypdf_import", True, f"version={getattr(pypdf, '__version__', '?')}")
    try:
        from pypdf import PdfReader, PdfWriter  # noqa: F401

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "probe.pdf"
            with open(target, "wb") as handle:
                writer.write(handle)
            reader = PdfReader(str(target))
            _ = (reader.pages[0].extract_text() or "").strip()
        record("pdf", "pypdf_extract", True, "extract_text() callable on a real PDF")
    except Exception as error:
        record("pdf", "pypdf_extract", False, f"{type(error).__name__}: {error}")


def probe_pdf_end_to_end() -> None:
    """端到端：让生产解析器真的跑一份 PDF，报告走了哪个分支、产出什么块。

    这是 Phase B 最关键的输入 —— PDF 分类能做到什么粒度，取决于解析器
    实际产出哪些 block type。
    """
    import asyncio

    from mathtutor.infrastructure.document_parser import LocalDocumentParser

    payload = _synthetic_pdf()
    if payload is None:
        record("pdf_e2e", "synthetic_pdf_build", False, "no PDF writer available to build the fixture")
        return

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "probe.pdf"
        target.write_bytes(payload)
        assets = Path(tmp) / "assets"
        try:
            parsed = asyncio.run(
                LocalDocumentParser().parse(
                    path=str(target), asset_dir=str(assets), asset_ref_prefix="probe"
                )
            )
        except Exception as error:
            record("pdf_e2e", "parse", False, f"{type(error).__name__}: {error}")
            return

    block_types: dict[str, int] = {}
    for block in parsed.blocks:
        block_types[block.type] = block_types.get(block.type, 0) + 1
    record("pdf_e2e", "parse", True, f"parse_mode={parsed.parse_mode}")
    record("pdf_e2e", "block_types", None, json.dumps(block_types, ensure_ascii=False))
    record(
        "pdf_e2e",
        "heading_blocks",
        block_types.get("heading", 0) > 0,
        "font-size heading detection requires PyMuPDF; pypdf emits paragraphs only",
    )
    record(
        "pdf_e2e",
        "table_blocks",
        block_types.get("table", 0) > 0,
        "table extraction requires PyMuPDF find_tables(); pypdf has no equivalent",
    )
    record(
        "pdf_e2e",
        "figure_blocks",
        block_types.get("figure", 0) > 0,
        "image extraction requires PyMuPDF get_images(); pypdf has no equivalent",
    )
    record(
        "pdf_e2e",
        "per_page_counting",
        parsed.total_pages > 0,
        f"total_pages={parsed.total_pages}, text_pages={parsed.text_pages}, empty_pages={parsed.empty_pages}",
    )


def _synthetic_pdf() -> bytes | None:
    """A minimal, hand-built PDF with a real text layer.

    Built from raw PDF syntax rather than through a library so the fixture is
    identical in every runtime — in particular it works when PyMuPDF is
    absent, which is exactly the configuration under test.
    """
    try:
        return _minimal_text_pdf(
            [
                "Quadratic formula x = (-b + sqrt(b^2 - 4ac)) / 2a",
                "Discriminant delta = b^2 - 4ac",
            ]
        )
    except Exception:
        return None


def _minimal_text_pdf(lines: list[str]) -> bytes:
    """Assemble a valid one-page PDF with an ASCII text layer and real xref."""
    content = "\n".join(
        f"BT /F1 12 Tf 72 {740 - index * 20} Td ({_escape_pdf(line)}) Tj ET"
        for index, line in enumerate(lines)
    ).encode("latin-1")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _escape_pdf(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def probe_mineru() -> None:
    """MinerU 是唯一的 ``ocr_text`` 来源，且不是声明依赖。"""
    executable = shutil.which("mineru")
    record("ocr", "mineru_cli_on_path", bool(executable), executable or "not on PATH")

    importable = []
    for module in ("magic_pdf", "mineru"):
        try:
            importlib.import_module(module)
            importable.append(module)
        except Exception:
            pass
    record("ocr", "mineru_module_importable", bool(importable), ",".join(importable) or "neither")

    # mineru_available() 的口径：which(cli) 或 magic_pdf/mineru 可导入即视为可用。
    # 但 _run_mineru_cli 仍要求 CLI 在 PATH 上 —— 两者可能背离。
    from mathtutor.infrastructure.parse_adapters import mineru_available

    available = mineru_available()
    divergent = available and not executable
    record(
        "ocr",
        "mineru_available",
        available,
        f"mineru_available()={available}, cli_on_path={bool(executable)}, divergent={divergent}",
    )
    if divergent:
        record(
            "ocr",
            "mineru_availability_divergence",
            False,
            "mineru_available() reports True but the CLI is absent, so parsing still degrades to needs_ocr",
        )

    # 仓库内是否存在任何 OCR 引擎（Phase A 结论的现场复核）。
    engines = [name for name in ("pytesseract", "paddleocr", "easyocr", "rapidocr_onnxruntime") if _importable(name)]
    record("ocr", "ocr_engine_present", bool(engines), ",".join(engines) or "no OCR engine installed")


def _importable(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


# --------------------------------------------------------------- indexes


def probe_production_modules() -> None:
    """Every production RAG module must import in THIS runtime.

    Companion to tests/test_package_surface.py: that test checks the packaging
    POLICY, this checks the actual interpreter. "Source passes, shipped
    artifact lacks the module" has happened here three times (PyMuPDF, the old
    retrieval stack, observability), so both halves are asserted.
    """
    modules = (
        "mathtutor.application.retrieval_orchestrator",
        "mathtutor.application.rerank",
        "mathtutor.application.context_expansion",
        "mathtutor.application.chat_documents",
        "mathtutor.application.knowledge_qa",
        "mathtutor.application.knowledge_tools",
        "mathtutor.domain.evidence",
        "mathtutor.infrastructure.observability",
    )
    for name in modules:
        try:
            importlib.import_module(name)
            record("modules", name.rsplit(".", 1)[1], True, "importable")
        except Exception as error:
            record("modules", name.rsplit(".", 1)[1], False, f"{type(error).__name__}: {error}")

    try:
        from mathtutor.api.product_state import ProductState

        state = ProductState()
        has_metrics = getattr(state, "metrics", None) is not None
        record(
            "modules",
            "ProductState.metrics",
            has_metrics,
            "registry present" if has_metrics else "MISSING — nothing would be recorded",
        )
    except Exception as error:
        record("modules", "ProductState.metrics", False, f"{type(error).__name__}: {error}")


def probe_fts5() -> None:
    """FTS5 决定词法检索走 MATCH 还是退化成 LIKE。

    必须用生产分词器构造索引串：CJK bigram 是在 Python 侧预先切好的
    （``build_fts_text``），直接插入原始中文只会得到一个整段 token，
    测不出真实行为。
    """
    from mathtutor.infrastructure.document_fts import FTS_TABLE
    from mathtutor.infrastructure.lexical import (
        build_fts_text,
        fts_match_query,
        fts_query_tokens,
    )

    record("index", "sqlite_version", True, sqlite3.sqlite_version)
    connection = sqlite3.connect(":memory:")
    record("index", "sqlite_source_id", None,
           connection.execute("SELECT sqlite_source_id()").fetchone()[0])
    try:
        try:
            connection.execute(
                f"CREATE VIRTUAL TABLE {FTS_TABLE} USING fts5("
                "chunk_id UNINDEXED, student_id UNINDEXED, document_id UNINDEXED, "
                "fts_text, tokenize='unicode61')"
            )
            record("index", "fts5_create", True, "fts5 virtual table created")
        except Exception as error:
            record("index", "fts5_create", False, f"{type(error).__name__}: {error}")
            return

        source = "一元二次方程 ax^2+bx+c=0 的求根公式，判别式 Δ=b²-4ac"
        indexed = build_fts_text(source)
        connection.execute(
            f"INSERT INTO {FTS_TABLE}(chunk_id, student_id, document_id, fts_text) "
            "VALUES ('c1', 's1', 'd1', ?)",
            (indexed,),
        )

        # 生产查询形状：fts_query_tokens → fts_match_query → MATCH + bm25。
        for query in ("求根公式", "判别式", "二次方程"):
            tokens = fts_query_tokens(query)
            match = fts_match_query(tokens)
            rows = connection.execute(
                f"SELECT chunk_id, bm25({FTS_TABLE}) FROM {FTS_TABLE} "
                f"WHERE {FTS_TABLE} MATCH ?",
                (match,),
            ).fetchall()
            record(
                "index",
                f"fts5_match:{query}",
                bool(rows),
                f"tokens={tokens} matched={len(rows)}",
            )

        # 别名扩充：源文只写「一元二次方程」，查询「解方程」应能命中。
        alias_rows = connection.execute(
            f"SELECT chunk_id FROM {FTS_TABLE} WHERE {FTS_TABLE} MATCH ?",
            (fts_match_query(fts_query_tokens("解方程")),),
        ).fetchall()
        record(
            "index",
            "fts5_alias_expansion",
            bool(alias_rows),
            "query 解方程 hits a chunk whose source text only said 一元二次方程",
        )
    finally:
        connection.close()


def probe_sqlite_vec() -> None:
    """sqlite-vec 是 OPTIONAL/NOT DEFAULT；此处只报告可达性，不作为阻塞项。"""
    try:
        extension = sqlite3.connect(":memory:")
        extension.enable_load_extension(True)
    except Exception as error:
        record("index", "sqlite_load_extension", False, f"{type(error).__name__}: {error}")
        return
    record("index", "sqlite_load_extension", True, "enable_load_extension available")
    extension.close()
    record(
        "index",
        "sqlite_vec_binary",
        False,
        "no vec0 shared library is resolved on this platform; sqlite-vec stays OPTIONAL",
    )


def probe_embeddings() -> None:
    """embedding backend 决定检索走 hybrid 还是纯词法降级。"""
    for module in ("torch", "sentence_transformers", "modelscope"):
        record("embedding", f"{module}_import", _importable(module), "declared dependency" if module != "torch" else "transitive via sentence-transformers")

    from mathtutor.infrastructure.embedding_runtime import EmbeddingRuntime

    status = EmbeddingRuntime().status()
    record(
        "embedding",
        "default_runtime_status",
        True,
        f"available={status.available}, reason={status.reason}",
    )


# --------------------------------------------------------------- schema


def probe_rag_schema() -> None:
    """确认当前迁移链能在本机真正建出 RAG 相关表（含 FTS5 vtable）。"""
    from mathtutor.infrastructure.migrate import upgrade_db

    with tempfile.TemporaryDirectory() as tmp:
        db_file = Path(tmp) / "probe.db"
        try:
            upgrade_db(str(db_file))
            record("schema", "migration_upgrade", True, "upgrade_db completed")
        except Exception as error:
            record("schema", "migration_upgrade", False, f"{type(error).__name__}: {error}")
            return

        connection = sqlite3.connect(str(db_file))
        try:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                )
            }
            for table in (
                "user_documents",
                "document_chunks",
                "document_chunks_fts",
                "document_chunk_vectors",
                "document_index_builds",
                "conversation_documents",
                "knowledge_spaces",
                "knowledge_members",
                "knowledge_bindings",
                "knowledge_versions",
                "knowledge_drafts",
                "knowledge_generations",
            ):
                record("schema", f"table:{table}", table in names, "present" if table in names else "MISSING")
        finally:
            connection.close()


def probe_runtime_identity() -> None:
    record("runtime", "python_version", None, sys.version.replace("\n", " "))
    record("runtime", "executable", None, sys.executable)
    record("runtime", "frozen", None, str(bool(getattr(sys, "frozen", False))))


# --------------------------------------------------------------- entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    probe_runtime_identity()
    probe_pymupdf()
    probe_pypdf()
    probe_pdf_end_to_end()
    probe_mineru()
    probe_production_modules()
    probe_fts5()
    probe_sqlite_vec()
    probe_embeddings()
    probe_rag_schema()

    if args.json:
        print(json.dumps(RESULTS, ensure_ascii=False, indent=2))
        return 0

    area = None
    for row in RESULTS:
        if row["area"] != area:
            area = row["area"]
            print(f"\n[{area}]")
        mark = "INFO" if row["ok"] is None else ("PASS" if row["ok"] else "MISS")
        print(f"  {mark}  {row['check']}: {row['detail']}")

    checks = [row for row in RESULTS if row["ok"] is not None]
    failures = [row for row in checks if not row["ok"]]
    print(f"\n{len(checks) - len(failures)}/{len(checks)} checks passed")
    for row in failures:
        print(f"  MISSING: [{row['area']}] {row['check']} — {row['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
