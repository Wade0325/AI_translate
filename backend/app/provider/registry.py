"""依名稱找出供應商轉接器，並驗證模型屬於這個供應商。

供應商名稱不分大小寫（前端送 ``Google``／``Local``，紀錄裡存的也是原樣）。
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from app.provider.base import ModelCapabilities, Provider

ProviderFactory = Callable[[str], Provider]
"""API 金鑰 → 一個任務專用的轉接器。建立時不連線、不檢查權重。"""


class UnsupportedModelError(ValueError):
    """供應商不存在，或模型不屬於這個供應商；訊息可直接顯示給使用者。"""


def _gemini(api_key: str) -> Provider:
    from app.provider.google.provider import GeminiProvider
    return GeminiProvider(api_key)


def _local(api_key: str) -> Provider:
    from app.provider.local.provider import LocalProvider
    return LocalProvider()


_factories: dict[str, ProviderFactory] = {"google": _gemini, "local": _local}
_lock = threading.Lock()


def register(name: str, factory: Optional[ProviderFactory]) -> Optional[ProviderFactory]:
    """換上（None 代表移除）某個名稱的轉接器，回傳原本的；測試用來換上假供應商。"""
    key = name.lower()
    with _lock:
        previous = _factories.get(key)
        if factory is None:
            _factories.pop(key, None)
        else:
            _factories[key] = factory
    return previous


def open_provider(provider: str, model: str, api_key: str = "") -> tuple[Provider, ModelCapabilities]:
    """建立轉接器並回傳這個模型的模型能力；模型不屬於這個供應商就拒絕。

    Raises:
        UnsupportedModelError: 供應商不存在，或模型不屬於它。
    """
    with _lock:
        factory = _factories.get((provider or "").lower())
    if factory is None:
        raise UnsupportedModelError(f"不支援的供應商：{provider}")
    adapter = factory(api_key)
    capabilities = adapter.capabilities().get(model)
    if capabilities is None:
        raise UnsupportedModelError(f"模型 {model} 不屬於供應商 {provider}")
    return adapter, capabilities


def model_capabilities(provider: str, model: str) -> ModelCapabilities:
    """這個供應商的這個模型的模型能力；不符時同 :func:`open_provider` 拒絕。"""
    return open_provider(provider, model)[1]
