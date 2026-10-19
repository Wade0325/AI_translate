"""列出供應商、它們的模型與每個模型的模型能力（唯讀）。

畫面依模型能力停用模型不支援的欄位，不再自己寫死哪個供應商能用哪些欄位。
"""

from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

from app.provider import registry
from app.provider.base import ModelCapabilities

router = APIRouter()


class ListedModel(BaseModel):
    """清單上的一個模型與它的模型能力。"""
    model: str
    capabilities: ModelCapabilities


class ListedProvider(BaseModel):
    """清單上的一個供應商與它的模型；送出任務時，``provider`` 與 ``model`` 照這裡的值帶回。"""
    provider: str
    models: List[ListedModel]


@router.get("/providers", response_model=List[ListedProvider])
def list_providers():
    return [
        ListedProvider(provider=provider, models=[
            ListedModel(model=model, capabilities=capabilities)
            for model, capabilities in models.items()
        ])
        for provider, models in registry.providers().items()
    ]
