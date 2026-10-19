"""依名稱找出供應商轉接器，驗證請求用得了所選的模型（模型屬於這個供應商、支援請求要的
處理方式、吃得下請求裡填了的輸入），並列出每個供應商的模型與模型能力。

供應商名稱不分大小寫（前端送 ``Google``／``Local``，紀錄裡存的也是原樣）。
"""

from __future__ import annotations

import threading
from typing import Dict, Mapping, Optional, Protocol

from app.provider.base import ModelCapabilities, Provider
from app.provider.google.provider import GeminiProvider
from app.provider.local.provider import LocalProvider


class ProviderFactory(Protocol):
    """一個供應商：查模型能力不必建立轉接器；建立的轉接器專給一個任務用。"""

    def capabilities(self) -> Mapping[str, ModelCapabilities]: ...

    def __call__(self, model: str, api_key: str) -> Provider:
        """建立已經準備好的轉接器；還不能轉錄（缺權重、金鑰無效）時拋 ValueError。"""


class UnsupportedModelError(ValueError):
    """所選的模型接不了這個請求：供應商不存在、模型不屬於這個供應商，或模型不支援請求要的
    處理方式（例如批次）；訊息可直接顯示給使用者。"""


class UnsupportedInputError(UnsupportedModelError):
    """請求填了模型不吃的輸入（提示詞、使用者文稿）。"""


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


def providers() -> Dict[str, Mapping[str, ModelCapabilities]]:
    """每個供應商（小寫名稱）的每個模型的模型能力。

    每次都向供應商重新查，不快取：本機的單次長度依顯卡容量而定。
    """
    with _lock:
        factories = list(_factories.items())
    return {name: factory.capabilities() for name, factory in factories}


def model_capabilities(provider: str, model: str) -> ModelCapabilities:
    """這個供應商的這個模型的模型能力。

    Raises:
        UnsupportedModelError: 供應商不存在，或模型不屬於它。
    """
    capabilities = _factory(provider).capabilities().get(model)
    if capabilities is None:
        raise UnsupportedModelError(f"模型 {model} 不屬於供應商 {provider}")
    return capabilities


def check_request(provider: str, model: str, *, prompt: Optional[str] = None,
                  user_text: Optional[str] = None, batch: bool = False) -> ModelCapabilities:
    """驗證這個請求用得了這個供應商的這個模型，回傳模型能力給呼叫端派送任務。

    依序檢查：模型屬於這個供應商；批次請求（``batch``）的模型支援批次；模型吃得下
    請求裡填了的輸入。整批跑不了的原因先報，免得使用者清掉輸入後又被拒一次。

    模型不吃的輸入要明確拒絕，不能送進任務後被默默丟掉。None、空字串與只有空白
    都算沒填，照常送出。

    Raises:
        UnsupportedModelError: 供應商不存在、模型不屬於它，或批次請求的模型不支援批次。
        UnsupportedInputError: 填了這個模型不吃的提示詞或使用者文稿。
    """
    capabilities = model_capabilities(provider, model)
    if batch and not capabilities.supports_batch:
        raise UnsupportedModelError(f"模型 {model} 不支援批次")
    unsupported = [name for name, value, accepted in (
        ("提示詞", prompt, capabilities.accepts_prompt),
        ("使用者文稿", user_text, capabilities.accepts_user_text),
    ) if value and value.strip() and not accepted]
    if unsupported:
        raise UnsupportedInputError(
            f"模型 {model} 不支援{'與'.join(unsupported)}，請清空後再送出")
    return capabilities


def open_provider(provider: str, model: str, api_key: str = "") -> Provider:
    """驗證模型屬於這個供應商，再建立一個任務專用的轉接器。

    Raises:
        UnsupportedModelError: 供應商不存在，或模型不屬於它。
        ValueError: 供應商還不能轉錄（缺 GPU、缺模型權重、API 金鑰無效）。
    """
    model_capabilities(provider, model)
    return _factory(provider)(model, api_key)
