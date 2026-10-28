"""依名稱找出供應商轉接器，驗證請求用得了所選的模型（模型屬於這個供應商、支援請求要的
處理方式、吃得下請求裡填了的輸入），並列出每個供應商的模型與模型能力；設定頁的「測試」也
經由這裡請供應商確認現在能不能轉錄。

供應商名稱不分大小寫：畫面送的是清單上的小寫名稱（``google``／``local``），改版前的
紀錄存的是 ``Google``／``Local``。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import List, Mapping, NamedTuple, Optional, Protocol, Tuple, cast

from app.provider.base import (
    BatchProvider,
    ModelCapabilities,
    Provider,
    ProviderInfo,
    UploadNotice,
)
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

    def check_ready(self, model: str, api_key: str) -> str:
        """不轉錄，確認現在能用這個模型轉錄（設定頁的「測試」）；回傳給使用者看的結果。

        和查模型能力不同，這裡會碰硬體或連線；要查什麼由供應商決定：本機查顯卡與這個模型的
        模型權重，Gemini 只用金鑰連一次 API、和模型無關。
        還不能轉錄（缺顯卡、缺模型權重、金鑰無效）時拋 ValueError，訊息可直接顯示給使用者。
        """


class UnsupportedModelError(ValueError):
    """所選的模型接不了這個請求：供應商不存在、模型不屬於這個供應商，或模型不支援請求要的
    處理方式（例如批次）；訊息可直接顯示給使用者。"""


class UnsupportedInputError(UnsupportedModelError):
    """請求填了模型不吃的輸入（提示詞、使用者文稿）。"""


# 順序就是畫面的順序，第一個是轉錄頁預設的供應商：本機（ADR-0003）。沒有 GPU 的電腦也一樣
# 預設本機，轉錄頁說明原因、讓使用者自己改用 Gemini，不自動改選會上傳音檔的供應商（#11 Q1）
_factories: dict[str, ProviderFactory] = {"local": local_provider,
                                          "google": GeminiProvider}
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
    checks_transcribing_machine: bool
    """在執行轉錄的那台機器上轉錄（本機）：轉錄頁選它時先問那台機器能不能轉錄（#11）。"""
    upload_notice: Optional[UploadNotice]
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
        checks_transcribing_machine=info.checks_transcribing_machine,
        upload_notice=info.upload_notice,
        models=tuple(ListedModel(model=model, label=info.model_labels.get(model, model),
                                 capabilities=capabilities)
                     for model, capabilities in models.items()),
    )


def provider_info(provider: str) -> ProviderInfo:
    """這個供應商的 :class:`ProviderInfo`，例如轉錄要不要使用者的 API 金鑰；和供應商清單
    （``GET /providers``）是同一份資訊。

    Raises:
        UnsupportedModelError: 供應商不存在。
    """
    return _factory(provider).info


def check_ready(provider: str, model: str, api_key: str = "") -> str:
    """設定頁的「測試」：驗證模型屬於這個供應商，再請供應商確認現在能用這個模型轉錄，
    回傳給使用者看的結果。

    Raises:
        UnsupportedModelError: 供應商不存在，或模型不屬於它。
        ValueError: 還不能轉錄（缺顯卡、缺模型權重、API 金鑰無效）；訊息可直接顯示給使用者。
    """
    model_capabilities(provider, model)
    return _factory(provider).check_ready(model, api_key)


def model_capabilities(provider: str, model: str) -> ModelCapabilities:
    """這個供應商的這個模型的模型能力。

    Raises:
        UnsupportedModelError: 供應商不存在，或模型不屬於它。
    """
    capabilities = _factory(provider).capabilities().get(model)
    if capabilities is None:
        raise UnsupportedModelError(f"模型 {model} 不屬於供應商 {provider}")
    return capabilities


class CheckedRequest(NamedTuple):
    """驗證過的請求：派送任務與存任務紀錄都用這裡的值。"""
    provider: str
    """供應商清單上的名稱（小寫）。請求裡可能寫成 ``Google``、``GOOGLE``，任務紀錄一律存這個。"""
    capabilities: ModelCapabilities


def check_request(provider: str, model: str, *, prompt: Optional[str] = None,
                  user_text: Optional[str] = None, batch: bool = False,
                  service_tier: Optional[str] = None) -> CheckedRequest:
    """驗證這個請求用得了這個供應商的這個模型，回傳供應商清單上的名稱與模型能力給呼叫端
    派送任務。

    依序檢查：模型屬於這個供應商；批次請求（``batch``）的模型支援批次、Flex 請求
    （``service_tier="flex"``）的模型支援 Flex；模型吃得下請求裡填了的輸入。處理模式跑不了
    的原因先報，免得使用者清掉輸入後又被拒一次。

    模型不吃的輸入要明確拒絕，不能送進任務後被默默丟掉。None、空字串與只有空白
    都算沒填，照常送出。

    Raises:
        UnsupportedModelError: 供應商不存在、模型不屬於它，或模型不支援請求的處理模式。
        UnsupportedInputError: 填了這個模型不吃的提示詞或使用者文稿。
    """
    capabilities = model_capabilities(provider, model)
    if batch and not capabilities.supports_batch:
        raise UnsupportedModelError(f"模型 {model} 不支援批次")
    if service_tier == "flex" and not capabilities.supports_flex:
        raise UnsupportedModelError(f"模型 {model} 不支援 Flex，請改用標準")
    unsupported = [name for name, value, accepted in (
        ("提示詞", prompt, capabilities.accepts_prompt),
        ("使用者文稿", user_text, capabilities.accepts_user_text),
    ) if value and value.strip() and not accepted]
    if unsupported:
        raise UnsupportedInputError(
            f"模型 {model} 不支援{'與'.join(unsupported)}，請清空後再送出")
    return CheckedRequest(provider=provider.lower(), capabilities=capabilities)


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
