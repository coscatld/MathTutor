"""Student-safe document and memory projections shared by HTTP and export."""

from pathlib import Path

from mathtutor.domain.memory import PersonalMemoryNode


def _project_document(doc) -> dict:
    """User-facing document projection — never storage/internal fields."""
    friendly_error = None
    if doc.status == "needs_ocr":
        friendly_error = (
            doc.parse_warning
            or "未提取到文字层，可能是扫描件。当前版本不支持 OCR，无法用于检索。"
        )
    elif doc.status == "failed":
        resource_errors = {
            "PARSE_PAGE_LIMIT": "资料页数超过处理上限，请拆分后重试。",
            "PARSE_TEXT_LIMIT": "资料文字量超过处理上限，请拆分后重试。",
            "PARSE_BLOCK_LIMIT": "资料内容数量超过处理上限，请拆分后重试。",
            "PARSE_ASSET_LIMIT": "资料图片数量或总大小超过处理上限，请拆分后重试。",
            "PARSE_TIMEOUT": "资料处理用时过长，请拆分资料后重试。",
            "PARSE_CANCELLED": "资料处理已取消，可以重新解析。",
            "PARSE_BUSY": "资料处理任务较多，请稍后重新解析。",
            "PARSE_CLOSED": "资料处理服务已关闭，请重新打开应用后重试。",
        }
        if getattr(doc, "classification", "") in resource_errors:
            friendly_error = resource_errors[doc.classification]
        elif Path(doc.filename).suffix.lower() == ".pdf":
            friendly_error = "无法解析此 PDF，请确认它是文本型 PDF（非扫描图片）。"
        else:
            friendly_error = "无法解析此文件，请确认内容是纯文本格式。"
    warning = doc.parse_warning or None
    return {
        "document_id": str(doc.document_id),
        "filename": doc.filename,
        "mime_type": doc.mime_type,
        "status": doc.status,
        "retrieval_enabled": doc.retrieval_enabled,
        "is_global": doc.is_global,
        "size_bytes": doc.size_bytes,
        "page_count": doc.page_count,
        "chunk_count": doc.chunk_count,
        "image_count": doc.image_count,
        "empty_page_count": doc.empty_page_count,
        "parse_warning": warning,
        "created_at": doc.created_at.isoformat(),
        "error": friendly_error,
    }


def _project_memory(node: PersonalMemoryNode) -> dict:
    return {
        "memory_id": str(node.memory_id),
        "memory_type": node.memory_type,
        "subject": node.subject,
        "predicate": node.predicate,
        "object_json": node.object_json,
        "source_type": node.source_type,
        "confidence": node.confidence,
        "retrieval_enabled": node.retrieval_enabled,
        "created_at": node.created_at.isoformat(),
        "updated_at": node.updated_at.isoformat(),
    }
