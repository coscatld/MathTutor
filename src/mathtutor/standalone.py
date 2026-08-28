"""Self-contained MathTutor application bootstrap.

This entry constructs only the product database, local auth provider,
controller and allowlisted API.  It never imports the DeepTutor orchestrator,
capability registry, tools, agents, plugins or MCP surfaces.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.security.settings import load_math_tutor_security_settings


def resolve_standalone_data_root() -> Path:
    explicit = os.environ.get("MATHTUTOR_DATA_ROOT", "").strip()
    if explicit:
        return Path(explicit).resolve()
    db_path = os.environ.get("MATHTUTOR_DB_PATH", "").strip()
    if db_path:
        return Path(db_path).resolve().parent
    # Deprecated one-release data-root alias for already installed 0.2.0
    # shells. New standalone launchers emit MATHTUTOR_DATA_ROOT only.
    legacy_home = os.environ.get("DEEPTUTOR_HOME", "").strip()
    if legacy_home:
        return Path(legacy_home).resolve()
    return (Path.cwd() / "data").resolve()


def create_standalone_app(data_root: Path | None = None) -> FastAPI:
    root = (data_root or resolve_standalone_data_root()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return create_math_tutor_app(
        settings=load_math_tutor_security_settings(),
        db_path=str(root / "math_tutor.db"),
    )


def main() -> None:  # pragma: no cover - exercised by packaged launch smoke
    import uvicorn

    settings = load_math_tutor_security_settings()
    uvicorn.run(
        create_standalone_app(),
        host=settings.host or "127.0.0.1",
        port=int(os.environ.get("MATHTUTOR_PORT", "8001")),
    )


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["create_standalone_app", "main", "resolve_standalone_data_root"]
