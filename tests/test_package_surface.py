"""Hard acceptance: every production RAG module must reach the shipped package.

This project has shipped the failure three separate times:

- ``pymupdf`` declared as a core dependency while the release omits it (D19);
- the retrieval/reranker modules excluded from the distribution while the
  code and tests looked wired;
- ``MathTutorMetrics`` constructed only by tests, so nothing in production
  recorded anything.

Each time, source and tests passed while the shipped artifact could not run
the capability. A capability therefore does not count as production unless it
is on the package surface — asserted here rather than assumed.
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "desktop" / "package_allowlist.json"

#: Modules this round added or rewired, plus the ones that already existed and
#: must keep shipping. Named explicitly: a glob that silently stops matching
#: is exactly the failure this test exists to catch.
REQUIRED_PRODUCTION_MODULES = (
    # Retrieval pipeline (Route 2)
    "src/mathtutor/application/retrieval_orchestrator.py",
    "src/mathtutor/application/rerank.py",
    "src/mathtutor/application/context_expansion.py",
    "src/mathtutor/domain/evidence.py",
    "src/mathtutor/application/document_ingestion.py",
    "src/mathtutor/application/chat_documents.py",
    "src/mathtutor/application/knowledge.py",
    "src/mathtutor/application/knowledge_qa.py",
    "src/mathtutor/application/knowledge_tools.py",
    "src/mathtutor/application/context_assembler.py",
    "src/mathtutor/application/conversation_scope.py",
    # Storage / index
    "src/mathtutor/repositories/document_repository.py",
    "src/mathtutor/repositories/sqlite_documents.py",
    "src/mathtutor/repositories/sqlite_knowledge.py",
    "src/mathtutor/infrastructure/document_parser.py",
    "src/mathtutor/infrastructure/document_fts.py",
    "src/mathtutor/infrastructure/chunking.py",
    "src/mathtutor/infrastructure/lexical.py",
    "src/mathtutor/infrastructure/schema.py",
    "src/mathtutor/infrastructure/knowledge_schema.py",
    # Telemetry
    "src/mathtutor/infrastructure/observability.py",
    # Domain
    "src/mathtutor/domain/documents.py",
    "src/mathtutor/domain/retrieval_policy.py",
)

#: Modules the packaging policy deliberately EXCLUDES. Pinned so a future
#: "cleanup" that starts shipping them is caught as a decision, not slipped in.
DELIBERATELY_EXCLUDED = (
    "src/mathtutor/application/lexical_reranker.py",
    "src/mathtutor/application/retrieval_router.py",
    "src/mathtutor/infrastructure/sqlite_vec_index.py",
)

#: Not shipped for a DIFFERENT reason: never needed by the packaged launcher,
#: not a capability gap. ``desktop/main.js`` starts the service with
#: ``import mathtutor.standalone``, so the ``python -m mathtutor`` convenience
#: entry point is a source-checkout affordance only.
SOURCE_CHECKOUT_ONLY = ("src/mathtutor/__main__.py",)


@pytest.fixture(scope="module")
def allowlist() -> dict:
    return json.loads(ALLOWLIST.read_text(encoding="utf-8"))


def _matches(path: str, pattern: str) -> bool:
    """Mirror of ``desktop/scripts/audit-package-surface.py::_matches``.

    Replicated rather than imported (it lives in a script, not a package) and
    deliberately identical: a test using different glob semantics than the
    packager would report gaps that do not exist, or miss ones that do.
    ``**/`` expands to zero directories, as electron-builder/minimatch do.
    """
    candidates = {pattern}
    while "/**/" in pattern:
        pattern = pattern.replace("/**/", "/", 1)
        candidates.add(pattern)
    return any(fnmatch.fnmatchcase(path, candidate) for candidate in candidates)


def _shipped(path: str, source: dict) -> bool:
    """Does ``path`` match the default-deny include/exclude policy?"""
    relative = str(Path(path).relative_to("src/mathtutor")).replace("\\", "/")
    included = any(_matches(relative, item) for item in source["include"])
    excluded = any(_matches(relative, item) for item in source["exclude"])
    return included and not excluded


@pytest.mark.parametrize("path", REQUIRED_PRODUCTION_MODULES)
def test_production_module_is_on_the_package_surface(allowlist, path: Path):
    source = allowlist["python_source"]
    assert (ROOT / path).exists(), f"{path} does not exist"
    assert _shipped(path, source), (
        f"{path} would NOT ship: the packaging policy excludes it, so the "
        "capability passes tests while being absent from the product"
    )


@pytest.mark.parametrize("path", DELIBERATELY_EXCLUDED)
def test_test_only_module_stays_off_the_package_surface(allowlist, path: Path):
    source = allowlist["python_source"]
    assert not _shipped(path, source), (
        f"{path} is test-only/legacy and must stay out of the shipped package"
    )


def test_no_production_module_is_silently_excluded():
    """Any module a production entry point imports must be shippable.

    Guards the general case, not just the names above: a new module reachable
    from ``application/`` that the policy drops is caught here.
    """
    source = (ROOT / "src" / "mathtutor")
    allowlist_source = json.loads(ALLOWLIST.read_text(encoding="utf-8"))["python_source"]

    unshipped = []
    for path in source.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        relative = str(path.relative_to(ROOT)).replace("\\", "/")
        if _shipped(relative, allowlist_source):
            continue
        name = path.name
        # Only files the policy *intends* to drop may be missing.
        known = DELIBERATELY_EXCLUDED + SOURCE_CHECKOUT_ONLY
        if any(Path(excluded).name == name for excluded in known):
            continue
        unshipped.append(relative)

    # Tests and data live outside src/mathtutor, so anything here is a policy
    # gap rather than an expected omission.
    assert unshipped == [], f"production modules excluded from the package: {unshipped}"
