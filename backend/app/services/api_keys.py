"""Provider API 金鑰的遮罩與還原。

金鑰只存在資料庫（``model_configurations.api_keys``，JSON 字串陣列）。設定 API
回給前端的一律是遮罩值；前端不保存、也不隨任務送出明文。需要金鑰的地方
（單檔／批次 WS 派發、批次恢復、Test Connection）在後端從資料庫取。

明文只在設定頁存檔時送進來，其他請求帶明文就拒收（#16 Q8b）。不改成忽略明文：那樣會默默
改用資料庫裡的那把，例如 Test Connection 測到的就不是請求帶的金鑰。

遮罩格式：前 4 碼 + ``********`` + 後 4 碼；長度不足 16 的金鑰整個遮掉。
``*`` 不會出現在真正的金鑰裡，所以前端送回的遮罩值認得出來，不會被當成新金鑰存進去。
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from app.repositories.model_manager_repository import find_provider_settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

MASK_FILL = "********"
_MIN_LENGTH_TO_SHOW_EDGES = 16

PLAINTEXT_API_KEY_MESSAGE = ("請求不能帶明文的 API 金鑰：請先到 Settings 存好金鑰，"
                             "請求不帶金鑰（或只帶設定頁顯示的遮罩值）即可")


class PlaintextApiKeyError(Exception):
    """請求帶了明文金鑰；訊息固定、不含金鑰，可直接顯示給使用者、寫進 log。

    不繼承 ValueError：Test Connection 會把 ValueError 的原文給使用者看，這個例外要另外接。
    """

    def __init__(self) -> None:
        super().__init__(PLAINTEXT_API_KEY_MESSAGE)


def mask_api_key(key: str) -> str:
    if len(key) < _MIN_LENGTH_TO_SHOW_EDGES:
        return MASK_FILL
    return f"{key[:4]}{MASK_FILL}{key[-4:]}"


def is_masked_api_key(value) -> bool:
    return isinstance(value, str) and MASK_FILL in value


def refuse_plaintext_api_keys(*values: Optional[str]) -> None:
    """請求帶的金鑰只能是空白或遮罩值，有明文就丟 :class:`PlaintextApiKeyError`。"""
    for value in values:
        if isinstance(value, str) and value.strip() and not is_masked_api_key(value):
            raise PlaintextApiKeyError()


def parse_stored_api_keys(raw: Optional[str]) -> list[str]:
    """資料庫裡的 JSON 字串 → 金鑰清單（略過空白項）；格式壞掉時回傳空清單。"""
    if not raw:
        return []
    try:
        keys = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"無法解析資料庫中的 API 金鑰，視為未設定: {e}")
        return []
    if not isinstance(keys, list):
        return []
    return [k for k in keys if isinstance(k, str) and k.strip()]


def load_stored_api_keys(db: Session, provider: str) -> list[str]:
    """讀出 provider 存在資料庫的金鑰（名稱不分大小寫）。"""
    row = find_provider_settings(db, provider)
    return parse_stored_api_keys(row.api_keys) if row else []


def merge_api_keys(incoming: list[str], stored: list[str]) -> list[str]:
    """設定存檔時，把前端送回的清單還原成要寫入資料庫的金鑰。

    - 遮罩值：換回資料庫中遮罩相同的原金鑰（依序配對，刪掉其中幾把也對得上）
    - 空字串：略過
    - 其他值：使用者新輸入的金鑰
    - 送來的值裡沒有任何可用的金鑰（只有空字串或對不上的遮罩）→ 保留原金鑰；
      遮罩字串永遠不會寫進資料庫
    - 明確送空陣列 ``[]`` → 清除（使用者把金鑰全部刪掉）
    """
    if not incoming:
        return []
    result = []
    used = set()
    for value in incoming:
        if not isinstance(value, str) or not value.strip():
            continue
        if is_masked_api_key(value):
            for index, key in enumerate(stored):
                if index not in used and mask_api_key(key) == value:
                    used.add(index)
                    result.append(key)
                    break
            continue
        result.append(value)
    return result or list(stored)


def resolve_api_keys(db: Session, provider: str, incoming: list[str]) -> list[str]:
    """Test Connection 用：遮罩值換回原金鑰；沒帶任何金鑰就用資料庫裡的。

    Raises:
        PlaintextApiKeyError: 請求帶了明文金鑰。
    """
    refuse_plaintext_api_keys(*incoming)
    stored = load_stored_api_keys(db, provider)
    return merge_api_keys(incoming, stored) or stored


def resolve_api_key(db: Session, provider: str, provided: Optional[str]) -> str:
    """任務派發／批次恢復要用的單一金鑰。

    缺少或只帶遮罩值 → 用資料庫裡的金鑰（遮罩值對得上哪把就用哪把，否則用第一把）。
    都沒有時回傳空字串。

    Raises:
        PlaintextApiKeyError: 請求帶了明文金鑰。
    """
    refuse_plaintext_api_keys(provided)
    stored = load_stored_api_keys(db, provider)
    if is_masked_api_key(provided):
        for key in stored:
            if mask_api_key(key) == provided:
                return key
    return stored[0] if stored else ""
