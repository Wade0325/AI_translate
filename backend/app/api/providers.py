"""列出供應商、它們的模型與每個模型的模型能力（唯讀）。

畫面依這份清單列出供應商與模型、依模型能力停用模型不支援的欄位，不再自己寫死。
列的是不建立轉接器就知道的模型能力，不碰顯卡：API 行程沒有顯卡、沒裝 torch 也列得出來。
"""

from typing import List

from fastapi import APIRouter

from app.provider import registry

router = APIRouter()


@router.get("/providers", response_model=List[registry.ListedProvider])
def list_providers():
    return registry.providers()
