from pydantic import BaseModel, Field
from typing import List, Optional
from pydantic import ConfigDict


class ProviderConfigRequest(BaseModel):
    """用於接收前端發送的模型介面設定的請求體。"""
    provider: str
    api_keys: List[str] = Field(..., alias="apiKeys")
    model: str = Field(..., alias="model")
    prompt: Optional[str] = None


class ProviderConfigResponse(BaseModel):
    """用於向前端返回模型介面設定的回應體。"""
    provider: str
    api_keys: List[str] = Field(..., serialization_alias="apiKeys")
    model: str = Field(..., serialization_alias="model")
    prompt: Optional[str] = None


class TestProviderRequest(BaseModel):
    """用於測試模型介面連接的請求體。"""
    provider: str
    api_keys: List[str] = Field(..., alias="apiKeys")
    model: str = Field(..., alias="model")


class ModelConfigurationSchema(BaseModel):
    """
    用於在應用程式內部傳遞和操作的模型設定資料結構。
    """
    provider: str
    api_keys: Optional[str] = None
    model: Optional[str] = Field(None, alias="model")
    prompt: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ServiceStatus(BaseModel):
    """
    服務層之間通用的狀態回應模型，用於標準化內部方法的返回結果。
    """
    success: bool
    message: Optional[str] = None


class TestProviderResponse(BaseModel):
    """用於測試模型介面連接的回應體。"""
    success: bool
    message: str
    details: Optional[str] = None
    testedInterface: str
