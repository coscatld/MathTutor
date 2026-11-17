"""Assemble the owner-scoped desktop HTTP surface.

Domain adapters live in ``api.routers``. This module preserves the public
mounting prefix and startup/readiness entry points used by the product app.
"""

from fastapi import APIRouter

from mathtutor.api.routers import (
    backup,
    bootstrap,
    diagnostics,
    documents,
    embedding_settings,
    exercises,
    learning_settings,
    memory,
    privacy,
    readiness,
    settings,
    student,
)
from mathtutor.api.routers.bootstrap import run_bootstrap
from mathtutor.api.routers.readiness import build_readiness
from mathtutor.api.routers.settings import mask_secret

DESKTOP_ROUTER_PREFIX = "/api/v2/math-tutor/desktop"
router = APIRouter()
router.include_router(settings.router)
router.include_router(embedding_settings.router)
router.include_router(readiness.router)
router.include_router(bootstrap.router)
router.include_router(backup.router)
router.include_router(privacy.router)
router.include_router(student.router)
router.include_router(learning_settings.router)
router.include_router(exercises.router)
router.include_router(diagnostics.router)
router.include_router(documents.router)
router.include_router(memory.router)

__all__ = [
    "DESKTOP_ROUTER_PREFIX",
    "router",
    "run_bootstrap",
    "build_readiness",
    "mask_secret",
]
