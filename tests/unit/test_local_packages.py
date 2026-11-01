"""本機模型要用的套件匯入不了時，分清楚是沒裝還是裝了卻載入失敗（#311）。

測試範圍：:mod:`app.provider.local.packages` 與經過它的就緒檢查（``weights.ensure_local_ready``）、
本機轉接器、``moss.transcribe`` 和錯誤碼。

套件用寫在暫存資料夾的真模組模擬，照真的匯入流程失敗。``lazylib`` 照 transformers 5.13.0 的延遲載入
（``transformers/utils/import_utils.py`` 第 2307、2393–2395 行）把匯入時的 RuntimeError 包成
ModuleNotFoundError：Wade 的電腦上，使用者自己裝的 torchvision 讓 ``import moss_transcribe_diarize``
這樣失敗，以前就被說成「缺少套件」（PR #306 的實測）。
"""
import importlib
import sys
import textwrap
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.error_codes import ErrorCode, describe
from app.provider.local import packages, weights
from app.provider.local.provider import LocalProvider

TORCHVISION_ERROR = "operator torchvision::nms does not exist"

# transformers 5.13.0 的 _LazyModule.__getattr__：取類別時才匯入模組，失敗時包成 ModuleNotFoundError
LAZYLIB = '''
import importlib


def __getattr__(name):
    try:
        module = importlib.import_module(".modeling", __name__)
        return getattr(module, name)
    except (ModuleNotFoundError, RuntimeError, AttributeError) as e:
        raise ModuleNotFoundError(
            f"Could not import module '{name}'. Are this object's requirements defined correctly?"
        ) from e
'''


@pytest.fixture
def site(tmp_path, monkeypatch):
    """放假套件的資料夾，排在 sys.path 最前面；測試結束後拿掉這次匯入的模組。"""
    folder = tmp_path / "site-packages"
    folder.mkdir()
    monkeypatch.syspath_prepend(str(folder))
    before = set(sys.modules)
    yield folder
    for name in set(sys.modules) - before:
        del sys.modules[name]


def write(site: Path, files: dict[str, str]) -> None:
    for relative, source in files.items():
        path = site / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")
    importlib.invalidate_caches()


def broken_by_torchvision(site: Path) -> packages.Package:
    """裝了、匯入時卻失敗的套件：它用到的 lazylib 在匯入 modeling 時拋 RuntimeError。"""
    write(site, {
        "lazylib/__init__.py": LAZYLIB,
        "lazylib/modeling.py": f"raise RuntimeError({TORCHVISION_ERROR!r})\n",
        "fake_moss/__init__.py": "from lazylib import Processor\n\nclass Model:\n    pass\n",
    })
    return packages.Package("fake-moss", "fake_moss", ("Model",))


@pytest.fixture
def usable_machine(monkeypatch):
    """免安裝模式、看得到能用的顯卡、模型權重都已下載。"""
    monkeypatch.setattr(get_settings(), "app_mode", "standalone")
    monkeypatch.setattr(weights, "detect_gpu", lambda: weights.Gpu("RTX 4080", 16.0, True))
    monkeypatch.setattr(weights, "repo_is_ready", lambda repo: True)


def default_model_uses(monkeypatch, package: packages.Package) -> None:
    monkeypatch.setitem(packages.MODEL_PACKAGES, weights.MOSS_ALIGN, (package,))


def not_ready(model: str = weights.MOSS_ALIGN) -> weights.LocalNotReady:
    with pytest.raises(weights.LocalNotReady) as caught:
        weights.ensure_local_ready(model)
    return caught.value


