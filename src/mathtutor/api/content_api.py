"""Owner-authenticated import/export of non-executable reference content."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.knowledge_api import state_for
from mathtutor.application.knowledge import KnowledgeError
from mathtutor.application.question_packs import MAX_UPLOAD_BYTES, QuestionPackError, QuestionPackService
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter(prefix="/content")


@router.post("/question-packs/import")
async def import_question_pack(file: UploadFile = File(...), name: str = Form(default=""),
                               owner: StudentOwnerScope = Depends(require_student_owner)):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "资料包最大 20 MiB。")
    state = state_for()
    async with state.turn_requests.owner(owner.student_id):
        try:
            return await QuestionPackService(state).import_pack(owner.student_id, data, file.filename or "", name=name)
        except QuestionPackError as exc:
            raise HTTPException(422, str(exc)) from exc
        except KnowledgeError as exc:
            raise HTTPException(409, str(exc)) from exc


@router.get("/libraries/{sid}/export")
async def export_content_library(sid: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    state = state_for()
    async with state.turn_requests.owner(owner.student_id):
        try:
            data = await QuestionPackService(state).export_library(owner.student_id, sid)
        except QuestionPackError as exc:
            raise HTTPException(422, str(exc)) from exc
        except KnowledgeError as exc:
            raise HTTPException(409, str(exc)) from exc
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": 'attachment; filename="MathTutor-learning-vault.zip"',
        "X-Content-Type-Options": "nosniff",
    })
