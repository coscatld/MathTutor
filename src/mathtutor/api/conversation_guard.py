"""Reject stale routes without exposing another owner's conversation."""
from fastapi import HTTPException


async def require_active(state, owner, cid):
    row = await state.conversations.get(owner, cid)
    if row and (row.get("trashed_at") or row.get("purged_at")):
        raise HTTPException(410, "对话已移入垃圾桶或已删除，请在设置中恢复，或新建对话。")
    return row
