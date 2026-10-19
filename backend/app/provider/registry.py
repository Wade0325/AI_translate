"""依名稱找出供應商轉接器，並驗證模型屬於這個供應商。

供應商名稱不分大小寫（前端送 ``Google``／``Local``，紀錄裡存的也是原樣）。
"""

from __future__ import annotations

import threading
from typing import Mapping, Optional, Protocol, cast

from app.provider.base import BatchProvider, ModelCapabilities, Provider
from app.provider.google.provider import GeminiProvider
from app.provider.local.provider import LocalProvider


class ProviderFactory(Protocol):
    """一個供應商：查模型能力不必建立轉接器；建立的轉接器專給一個任務用。"""

    def capabilities(self) -> Mapping[str, ModelCapabilities]: ...

    def __call__(self, model: str, api_key: str) -> Provider:
        """建立已經準備好的轉接器；還不能轉錄（缺權重、金鑰無效）時拋 ValueError。"""


class UnsupportedModelError(ValueError):
    """供應商不存在，或模型不屬於這個供應商；訊息可直接顯示給使用者。"""


_factories: dict[str, ProviderFactory] = {"google": GeminiProvider, "local": LocalProvider}
_lock = threading.Lock()


def register(name: str, factory: Optional[ProviderFactory]) -> Optional[ProviderFactory]:
    """換上（None 代表移除）某個名稱的供應商，回傳原本的；測試用來換上假供應商。"""
    key = name.lower()
    with _lock:
        previous = _factories.get(key)
        if factory is None:
            _factories.pop(key, None)
        else:
            _factories[key] = factory
    return previous


def _factory(provider: str) -> ProviderFactory:
    with _lock:
        factory = _factories.get((provider or "").lower())
    if factory is None:
        raise UnsupportedModelError(f"不支援的供應商：{provider}")
    return factory


def model_capabilities(provider: str, model: str) -> ModelCapabilities:
    """這個供應商的這個模型的模型能力。

    Raises:
        UnsupportedModelError: 供應商不存在，或模型不屬於它。
    """
    capabilities = _factory(provider).capabilities().get(model)
    if capabilities is None:
        raise UnsupportedModelError(f"模型 {model} 不屬於供應商 {provider}")
    return capabilities


def open_provider(provider: str, model: str, api_key: str = "") -> Provider:
    """驗證模型屬於這個供應商，再建立一個任務專用的轉接器。

    Raises:
        UnsupportedModelError: 供應商不存在，或模型不屬於它。
        ValueError: 供應商還不能轉錄（缺 GPU、缺模型權重、API 金鑰無效）。
    """
    model_capabilities(provider, model)
    return _factory(provider)(model, api_key)


def open_batch_provider(provider: str, model: str, api_key: str = "") -> BatchProvider:
    """驗證模型屬於這個供應商而且支援批次，再建立一個批次專用的轉接器。

    Raises:
        UnsupportedModelError: 供應商不存在、模型不屬於它，或模型不支援批次。
        ValueError: 供應商還不能轉錄（API 金鑰無效）。
    """
    if not model_capabilities(provider, model).supports_batch:
        raise UnsupportedModelError(f"模型 {model} 不支援批次")
    # 模型能力標明支援批次的供應商，轉接器都實作 BatchProvider
    return cast(BatchProvider, _factory(provider)(model, api_key))
