#!/usr/bin/env python3
"""Export desktop HTTP contracts without starting a runtime or touching user data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi import FastAPI
from pydantic import TypeAdapter

from mathtutor.api import (
    desktop_api,
    desktop_contracts,
    exploration_api,
    learning_profile_api,
    math_tutor_read,
)


def desktop_schema() -> dict:
    app = FastAPI(title="MathTutor desktop contracts", version="1")
    app.include_router(desktop_api.router, prefix=desktop_api.DESKTOP_ROUTER_PREFIX)
    app.include_router(exploration_api.router, prefix=desktop_api.DESKTOP_ROUTER_PREFIX)
    app.include_router(
        learning_profile_api.router, prefix=desktop_api.DESKTOP_ROUTER_PREFIX
    )
    app.include_router(math_tutor_read.router, prefix="/api/v2/math-tutor")
    schema = app.openapi()
    models = schema.setdefault("components", {}).setdefault("schemas", {})
    for name in desktop_contracts.PUBLIC_CONTRACTS:
        contract = TypeAdapter(getattr(desktop_contracts, name)).json_schema(
            ref_template="#/components/schemas/{model}"
        )
        models.update(contract.pop("$defs", {}))
        models[name] = contract
    return schema


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = (
        Path(__file__).resolve().parents[1]
        / "web/features/math-tutor/desktop/generated/openapi.json"
    )
    content = (
        json.dumps(desktop_schema(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            raise SystemExit("HTTP schema is stale; run npm run api:generate in web/.")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
