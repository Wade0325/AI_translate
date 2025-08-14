from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Any, Dict
from pydantic import ConfigDict


class InterfaceConfigRequest(BaseModel):
    """用於接收前端發送的模型介面設定的請求體。"""
    interfaceName: str
    apiKeys: List[str]
    modelName: str
    prompt: Optional[str] = None


class InterfaceConfigResponse(BaseModel):
    """用於向前端返回模型介面設定的回應體。"""
    interfaceName: str
    apiKeys: List[str]
    modelName: str
    prompt: Optional[str] = None


class TestInterfaceRequest(BaseModel):
    """用於測試模型介面連接的請求體。"""
    interfaceName: str
    apiKeys: List[str]
    modelName: Optional[str] = None


class ModelConfigurationSchema(BaseModel):
    """
    用於在應用程式內部（特別是 Repository 層）傳遞和操作的模型設定資料結構。
    它的欄位名稱使用蛇形命名法 (snake_case) 以匹配資料庫欄位。
    """
    interface_name: str
    api_keys_json: str
    model_name: str
    prompt: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ServiceStatus(BaseModel):
    """
    服務層之間通用的狀態回應模型，用於標準化內部方法的返回結果。
    """
    success: bool
    message: Optional[str] = None


class TestInterfaceResponse(BaseModel):
    """用於測試模型介面連接的回應體。"""
    success: bool
    message: str
    details: Optional[str] = None
    testedInterface: str
