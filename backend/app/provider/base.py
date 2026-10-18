"""供應商接縫：分段轉錄、任務與取消只透過這裡的介面認識供應商。

介面只做三件事：轉錄一段音檔（回傳轉錄結果與用量）、釋放這次用到的遠端與暫存資源、
回報每個模型的模型能力。供應商之間的差異收在各自的轉接器裡：

- :class:`app.provider.local.provider.LocalProvider`：本機
- :class:`app.provider.google.provider.GeminiProvider`：Gemini

依名稱找轉接器、驗證模型屬於供應商，見 :mod:`app.provider.registry`。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping, Optional, Protocol

from app.services.transcription.models import TranscriptionTaskResult

LOCAL_QUEUE = "local_asr"
"""GPU 佇列：Docker 模式由主機端 GPU worker 消化，免安裝模式是序列化的執行緒池。"""
DEFAULT_QUEUE = "celery"


@dataclass(frozen=True)
class ModelCapabilities:
    """一個模型支援哪些輸入與處理方式；依供應商名稱分支的規則都改讀這裡。"""

    single_pass_seconds: float
    """單次能處理的長度（秒）；更長的音檔要分段轉錄。0 = 不分段。"""
    queue: str
    """工作佇列：``LOCAL_QUEUE`` 或 ``DEFAULT_QUEUE``。"""
    can_terminate: bool
    """執行中能不能強制終止；不能的只靠取消旗標合作式停止。"""
    split_retry_on_failure: bool
    """失敗後能不能切段重試；各段說話者編號互相獨立的模型不能。"""
    accepts_prompt: bool
    accepts_user_text: bool
    supports_batch: bool
    pricing: Literal["per_token", "free"]
    remove_silence: bool
    """轉錄前要不要剪掉靜音。"""


@dataclass
class TranscribeRequest:
    """轉錄一段音檔需要的設定；同一個任務的每一段共用一份。"""

    model: str
    prompt: str = ""
    source_lang: Optional[str] = None
    service_tier: Optional[str] = None
    """Gemini 的處理模式：None／"standard" 或 "flex"；其他供應商忽略。"""
    status_callback: Optional[Callable[[str], None]] = None
    cancel_check: Optional[Callable[[], bool]] = None

    def notify(self, text: str) -> None:
        if self.status_callback:
            self.status_callback(text)

    def cancel_requested(self) -> bool:
        return bool(self.cancel_check and self.cancel_check())


class Provider(Protocol):
    """一個任務專用的供應商轉接器；任務結束時呼叫 :meth:`release`。

    建立轉接器時就確認它能轉錄（權重齊備、金鑰可用），不行就拋出明確的錯誤，
    見 :func:`app.provider.registry.open_provider`。
    """

    def capabilities(self) -> Mapping[str, ModelCapabilities]:
        """這個供應商每個模型的模型能力，key 是模型名稱。"""

    def transcribe(self, audio_path: Path, request: TranscribeRequest) -> TranscriptionTaskResult:
        """轉錄一段音檔，時間軸是這段音檔本身。

        使用者取消時拋 :class:`~app.exceptions.TranscriptionCancelledError`；
        其他錯誤由分段轉錄當成這一段失敗處理。
        """

    def release(self) -> None:
        """釋放這次用到的遠端資源與暫存資源；失敗只記 log，不拋例外。"""
