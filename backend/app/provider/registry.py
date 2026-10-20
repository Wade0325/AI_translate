"""依名稱找出供應商轉接器，驗證請求用得了所選的模型（模型屬於這個供應商、支援請求要的
處理方式、吃得下請求裡填了的輸入），並列出每個供應商的模型與模型能力。

供應商名稱不分大小寫：畫面送的是清單上的小寫名稱（``google``／``local``），改版前的
紀錄存的是 ``Google``／``Local``。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import List, Mapping, Optional, Protocol, Tuple, cast

from app.provider.base import BatchProvider, ModelCapabilities, Provider, ProviderInfo
from app.provider.google.provider import GeminiProvider
from app.provider.local.provider import local_provider


class ProviderFactory(Protocol):
    """一個供應商：查模型能力不必建立轉接器，也不碰顯卡之類的硬體（API 行程與模型能力
    端點都會查）；建立的轉接器專給一個任務用。"""

    info: ProviderInfo

    def capabilities(self) -> Mapping[str, ModelCapabilities]:
        """每個模型的模型能力，依畫面列出的順序；第一個是這個供應商的預設模型。"""

    def __call__(self, model: str, api_key: str) -> Provider:
        """建立已經準備好的轉接器；還不能轉錄（缺權重、金鑰無效）時拋 ValueError。"""


class UnsupportedModelError(ValueError):
    """所選的模型接不了這個請求：供應商不存在、模型不屬於這個供應商，或模型不支援請求要的
    處理方式（例如批次）；訊息可直接顯示給使用者。"""


class UnsupportedInputError(UnsupportedModelError):
    """請求填了模型不吃的輸入（提示詞、使用者文稿）。"""


# 順序就是畫面的順序，第一個是轉錄頁預設的供應商。沿用改版前的預設（Gemini）：和 ADR-0003
# 「預設本機」不一致，沒有 GPU 時預設什麼還在 #11 待決定，決定後改這裡的順序
_factories: dict[str, ProviderFactory] = {"google": GeminiProvider, "local": local_provider}
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


@dataclass(frozen=True)
class ListedModel:
    """清單上的一個模型與它不建立轉接器就知道的模型能力。``single_pass_seconds`` 是上限：
    實際轉錄時，轉接器在執行的機器上可能切得更短（本機依顯卡容量收斂）。"""
    model: str
    label: str
    capabilities: ModelCapabilities


@dataclass(frozen=True)
class ListedProvider:
    """清單上的一個供應商與它的模型；送出任務時，``provider`` 與 ``model`` 照這裡的值帶回。
    第一個模型是這個供應商的預設模型。"""
    provider: str
    label: str
    requires_api_key: bool
    models: Tuple[ListedModel, ...]


def providers() -> List[ListedProvider]:
    """每個供應商（小寫名稱）與它的每個模型，不建立轉接器、不碰顯卡。"""
    with _lock:
        factories = list(_factories.items())
    return [_listed(name, factory.info, factory.capabilities()) for name, factory in factories]


def _listed(name: str, info: ProviderInfo,
            models: Mapping[str, ModelCapabilities]) -> ListedProvider:
    return ListedProvider(
        provider=name,
        label=info.label,
        requires_api_key=info.requires_api_key,
        models=tuple(ListedModel(model=model, label=info.model_labels.get(model, model),
                                 capabilities=capabilities)
                     for model, capabilities in models.items()),
    )


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


def reopen_batch_provider(provider: str, model: str, api_key: str = "") -> BatchProvider:
    """建立轉接器，接手一個已經送出的批次（重啟後復原）。

    模型在送出時驗證過，這裡不再驗證：升級後模型清單拿掉了送出時的模型，
    還在進行中的批次也收得回來。

    Raises:
        UnsupportedModelError: 供應商不存在。
        ValueError: 供應商還不能使用（API 金鑰無效）。
    """
    return cast(BatchProvider, _factory(provider)(model, api_key))
