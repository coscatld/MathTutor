"""Authenticated local image upload/read/delete; no remote URL ingestion."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.infrastructure.generative_gateway import ModelRole
from mathtutor.infrastructure.vision import supports_vision
from mathtutor.repositories.image_repository import MAX_IMAGE_BYTES

router = APIRouter(prefix="/api/v2/math-tutor")


@router.get("/image-capabilities")
async def capabilities(owner=Depends(require_student_owner)):
    provider = get_product_state().gateway.provider_for(ModelRole.TUTOR_WRITER)
    return {"vision": await supports_vision(provider), "provider": getattr(provider, "provider_id", ""), "model": getattr(provider, "model", "")}


@router.post("/images", status_code=201)
async def upload(file: UploadFile = File(...), owner=Depends(require_student_owner)):
    try:
        data = await file.read(MAX_IMAGE_BYTES + 1)
        return await get_product_state().images.put(owner.student_id, data, file.content_type, file.filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    finally:
        await file.close()


@router.get("/images/{image_id}")
async def read(image_id: str, owner=Depends(require_student_owner)):
    row = await get_product_state().images.get(owner.student_id, image_id)
    if row is None:
        raise HTTPException(404, "图片不存在或无权访问")
    return Response(row["data"], media_type=row["mime_type"], headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/images/{image_id}", status_code=204)
async def remove(image_id: str, owner=Depends(require_student_owner)):
    await get_product_state().images.remove(owner.student_id, image_id)
    return Response(status_code=204)
