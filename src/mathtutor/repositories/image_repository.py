"""Owner-scoped local blob storage. No Base64 in history or browser storage."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select, delete
from mathtutor.infrastructure.schema import image_attachments
from mathtutor.repositories.sqlite_runtime import ensure_student

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGES = 4
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


def validate_image(data: bytes, mime_type: str):
    if mime_type not in IMAGE_TYPES:
        raise ValueError("暂不支持该图片格式")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("单张图片不能超过 10 MB")
    # Check container signatures as well as client MIME. Never serve SVG/HTML.
    valid = ((mime_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
        or (mime_type == "image/jpeg" and data.startswith(b"\xff\xd8\xff"))
        or (mime_type == "image/webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP"))
    if not valid:
        raise ValueError("图片内容与格式不符，或文件已损坏")


def public_image(row):
    return {"id": row["id"], "type": "image", "mimeType": row["mime_type"],
        "name": row["name"], "size": len(row["data"]),
        "url": f'/api/v2/math-tutor/images/{row["id"]}'}


class ImageRepository:
    def __init__(self, engine=None):
        self.engine = engine
        self.rows = {}

    async def put(self, owner, data, mime_type, name):
        validate_image(data, mime_type)
        row = dict(id=str(uuid4()), student_id=owner, data=data, mime_type=mime_type,
            name=(name or "image")[:160], created_at=datetime.now(timezone.utc).isoformat())
        if self.engine is None:
            self.rows[row["id"]] = row
        else:
            async with self.engine.begin() as conn:
                await ensure_student(conn, student_id=owner)
                await conn.execute(image_attachments.insert().values(**row))
        return public_image(row)

    async def get(self, owner, image_id):
        if self.engine is None:
            row = self.rows.get(image_id)
            return row if row and row["student_id"] == owner else None
        async with self.engine.connect() as conn:
            row = (await conn.execute(select(image_attachments).where(
                image_attachments.c.student_id == owner, image_attachments.c.id == image_id))).mappings().first()
        return dict(row) if row else None

    async def resolve(self, owner, ids):
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_IMAGES or any(not isinstance(i, str) for i in ids):
            raise ValueError("每条消息最多上传 4 张图片")
        if len(set(ids)) != len(ids):
            raise ValueError("图片附件重复")
        rows = [await self.get(owner, i) for i in ids]
        if not all(rows):
            raise ValueError("图片不存在或无权访问，请重新上传")
        return rows

    async def remove(self, owner, image_id):
        if self.engine is None:
            if await self.get(owner, image_id):
                self.rows.pop(image_id)
        else:
            async with self.engine.begin() as conn:
                await conn.execute(delete(image_attachments).where(
                    image_attachments.c.student_id == owner, image_attachments.c.id == image_id))
