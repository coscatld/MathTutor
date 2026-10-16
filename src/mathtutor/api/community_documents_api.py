"""Owner-authenticated explicit import of reference files and folder uploads."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.creator_api import require_local_creator_origin
from mathtutor.api.product_state import get_product_state
from mathtutor.application.community_documents import CommunityDocumentService, DocumentUpload, TEXT_SUFFIXES
from mathtutor.application.knowledge import KnowledgeError
from mathtutor.application.question_packs import MAX_FILES, MAX_MARKDOWN_BYTES, MAX_UPLOAD_BYTES
from mathtutor.security.scopes import StudentOwnerScope
from pathlib import PurePosixPath

router = APIRouter(prefix="/community/documents")


@router.post("/import", dependencies=[Depends(require_local_creator_origin)])
async def import_documents(files: list[UploadFile] = File(...),
        operation_id: str | None = Form(default=None, min_length=1, max_length=128),
        owner: StudentOwnerScope = Depends(require_student_owner)):
    if not 1 <= len(files) <= MAX_FILES:
        raise HTTPException(413, "请选择 1–1000 份资料文件。")
    state = get_product_state()
    async with state.turn_requests.owner(owner.student_id):
        uploads, total = [], 0
        try:
            for file in files:
                filename = file.filename or ""
                text = PurePosixPath(filename).suffix.casefold() in TEXT_SUFFIXES
                limit = MAX_MARKDOWN_BYTES if text or len(files) > 1 else MAX_UPLOAD_BYTES
                data = await file.read(limit + 1)
                if len(data) > limit:
                    raise HTTPException(413, "每份文本最多 1 MiB，资料包最多 20 MiB。")
                total += len(data)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "资料文件合计不能超过 20 MiB，请分批导入。")
                uploads.append(DocumentUpload(filename, data))
            return await CommunityDocumentService(state).import_files(owner.student_id, uploads, operation_id=operation_id)
        except KnowledgeError as exc:
            detail = str(exc).replace("JSON", "文件内容").replace("SHA256", "完整性").replace("Base64", "文件编码")
            raise HTTPException(409, detail) from None
        finally:
            for file in files:
                await file.close()