class TestLoadFailed:
    def test_wrapped_runtime_error_is_not_reported_as_missing(self, site):
        result = packages.check(broken_by_torchvision(site))

        assert result == packages.PackageUnavailable(
            "package_load_failed", "fake-moss", detail=f"RuntimeError: {TORCHVISION_ERROR}")

    def test_readiness_says_it_failed_to_load_and_points_to_diagnostics(
            self, site, monkeypatch, usable_machine):
        default_model_uses(monkeypatch, broken_by_torchvision(site))

        error = not_ready()

        assert error.reason == "package_load_failed"
        assert str(error) == ("fake-moss 套件載入失敗，本機轉錄不能用，"
                              "請回報問題並附上診斷資訊，或改用 Gemini")
        # 原始錯誤和 PyTorch 的一樣只寫進診斷資訊與日誌（#262）
        assert TORCHVISION_ERROR not in str(error)

    def test_a_task_fails_with_its_own_error_code(self, site, monkeypatch, usable_machine):
        default_model_uses(monkeypatch, broken_by_torchvision(site))

        with pytest.raises(weights.LocalNotReady) as caught:
            LocalProvider(weights.MOSS_ALIGN)

        failure = describe(caught.value)
        assert failure.code == ErrorCode.LOCAL_PACKAGE_LOAD_FAILED
        assert failure.detail.startswith("fake-moss 套件載入失敗，")

    def test_missing_class_in_an_installed_package(self, site):
        write(site, {"old_moss/__init__.py": "class Processor:\n    pass\n"})

        result = packages.check(packages.Package("old-moss", "old_moss", ("Processor", "Model")))

        assert isinstance(result, packages.PackageUnavailable)
        assert result.reason == "package_load_failed"
        assert result.detail.startswith("AttributeError: ")

    def test_missing_submodule_of_an_installed_package_is_not_missing_package(self, site):
        # 套件找得到，只是版本不合、少了子模組：說「沒裝」會讓人去裝一個已經裝了的套件
        write(site, {"half_moss/__init__.py": "import half_moss.gone\n"})

        result = packages.check(packages.Package("half-moss", "half_moss", ()))

        assert isinstance(result, packages.PackageUnavailable)
        assert result.reason == "package_load_failed"
        assert result.detail == "ModuleNotFoundError: No module named 'half_moss.gone'"

    def test_follows_only_explicit_causes(self, site):
        # 處理另一個錯誤時剛好發生的（__context__）不是原因：這裡沒裝的是選用的加速套件，
        # 真正讓匯入失敗的是後面的 RuntimeError
        write(site, {"fallback_moss/__init__.py": """
            try:
                import optional_speedup_311
            except ImportError:
                raise RuntimeError("slow path is broken too")
        """})

        result = packages.check(packages.Package("fallback-moss", "fallback_moss", ()))

        assert result == packages.PackageUnavailable(
            "package_load_failed", "fallback-moss", detail="RuntimeError: slow path is broken too")

    def test_paths_in_the_error_keep_only_the_file_name(self, site):
        # 診斷資訊會貼進公開的 Issue，路徑常帶著帳號名稱
        write(site, {"dll_moss/__init__.py": """
            raise OSError(22, "找不到指定的模組。 Error loading "
                          '"C:\\\\Users\\\\王小明\\\\AppData\\\\Roaming\\\\Python\\\\Python311\\\\'
                          'site-packages\\\\torchvision\\\\_C.pyd" or one of its dependencies.')
        """})

        result = packages.check(packages.Package("dll-moss", "dll_moss", ()))

        assert isinstance(result, packages.PackageUnavailable)
        assert "王小明" not in result.detail
        assert '"_C.pyd"' in result.detail


class TestMissing:
    def test_package_not_installed(self, monkeypatch, usable_machine):
        default_model_uses(monkeypatch, packages.Package("no-moss", "no_moss_311", ("Model",)))

        error = not_ready()

        assert error.reason == "missing_package"
        assert str(error) == ("缺少 no-moss 套件，本機轉錄不能用，"
                              "請回報問題並附上診斷資訊，或改用 Gemini")
        assert describe(error).code == ErrorCode.LOCAL_PACKAGE_MISSING

    def test_a_package_it_needs_is_not_installed(self, site, monkeypatch, usable_machine):
        # moss-transcribe-diarize 要用 av：以前的訊息要人補裝「av 與 moss-transcribe-diarize 兩行」
        write(site, {"needs_av/__init__.py": "import no_av_311\n"})
        default_model_uses(monkeypatch, packages.Package("needs-av", "needs_av", ()))

        error = not_ready()

        assert error.reason == "missing_package"
        assert str(error).startswith("缺少 no_av_311 套件（needs-av 要用），本機轉錄不能用，")

    def test_docker_mode_points_to_the_gpu_worker_venv(self, monkeypatch, usable_machine):
        monkeypatch.setattr(get_settings(), "app_mode", "docker")
        default_model_uses(monkeypatch, packages.Package("no-moss", "no_moss_311", ()))

        assert str(not_ready()) == (
            "缺少 no-moss 套件，本機轉錄不能用，請依 backend/requirements-standalone.txt 裝進主機的 "
            "backend\\.venv，再重新啟動 local_worker.bat")


