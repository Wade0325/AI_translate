"""本機模型要匯入的套件：轉錄前先匯入一次，匯入不了時分清楚是沒裝，還是裝了卻載入失敗（#311）。

就緒檢查（:func:`weights.ensure_local_ready`）在顯卡之後、模型權重之前問這裡，所以轉錄頁的就緒提示、
設定頁的「測試」與轉錄前的檢查寫同一個原因；套件載入不了時，就緒提示不會說能轉錄。給使用者看的
句子寫在 weights.py（:class:`weights.LocalNotReady` 的訊息都在那裡寫）。

只看例外類別分不出這兩種：套件裝了、匯入時卻出錯時（例如載入了使用者自己裝的、版本不合的 torchvision，
#301），transformers 5.13.0 的延遲載入把原本的 RuntimeError 包成 ModuleNotFoundError（ImportError 的
子類別；``transformers/utils/import_utils.py`` 第 2307 行接住、第 2393–2395 行重新拋出），以前就被說成
「缺少套件」。這裡改看模組找不找得到（``importlib.util.find_spec``）；找得到卻匯入失敗時，原因取
``raise … from`` 接起來的最裡層的錯誤，和 :func:`app.core.error_codes.describe` 找成因的方式一樣。
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import threading
from dataclasses import dataclass
from types import ModuleType

from app.provider.local import weights
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass(frozen=True)
class Package:
    """本機模型從一個套件匯入的類別。"""
    name: str
    """安裝時的套件名稱，例如 ``moss-transcribe-diarize``；訊息與診斷資訊寫這個。"""
    module: str
    """匯入的頂層模組，例如 ``moss_transcribe_diarize``。"""
    classes: tuple[str, ...]
    """從模組取出的類別。transformers 的類別要取出來才真的匯入（延遲載入）。"""


MOSS = Package("moss-transcribe-diarize", "moss_transcribe_diarize",
               ("MossTranscribeDiarizeForConditionalGeneration", "MossTranscribeDiarizeProcessor"))
QWEN3_ASR = Package("transformers", "transformers", ("Qwen3ASRForConditionalGeneration",))
VIBEVOICE = Package("transformers", "transformers", ("VibeVoiceAsrForConditionalGeneration",))

MODEL_PACKAGES = {
    weights.MOSS_ALIGN: (MOSS,),
    weights.MOSS_QWEN: (MOSS, QWEN3_ASR),
    weights.VIBEVOICE_QWEN: (VIBEVOICE, QWEN3_ASR),
}
"""每個本機模型轉錄時匯入的套件（``moss.py``、``asr.py``），照轉錄時的順序。

只列匯入不了就會讓任務失敗的：強制對齊整段失敗時退回片段時間戳、任務照樣完成
（``asr._align_with_fallback``），所以不列對齊器。
"""


@dataclass(frozen=True)
class PackageUnavailable:
    """本機模型要用的套件匯入不了。``reason`` 是 :class:`weights.LocalNotReady` 的 ``reason`` 之一：

    - ``missing_package``：沒裝這個套件，或沒裝它要用的套件（``missing``）
    - ``package_load_failed``：裝了，匯入時卻出錯（``detail``）
    """
    reason: str
    package: str
    """匯入不了的套件（:attr:`Package.name`）。"""
    missing: str = ""
    """``missing_package`` 時沒裝的那個：套件本身，或它要用的頂層模組（例如 ``av``）。"""
    detail: str = ""
    """``package_load_failed`` 時的原始錯誤（:func:`weights.error_summary`），寫進診斷資訊與日誌。"""


_results: dict[Package, ModuleType | PackageUnavailable] = {}
_lock = threading.Lock()


def problem(model: str | None) -> PackageUnavailable | None:
    """這個模型要用的套件裡，第一個匯入不了的；都匯入得了時是 None。"""
    for package in MODEL_PACKAGES[weights.normalize_model(model)]:
        result = check(package)
        if isinstance(result, PackageUnavailable):
            return result
    return None


def check(package: Package) -> ModuleType | PackageUnavailable:
    """匯入 ``package`` 的模組並取出它的類別：成功時是模組，匯入不了時是原因。

    結果在這個行程裡記住：套件在 app 執行期間不會變（免安裝版的首次佈建在伺服器啟動前就做完），
    每次問都重新匯入一次失敗的套件很慢，日誌也只寫一次。修好之後重新開啟 app 才會再查。
    """
    with _lock:
        if package not in _results:
            _results[package] = _import(package)
        return _results[package]


def _import(package: Package) -> ModuleType | PackageUnavailable:
    if not _installed(package.module):
        return _noted(PackageUnavailable("missing_package", package.name, missing=package.name))
    try:
        module = importlib.import_module(package.module)
        for name in package.classes:
            getattr(module, name)
    except Exception as e:  # 套件壞掉時什麼例外都有可能（DLL 載入失敗是 OSError）
        root = _root_cause(e)
        missing = _missing_module(root)
        if missing:
            return _noted(PackageUnavailable("missing_package", package.name, missing=missing), e)
        return _noted(PackageUnavailable(
            "package_load_failed", package.name, detail=weights.error_summary(root)), e)
    return module


def _installed(module: str) -> bool:
    """找得到這個頂層模組：已經匯入過，或 ``find_spec`` 找得到（只找、不匯入）。"""
    if module in sys.modules:
        return True
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # 模組在 sys.modules 卻沒有 __spec__ 之類的怪狀況：當成有裝
        return True


def _root_cause(error: BaseException) -> BaseException:
    """``raise … from`` 接起來的最裡層的錯誤。不跟 ``__context__``：那可能是處理別的錯誤時剛好發生的。"""
    seen = {id(error)}
    while error.__cause__ is not None and id(error.__cause__) not in seen:
        error = error.__cause__
        seen.add(id(error))
    return error


def _missing_module(error: BaseException) -> str | None:
    """``error`` 是因為某個頂層模組沒裝時，那個模組的名稱；否則是 None。

    模組找得到、只是裡面少了東西（例如 ``No module named 'transformers.models.x'``）不算沒裝。
    """
    if not isinstance(error, ModuleNotFoundError) or not error.name:
        return None
    top = error.name.partition(".")[0]
    return None if _installed(top) else top


def _noted(unavailable: PackageUnavailable,
           error: BaseException | None = None) -> PackageUnavailable:
    """寫進日誌：每個套件只會走到這裡一次（見 :func:`check`）。附上完整的 traceback，日誌檔會把
    使用者家目錄寫成 ``~``（#231）。"""
    if unavailable.reason == "missing_package":
        what = f"沒裝 {unavailable.missing}"
    else:
        what = f"載入失敗（{unavailable.detail}）"
    logger.warning(f"本機轉錄不能用：{unavailable.package} 套件{what}", exc_info=error)
    return unavailable
