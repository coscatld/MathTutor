"""Optional parse backends — NOT default dependencies, never cloud-forced.

Decision tree (see LocalDocumentParser):

    digital PDF  → PyMuPDF (text layer + embedded images)
    empty text layer → MinerU if locally installed
    MinerU missing/fail → needs_ocr (never pretend success)

Docling and LlamaParse are adapter stubs only. LlamaParse would need a
cloud API key and is never invoked from the default pipeline.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from mathtutor.domain.documents import DocumentParseError, ParsedBlock, ParsedTextDocument


def mineru_available() -> bool:
    """True when a local MinerU install is importable or on PATH."""
    if shutil.which("mineru"):
        return True
    try:
        import magic_pdf  # noqa: F401

        return True
    except ImportError:
        pass
    try:
        import mineru  # noqa: F401

        return True
    except ImportError:
        return False


def try_mineru_parse(
    file_path: Path, *, asset_dir: str | None, asset_ref_prefix: str
) -> ParsedTextDocument | None:
    """Best-effort MinerU; budget/cancellation failures remain classified."""
    if not mineru_available():
        return None
    try:
        return _run_mineru_cli(file_path, asset_dir=asset_dir, asset_ref_prefix=asset_ref_prefix)
    except DocumentParseError:
        raise
    except Exception:
        return None


def _run_mineru_cli(
    file_path: Path, *, asset_dir: str | None, asset_ref_prefix: str
) -> ParsedTextDocument | None:
    """Invoke ``mineru`` CLI if present; parse produced markdown if any.

    No model download is triggered here beyond what a preinstalled MinerU
    already does. Timeouts and non-zero exits return None.
    """
    import subprocess
    import tempfile
    import time

    # Loaded at invocation time to avoid the parser/adapter import cycle.
    from mathtutor.infrastructure.document_parser import _ACTIVE_BUDGET

    budget = _ACTIVE_BUDGET.get(None)

    if not shutil.which("mineru"):
        return None
    with tempfile.TemporaryDirectory(prefix="mathtutor-mineru-") as tmp:
        process = subprocess.Popen(
            ["mineru", "-p", str(file_path), "-o", tmp],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 90
        try:
            while process.poll() is None:
                if budget is not None:
                    budget.check()
                if time.monotonic() >= deadline:
                    return None
                try:
                    process.wait(timeout=0.05)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
        if process.returncode != 0:
            return None
        markdown_file = None
        for candidate in Path(tmp).rglob("*.md"):
            if budget is not None:
                budget.check()
            if markdown_file is None or candidate < markdown_file:
                markdown_file = candidate
        if markdown_file is None:
            return None
        char_limit = budget.limits.max_text_chars if budget is not None else 2_000_000
        with markdown_file.open("rb") as stream:
            raw = stream.read(char_limit * 4 + 1)
        text = raw.decode("utf-8", errors="replace").strip()
        if len(raw) > char_limit * 4 or len(text) > char_limit:
            raise DocumentParseError("PARSE_TEXT_LIMIT", "文档提取文字超过解析限制。")
        if not text:
            return None
        blocks = [
            ParsedBlock(
                type="paragraph",
                page=1,
                text=part,
                ocr_text=part,
            )
            for part in _split_paragraphs(text)
            if part
        ]
        chars = len(text)
        image_count = 0
        if asset_dir:
            dest = Path(asset_dir)
            dest.mkdir(parents=True, exist_ok=True)
            for index, image in enumerate(Path(tmp).rglob("*.png")):
                if budget is not None:
                    budget.asset(image.stat().st_size)
                name = f"mineru-img-{index}{image.suffix.lower()}"
                target = dest / name
                target.write_bytes(image.read_bytes())
                ref = f"{asset_ref_prefix}/{name}" if asset_ref_prefix else name
                blocks.append(
                    ParsedBlock(
                        type="figure",
                        page=1,
                        image_path=ref,
                        ocr_text="",
                    )
                )
                image_count += 1
        return ParsedTextDocument(
            blocks=tuple(blocks),
            total_pages=1,
            text_pages=1 if chars else 0,
            empty_pages=0,
            extractable_chars=chars,
            parse_mode="text_layer" if chars else "empty",
            parse_warning="",
            image_count=image_count,
        )


def _split_paragraphs(text: str) -> list[str]:
    import re

    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


class DoclingAdapter:
    """Optional local adapter. Not a default dependency; unused by ingest.

    Install would be ``docling`` on the operator's machine. MathTutor never
    pulls it in, and the default parser never calls :meth:`parse`.
    """

    def available(self) -> bool:
        try:
            import docling  # noqa: F401

            return True
        except ImportError:
            return False

    async def parse(self, *, path: str) -> ParsedTextDocument:
        raise RuntimeError("DoclingAdapter is not wired into the default parser")


class LlamaParseAdapter:
    """Cloud adapter stub — requires an API key; never called by default.

    MathTutor does not prompt for or store a LlamaParse/VLM key as part of
    document ingest. This class exists so a future opt-in can implement
    :meth:`parse` without changing the domain IR.
    """

    def available(self) -> bool:
        return False

    async def parse(self, *, path: str) -> ParsedTextDocument:
        raise RuntimeError("LlamaParse is disabled (no cloud API in the default pipeline)")


__all__ = [
    "DoclingAdapter",
    "LlamaParseAdapter",
    "mineru_available",
    "try_mineru_parse",
]