def test_docker_mode_load_failure_points_to_the_gpu_worker_log(site, monkeypatch, usable_machine):
    monkeypatch.setattr(get_settings(), "app_mode", "docker")
    default_model_uses(monkeypatch, broken_by_torchvision(site))

    assert str(not_ready()) == ("fake-moss 套件載入失敗，本機轉錄不能用，原始錯誤寫在主機 GPU worker "
                                "的日誌，修好後重新啟動 local_worker.bat，或改用 Gemini")


class TestOrder:
    def test_gpu_problem_comes_first(self, monkeypatch, usable_machine):
        monkeypatch.setattr(weights, "detect_gpu", lambda: weights.NO_GPU)
        default_model_uses(monkeypatch, packages.Package("no-moss", "no_moss_311", ()))

        assert not_ready().reason == "no_gpu"

    def test_package_problem_comes_before_missing_weights(self, monkeypatch, usable_machine):
        # 套件載入不了時，下載好幾 GB 的模型權重也轉錄不了
        monkeypatch.setattr(weights, "repo_is_ready", lambda repo: False)
        default_model_uses(monkeypatch, packages.Package("no-moss", "no_moss_311", ()))

        assert not_ready().reason == "missing_package"

    def test_importable_packages_are_ready(self, usable_machine):
        # conftest 把每個模型要用的套件記成匯入得了
        assert weights.ensure_local_ready(weights.MOSS_ALIGN).name == "RTX 4080"

    def test_only_the_selected_models_packages(self, monkeypatch, usable_machine):
        missing = packages.Package("no-vibevoice", "no_vibevoice_311", ())
        monkeypatch.setitem(packages.MODEL_PACKAGES, weights.VIBEVOICE_QWEN, (missing,))

        weights.ensure_local_ready(weights.MOSS_ALIGN)
        assert not_ready(weights.VIBEVOICE_QWEN).reason == "missing_package"


class TestRemembered:
    def test_imports_once_and_logs_once(self, site, app_log):
        write(site, {
            "counted_moss/__init__.py": """
                import builtins
                builtins.counted_moss_imports = getattr(builtins, "counted_moss_imports", 0) + 1
                raise RuntimeError("broken")
            """,
        })
        package = packages.Package("counted-moss", "counted_moss", ())

        first, second = packages.check(package), packages.check(package)

        import builtins
        assert first is second
        assert builtins.counted_moss_imports == 1
        del builtins.counted_moss_imports
        logged = [entry for entry in app_log if "counted-moss" in entry]
        assert len(logged) == 1
        # 日誌附上完整的 traceback：知道是從哪個檔案載入的
        assert "本機轉錄不能用：counted-moss 套件載入失敗（RuntimeError: broken）" in logged[0]
        assert "Traceback" in logged[0]

    def test_importable_package_returns_the_module(self, site):
        write(site, {"good_moss/__init__.py": "class Model:\n    pass\n"})

        module = packages.check(packages.Package("good-moss", "good_moss", ("Model",)))

        assert module is sys.modules["good_moss"]


def test_moss_transcribe_says_which_one(site, monkeypatch, tmp_path):
    # 直接呼叫推論的地方（例如評測工具）不經過就緒檢查，也要說對原因
    from app.provider.local import moss

    monkeypatch.setattr(get_settings(), "app_mode", "standalone")
    monkeypatch.setattr(packages, "MOSS", broken_by_torchvision(site))

    with pytest.raises(weights.LocalNotReady) as caught:
        moss.transcribe(tmp_path / "audio.wav")

    assert caught.value.reason == "package_load_failed"
    assert "缺少" not in str(caught.value)


def test_every_local_model_lists_its_packages():
    assert set(packages.MODEL_PACKAGES) == set(weights.MODEL_REPOS)
    assert all(packages.MODEL_PACKAGES[model] for model in weights.MODEL_REPOS)


def test_moss_models_import_the_moss_package():
    for model in (weights.MOSS_ALIGN, weights.MOSS_QWEN):
        assert packages.MODEL_PACKAGES[model][0] == packages.MOSS
    assert packages.MOSS.module == "moss_transcribe_diarize"
