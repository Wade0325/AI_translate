import uuid
from typing import Optional


def coerce_uuid(value) -> Optional[uuid.UUID]:
    """把任意輸入轉為 uuid.UUID；無法解析回傳 None（相容 PostgreSQL 與 SQLite 的查詢）。"""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None
