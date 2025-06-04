# backend/app/models/model_settings_model.py
from pydantic import BaseModel, Field
from typing import List, Optional


class InterfaceConfigRequest(BaseModel):
    interfaceName: str
    apiKeys: List[str] = Field(default_factory=list)
    modelName: str
    prompt: Optional[str] = None


class InterfaceConfigResponse(BaseModel):
    interfaceName: str
    apiKeys: List[str]
    modelName: str
    prompt: Optional[str] = None

# 這個模型可以代表從資料庫讀取或寫入資料庫時，更接近資料庫結構的數據形態。
# 在 Repository 層內部使用，或者作為 Service 層與 Repository 層之間的數據傳輸對象 (DTO)。


class ModelConfigurationSchema(BaseModel):
    interface_name: str
    api_keys_json: str  # 在資料庫中儲存的是 JSON 字串
    model_name: str
    prompt: Optional[str] = None
    # last_updated 通常由資料庫自動處理或在儲存時設置

    class Config:
        from_attributes = True
