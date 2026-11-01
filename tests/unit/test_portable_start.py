"""免安裝版的手動啟動（start.bat → bin\\start.py）與 README.txt（#267），內容在 tools/portable/。

start.bat 是防毒軟體攔下 AI_Translate.exe 時的手動啟動，只用隨包的 Python 執行 start.py；佈建、啟動
與訊息都在 start.py。它要和啟動器（tools/launcher.cs）做一樣的事：設一樣的環境變數，用一樣的指令
佈建與啟動。兩邊各寫一份（Python 與 C#），這裡檢查沒有分岔，並測 start.py 的每一條路徑。

start.bat 只能是 ASCII：cmd 遇到多位元組字元會算錯下一行的位置，把後面的字當成指令執行（#267 在
Windows 10 上實測到）。發布包裡的換行、BOM 與 ASCII 由 CI 檢查 zip（tools/portable_zip.py）。
"""
import io
import os
import re
import subprocess
import sys
import types
from pathlib import Path, PureWindowsPath

import pytest

from app.core.config import Settings
from tools import portable_zip
from tools.portable import start

ROOT = Path(__file__).resolve().parents[2]
PORTABLE = ROOT / "tools" / "portable"

# 啟動器設給伺服器的環境變數。路徑以發布包的根目錄為基準
SERVER_ENV = {
    "APP_MODE": "standalone",
    "AIT_DATA_DIR": "data",
    "AIT_FFMPEG_DIR": "bin",
    "AIT_STATIC_DIR": r"frontend\dist",
    "HF_HOME": r"data\models\hf_cache",
    "PYTHONIOENCODING": "utf-8",
}
PKG = Path("/pkg")  # start.py 的函式拿到的發布包根目錄（測試用的假路徑）


def _launcher() -> str:
    return (ROOT / "tools" / "launcher.cs").read_text(encoding="utf-8-sig")


def _cs_value(expr: str, names: dict[str, str]) -> str:
    """launcher.cs 裡的字串常數、變數或 Path.Combine(...)，算成以發布包根目錄為基準的路徑。"""
    expr = expr.strip()
    literal = re.fullmatch(r'"([^"]*)"', expr)
    if literal:
        return literal.group(1)
    if expr in names:
        return names[expr]
    combine = re.fullmatch(r"Path\.Combine\((.*)\)", expr)
    if combine:
        parts = [_cs_value(arg, names) for arg in combine.group(1).split(",")]
        return "\\".join(part for part in parts if part)
    raise AssertionError(f"看不懂 tools/launcher.cs 的 {expr}：啟動器改了寫法時，這個測試跟著改")


def _launcher_env() -> dict[str, str]:
    text = _launcher()
    data_dir = re.search(r"string dataDir = (.+?);", text)
    assert data_dir, "tools/launcher.cs 裡找不到 dataDir"
    names = {"root": "", "dataDir": _cs_value(data_dir.group(1), {"root": ""})}
    assignments = re.findall(r'EnvironmentVariables\["(\w+)"\]\s*=\s*(.+?);', text)
    assert assignments, "tools/launcher.cs 裡找不到設給伺服器的環境變數"
    return {name: _cs_value(expr, names) for name, expr in assignments}


def _relative(value: str) -> str:
    """start.py 給的值：PKG 底下的路徑改寫成以發布包根目錄為基準、用 \\ 的寫法，其他照原樣。"""
    path = Path(value)
    if path.is_relative_to(PKG):
        return str(PureWindowsPath(*path.relative_to(PKG).parts))
    return value


def _package(tmp_path: Path, *, provisioned: bool = False, skip: tuple[str, ...] = ()) -> Path:
    """在 tmp_path 做一個解壓後的發布包：start.py 啟動前檢查的檔案都在（skip 裡的除外）。"""
    for rel in ("runtime/python.exe", "bin/uv.exe", "backend/main.py",
                "backend/requirements-standalone.txt"):
        if rel not in skip:
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_bytes(b"x")
    if provisioned:
        start.provisioned_marker(tmp_path).write_text("done", encoding="utf-8")
    return tmp_path


class _Calls:
    """假的 run／serve：記下收到什麼，回傳指定的結束代碼。"""

    def __init__(self, code: int = 0):
        self.code = code
        self.calls: list[tuple] = []

    def __call__(self, *args, **kwargs) -> int:
        self.calls.append((args, kwargs))
        return self.code


@pytest.fixture(autouse=True)
def _empty_system32(monkeypatch, tmp_path_factory):
    """System32 預設是空的資料夾（沒有 NVIDIA 驅動，不提示 VC++）：不看執行測試那台電腦的 System32。"""
    folder = tmp_path_factory.mktemp("System32")
    monkeypatch.setattr(start, "system_folder", lambda: folder)


class TestMatchesLauncher:
    def test_launcher_sets_these_variables(self):
        # 啟動器多設或改了一個變數時這裡紅燈：start.py 與 SERVER_ENV 一起改
        assert _launcher_env() == SERVER_ENV

    def test_start_py_sets_the_same_variables(self):
        assert {name: _relative(value) for name, value in start.server_env(PKG).items()} == SERVER_ENV

    def test_hf_home_is_where_config_puts_it_without_the_variable(self, monkeypatch):
        # 沒設 HF_HOME 時，免安裝模式的預設也在資料目錄的同一個位置（config.py 的 _default_hf_home）。
        # 別的測試 import 過 provider/local/weights.py 時，它已經替這個行程設了 HF_HOME
        monkeypatch.delenv("HF_HOME", raising=False)
        data = Path("X:/pkg/data")
        default = Path(Settings(_env_file=None, app_mode="standalone", data_dir=str(data)).hf_home)
        set_by_launcher = PureWindowsPath(SERVER_ENV["HF_HOME"]).relative_to(SERVER_ENV["AIT_DATA_DIR"])

        assert default.relative_to(data).parts == set_by_launcher.parts

    def test_same_server_command(self):
        launcher = _launcher()
        # 從第一個參數取到埠號之前：連 -m 前面的 python 旗標（-s，#301）一起比
        args = re.search(r'"((?:-\S+ )*-m uvicorn [^"]*)\{0\}"', launcher)
        assert args, "tools/launcher.cs 裡找不到啟動 uvicorn 的參數"
        assert "psi.WorkingDirectory = backend;" in launcher

        command = start.server_command(PKG, 8123)
        assert _relative(command[0]) == r"runtime\python.exe"
        assert command[1:] == [*args.group(1).split(), "8123"]

    def test_same_provisioning(self):
        # 佈建的指令與完成標記相同：用哪一個啟動，另一個都認得已經佈建好
        launcher = _launcher()
        assert r'"pip install --python \"{0}\" --target \"{1}\" -r \"{2}\""' in launcher
        assert 'Path.Combine(root, "runtime", "Lib", "site-packages")' in launcher
        assert 'Path.Combine(root, "backend", "requirements-standalone.txt")' in launcher
        assert 'Path.Combine(root, "runtime", ".provisioned")' in launcher
        assert "psi.WorkingDirectory = root;" in launcher

        assert [_relative(part) for part in start.provision_command(PKG)] == [
            r"bin\uv.exe", "pip", "install", "--python", r"runtime\python.exe",
            "--target", r"runtime\Lib\site-packages",
            "-r", r"backend\requirements-standalone.txt"]
        assert _relative(str(start.provisioned_marker(PKG))) == r"runtime\.provisioned"

    def test_same_static_libraries_are_removed(self):
        # 首次佈建成功後與已佈建時都刪 torch\lib 的 .lib（#305），副檔名不分大小寫
        launcher = _launcher()
        assert 'Path.Combine(root, "runtime", "Lib", "site-packages", "torch", "lib")' in launcher
        assert '".lib", StringComparison.OrdinalIgnoreCase' in launcher
        assert launcher.count("RemoveStaticLibraries(root);") == 2

        assert _relative(str(start.torch_lib(PKG))) == r"runtime\Lib\site-packages\torch\lib"


class TestMain:
    def test_first_run_provisions_then_starts_the_server(self, tmp_path, capsys):
        root = _package(tmp_path)
        run, serve = _Calls(), _Calls()

        assert start.main([], root, run=run, serve=serve) == 0

        assert run.calls == [((start.provision_command(root),), {"cwd": root})]
        assert start.provisioned_marker(root).exists()
        assert serve.calls == [((root, 8000), {})]
        out = capsys.readouterr().out
        assert "首次啟動：正在下載執行環境" in out
        assert "執行環境佈建完成" in out
        assert "用瀏覽器開啟 http://127.0.0.1:8000" in out

    def test_provisioned_package_skips_uv(self, tmp_path):
        root = _package(tmp_path, provisioned=True)
        run, serve = _Calls(), _Calls()

        assert start.main([], root, run=run, serve=serve) == 0

        assert run.calls == []
        assert len(serve.calls) == 1

    def test_failed_provisioning_stops_without_the_marker(self, tmp_path, capsys):
        root = _package(tmp_path)
        run, serve = _Calls(code=2), _Calls()

        assert start.main([], root, run=run, serve=serve) == 1

        assert not start.provisioned_marker(root).exists()
        assert serve.calls == []
        out = capsys.readouterr().out
        assert "執行環境佈建失敗（結束代碼 2" in out
        assert "重新執行 start.bat 即可續傳" in out
        assert "按任意鍵關閉" in out

    @pytest.mark.parametrize("code, shown", [
        (1, "1"),
        (3221225477, "0xC0000005"),  # Windows 回報程式當掉的結束代碼
        (-1, "0xFFFFFFFF"),
    ])
    def test_any_nonzero_server_exit_is_reported(self, tmp_path, capsys, code, shown):
        # 雙擊執行時視窗要停下來：負數或很大的結束代碼也一樣（cmd 的 if errorlevel 1 會漏掉負數）
        root = _package(tmp_path, provisioned=True)

        assert start.main([], root, run=_Calls(), serve=_Calls(code=code)) == 1

        out = capsys.readouterr().out
        assert f"伺服器已停止（結束代碼 {shown}）" in out
        assert "start.bat 8001 換一個埠" in out
        assert "按任意鍵關閉" in out

    def test_port_argument(self, tmp_path, capsys):
        root = _package(tmp_path, provisioned=True)
        serve = _Calls()

        assert start.main(["8267"], root, run=_Calls(), serve=serve) == 0

        assert serve.calls == [((root, 8267), {})]
        assert "http://127.0.0.1:8267" in capsys.readouterr().out

    @pytest.mark.parametrize("arg", ["abc", "0", "65536"])
    def test_bad_port_stops_before_anything_runs(self, tmp_path, capsys, arg):
        root = _package(tmp_path)
        run, serve = _Calls(), _Calls()

        assert start.main([arg], root, run=run, serve=serve) == 1

        assert run.calls == serve.calls == []
        assert f"收到的是：{arg}" in capsys.readouterr().out

    def test_incomplete_package_says_what_is_missing(self, tmp_path, capsys):
        root = _package(tmp_path, skip=("bin/uv.exe",))
        run, serve = _Calls(), _Calls()

        assert start.main([], root, run=run, serve=serve) == 1

        assert run.calls == serve.calls == []
        out = capsys.readouterr().out
        assert str(Path("bin") / "uv.exe") in out
        assert "請確認 zip 已完整解壓" in out

    def test_unexpected_error_is_shown_before_the_window_closes(self, monkeypatch, capsys):
        def boom(argv):
            raise PermissionError("拒絕存取")
        monkeypatch.setattr(start, "main", boom)

        assert start.entry([]) == 1

        captured = capsys.readouterr()
        assert "PermissionError: 拒絕存取" in captured.err
        assert "按任意鍵關閉" in captured.out


MISSING_VC = "這台電腦沒有 Microsoft Visual C++ 可轉散發套件"


def _system32(tmp_path: Path, *dlls: str, nvidia: bool = True) -> Path:
    """假的 System32：有 NVIDIA 驅動（nvcuda.dll）與 dlls 裡的檔案。"""
    folder = tmp_path / "System32"
    folder.mkdir(exist_ok=True)
    for name in (("nvcuda.dll",) if nvidia else ()) + dlls:
        (folder / name).write_bytes(b"")
    return folder


class TestVcRuntime:
    """有 NVIDIA 驅動、卻沒裝 Microsoft Visual C++ 可轉散發套件（或太舊）時，佈建之前先提示，不擋啟動，
    和啟動器相同（#304）。清單、版本、網址與原因和啟動器、weights.py 相同，在 test_vc_runtime.py 比對。"""

    def test_missing_runtime(self, tmp_path):
        assert start.vc_runtime_problem(_system32(tmp_path), lambda path: None) == MISSING_VC

    @pytest.mark.parametrize("dll", start.VC_RUNTIME_DLLS)
    def test_each_dll_is_required(self, tmp_path, dll):
        others = [name for name in start.VC_RUNTIME_DLLS if name != dll]

        assert start.vc_runtime_problem(_system32(tmp_path, *others), lambda path: (14, 44)) == MISSING_VC

    def test_old_runtime_says_both_versions(self, tmp_path):
        system, read = _system32(tmp_path, *start.VC_RUNTIME_DLLS), []

        problem = start.vc_runtime_problem(system, lambda path: read.append(path.name) or (14, 29))

        assert problem == ("這台電腦的 Microsoft Visual C++ 可轉散發套件太舊"
                           "（目前 14.29，需要 14.38 以上）")
        assert read == ["msvcp140.dll"]

    @pytest.mark.parametrize("version", [(14, 38), (14, 44), (15, 0), None])
    def test_recent_or_unreadable_runtime_is_fine(self, tmp_path, version):
        system = _system32(tmp_path, *start.VC_RUNTIME_DLLS)

        assert start.vc_runtime_problem(system, lambda path: version) is None

    def test_without_nvidia_driver_nothing_is_said(self, tmp_path):
        # 本機轉錄本來就不能用，轉錄頁會先說顯卡
        assert start.vc_runtime_problem(_system32(tmp_path, nvidia=False)) is None

    def test_windows_checks_system32(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(start, "system_folder", lambda: _system32(tmp_path))

        assert start.check_vc_runtime() == MISSING_VC

    def test_an_error_while_checking_does_not_stop_the_start(self, tmp_path, monkeypatch):
        # 只是提示：讀不到 System32 或版本時不提示，照樣佈建與啟動（和啟動器相同）
        def denied(path: Path, version=None):
            raise PermissionError("拒絕存取")
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(start, "vc_runtime_problem", denied)

        assert start.check_vc_runtime() is None

    def test_other_platforms_do_not_check(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(start, "system_folder", lambda: _system32(tmp_path))

        assert start.check_vc_runtime() is None
        assert start.file_version(tmp_path / "System32" / "msvcp140.dll") is None

    def test_first_run_warns_before_provisioning_and_again_after(self, tmp_path, capsys):
        root = _package(tmp_path)
        serve = _Calls()

        assert start.main([], root, run=_Calls(), serve=serve, vc_problem=lambda: MISSING_VC) == 0

        out = capsys.readouterr().out
        warning = f"{MISSING_VC}，本機轉錄不能用。"
        # 佈建前說一次；佈建完還沒裝，再說一次（uv 的輸出把前一次推上去了）
        assert out.count(warning) == 2
        assert (out.index(warning) < out.index("首次啟動：正在下載執行環境")
                < out.rindex(warning) < out.index("正在啟動 AI_Translate 伺服器"))
        assert f"請下載安裝（需要系統管理員權限）：{start.VC_REDIST_URL}" in out
        assert "再執行一次 start.bat" in out
        assert len(serve.calls) == 1  # 不擋啟動：Gemini 照樣能用

    def test_installed_while_provisioning(self, tmp_path, capsys):
        root = _package(tmp_path)
        answers = iter([MISSING_VC, None])

        assert start.main([], root, run=_Calls(), serve=_Calls(),
                          vc_problem=lambda: next(answers)) == 0

        out = capsys.readouterr().out
        assert out.count("本機轉錄不能用") == 1
        assert (out.index("執行環境佈建完成")
                < out.index("已經裝好 Microsoft Visual C++ 可轉散發套件")
                < out.index("正在啟動 AI_Translate 伺服器"))

    def test_provisioned_package_warns_once(self, tmp_path, capsys):
        root = _package(tmp_path, provisioned=True)
        checked = []

        assert start.main([], root, run=_Calls(), serve=_Calls(),
                          vc_problem=lambda: checked.append(1) or MISSING_VC) == 0

        out = capsys.readouterr().out
        assert out.count("本機轉錄不能用") == 1
        assert "已經裝好" not in out
        assert checked == [1]

    def test_failed_provisioning_is_not_rechecked(self, tmp_path, capsys):
        root = _package(tmp_path)
        checked = []

        assert start.main([], root, run=_Calls(code=2), serve=_Calls(),
                          vc_problem=lambda: checked.append(1) or MISSING_VC) == 1

        assert checked == [1]
        assert capsys.readouterr().out.count("本機轉錄不能用") == 1

    def test_nothing_is_said_when_installed(self, tmp_path, capsys):
        root = _package(tmp_path)

        assert start.main([], root, run=_Calls(), serve=_Calls(), vc_problem=lambda: None) == 0

        assert "可轉散發套件" not in capsys.readouterr().out

    def test_running_instance_is_not_checked(self, tmp_path):
        # 和啟動器相同：已經有實例在執行時只顯示網址，提示交給那一個
        root = _package(tmp_path)
        checked = []

        start.main([], root, run=_Calls(), serve=_Calls(), acquire=lambda root_: None,
                   probe=lambda url: False, vc_problem=lambda: checked.append(1))

        assert checked == []


# 首次佈建裝好的樣子：torch\lib 有 .lib 與 DLL，numpy 也有一個 .lib（#239 實測的檔名）
TORCH_LIB_FILES = ("dnnl.lib", "KINETO.LIB", "torch_cpu.lib", "torch_cpu.dll", "c10.dll")
KEPT = {"torch_cpu.dll", "c10.dll"}


def _install_torch(root: Path) -> tuple[Path, Path]:
    torch_lib = start.torch_lib(root)
    torch_lib.mkdir(parents=True)
    for name in TORCH_LIB_FILES:
        (torch_lib / name).write_bytes(b"x")
    other = root / "runtime" / "Lib" / "site-packages" / "numpy" / "_core" / "lib" / "npymath.lib"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"x")
    return torch_lib, other


class TestStaticLibraries:
    """和啟動器一樣刪掉 torch\\lib 的 .lib（#305）：執行時用不到，約 2.8 GB。"""

    def test_first_run_removes_them_after_provisioning(self, tmp_path):
        root = _package(tmp_path)
        torch_lib, other = _install_torch(root)

        assert start.main([], root, run=_Calls(), serve=_Calls()) == 0

        assert {path.name for path in torch_lib.iterdir()} == KEPT
        assert other.exists()  # 只刪 torch 的
        assert start.provisioned_marker(root).exists()

    def test_provisioned_package_removes_what_is_left(self, tmp_path):
        root = _package(tmp_path, provisioned=True)
        torch_lib, _ = _install_torch(root)
        run = _Calls()

        assert start.main([], root, run=run, serve=_Calls()) == 0

        assert {path.name for path in torch_lib.iterdir()} == KEPT
        assert run.calls == []

    def test_failed_provisioning_leaves_them(self, tmp_path):
        root = _package(tmp_path)
        torch_lib, _ = _install_torch(root)

        assert start.main([], root, run=_Calls(code=2), serve=_Calls()) == 1

        assert {path.name for path in torch_lib.iterdir()} == set(TORCH_LIB_FILES)

    def test_one_that_cannot_be_removed_does_not_stop_the_start(self, tmp_path, monkeypatch, capsys):
        root = _package(tmp_path)
        torch_lib, _ = _install_torch(root)
        unlink = Path.unlink

        def locked(path: Path, missing_ok: bool = False) -> None:
            if path.name == "dnnl.lib":
                raise PermissionError(13, "檔案被其他程式占用")
            unlink(path, missing_ok)
        monkeypatch.setattr(Path, "unlink", locked)
        serve = _Calls()

        assert start.main([], root, run=_Calls(), serve=serve) == 0

        assert {path.name for path in torch_lib.iterdir()} == KEPT | {"dnnl.lib"}
        assert start.provisioned_marker(root).exists()
        assert len(serve.calls) == 1
        out = capsys.readouterr().out
        assert "torch\\lib 裡有 1 個用不到的 .lib 刪不掉，不影響使用，下次啟動再試：" in out
        assert "dnnl.lib（PermissionError：檔案被其他程式占用）" in out

    def test_package_without_torch_starts_as_usual(self, tmp_path, capsys):
        root = _package(tmp_path, provisioned=True)

        assert start.main([], root, run=_Calls(), serve=_Calls()) == 0

        assert "torch\\lib" not in capsys.readouterr().out


class _Instance:
    """假的單一實例（start.acquire_instance）：running=True 表示同一個資料夾已經有實例在執行。"""

    def __init__(self, running: bool = False):
        self.held = running
        self.released = 0

    def __call__(self, root: Path):
        if self.held:
            return None
        self.held = True

        def release() -> None:
            self.held = False
            self.released += 1

        return release


class TestSingleInstance:
    """同一個資料夾的 AI_Translate.exe 與 start.bat 合起來只跑一個伺服器：伺服器啟動時會先把「處理中」
    的任務記成失敗才綁埠，第二個實例綁不到埠也已經記了（#267 實測）。和啟動器真的互相擋住，
    在 tests/integration/test_launcher.py 的 Windows 腿測。"""

    def test_running_instance_is_shown_instead_of_starting_another(self, tmp_path, capsys):
        root = _package(tmp_path)  # 還沒佈建也一樣：佈建交給已在執行的那一個
        start.write_url_file(root, "http://127.0.0.1:8001")
        run, serve, probed = _Calls(), _Calls(), []

        code = start.main([], root, run=run, serve=serve, acquire=_Instance(running=True),
                          probe=lambda url: probed.append(url) or True)

        assert code == 0
        assert run.calls == serve.calls == []
        assert probed == ["http://127.0.0.1:8001"]
        out = capsys.readouterr().out
        assert "AI_Translate 已經在執行，不會再啟動第二個" in out
        assert "請用瀏覽器開啟 http://127.0.0.1:8001" in out
        assert "按任意鍵關閉" in out
        assert start.url_file(root).exists()  # 是那個實例的，不刪

    @pytest.mark.parametrize("url_text, responds", [
        (None, True),                             # 還在首次佈建：還沒寫網址
        ("http://127.0.0.1:8001", False),         # 已經寫了網址，伺服器還沒就緒
        ("http://example.com:8001", True),        # 不是啟動器寫的格式，不顯示
        ("http://127.0.0.1:70000", True),
    ])
    def test_instance_still_starting_points_to_its_window(self, tmp_path, capsys, url_text, responds):
        root = _package(tmp_path, provisioned=True)
        if url_text is not None:
            start.write_url_file(root, url_text)
        serve = _Calls()

        code = start.main([], root, run=_Calls(), serve=serve, acquire=_Instance(running=True),
                          probe=lambda url: responds)

        assert code == 0
        assert serve.calls == []
        out = capsys.readouterr().out
        assert "AI_Translate 已經在另一個視窗啟動中，不會再啟動第二個" in out
        assert "example.com" not in out and "70000" not in out

    def test_url_is_written_while_serving_and_removed_after(self, tmp_path):
        root = _package(tmp_path)
        instance, seen = _Instance(), []

        def serve(root_: Path, port: int) -> int:
            seen.append((instance.held, start.read_url_file(root_)))
            return 0

        assert start.main(["8267"], root, run=_Calls(), serve=serve, acquire=instance) == 0

        # 佈建與伺服器都在持有單一實例時進行；網址和啟動器寫的格式相同，結束後讓出並刪掉
        assert seen == [(True, "http://127.0.0.1:8267")]
        assert instance.released == 1
        assert not start.url_file(root).exists()

    @pytest.mark.parametrize("run_code, serve_code", [(2, 0), (0, 1)])
    def test_failure_releases_the_instance_before_waiting_for_a_key(self, tmp_path, monkeypatch,
                                                                    run_code, serve_code):
        # 視窗還停在「按任意鍵關閉」時再雙擊，要能直接重新啟動（和啟動器相同）
        root = _package(tmp_path)
        instance, held_at_pause = _Instance(), []
        monkeypatch.setattr(start, "pause", lambda: held_at_pause.append(instance.held))

        code = start.main([], root, run=_Calls(code=run_code), serve=_Calls(code=serve_code),
                          acquire=instance)

        assert code == 1
        assert held_at_pause == [False]
        assert not start.url_file(root).exists()

    def test_unexpected_error_still_releases_the_instance(self, tmp_path):
        root = _package(tmp_path, provisioned=True)
        instance = _Instance()

        def serve(root_: Path, port: int) -> int:
            raise OSError("拒絕存取")

        with pytest.raises(OSError):
            start.main([], root, run=_Calls(), serve=serve, acquire=instance)

        assert instance.released == 1
        assert not start.url_file(root).exists()

    def test_instance_name_follows_the_launcher(self, tmp_path):
        # 啟動器：Local\ + AppName + -launcher- + 資料夾完整路徑去掉結尾的 \ 或 /、轉大寫後
        # UTF-8 的 SHA-256 前 8 個位元組（16 個十六進位字）
        launcher = _launcher()
        assert 'const string AppName = "AI_Translate";' in launcher
        assert '"Local\\\\" + AppName + "-launcher-" + PathHash(root)' in launcher
        assert ".TrimEnd('\\\\', '/').ToUpperInvariant()" in launcher
        assert "for (int i = 0; i < 8; i++)" in launcher
        assert 'Path.Combine(dataDir, "launcher-url.txt")' in launcher

        folder = tmp_path / "AI_Translate"
        name = start.instance_name(folder)
        assert re.fullmatch(r"Local\\AI_Translate-launcher-[0-9a-f]{16}", name)
        assert start.instance_name(tmp_path / "ai_translate") == name  # 不分大小寫
        assert start.instance_name(tmp_path / "AI_Translate-old") != name
        assert start.url_file(folder) == folder / "data" / "launcher-url.txt"

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows 上取得真的 mutex，在整合測試測")
    def test_other_platforms_do_not_check(self, tmp_path):
        release = start.acquire_instance(tmp_path)
        assert release is not None
        release()


class _Console:
    """假的 stdin：是 console。"""

    def isatty(self) -> bool:
        return True


class TestPause:
    def _msvcrt(self, monkeypatch, pending: list[bytes]) -> list[bytes]:
        """換成假的 Windows console：pending 是緩衝區裡已經按過的鍵；回傳讀到的鍵。"""
        read: list[bytes] = []

        def getch() -> bytes:
            key = pending.pop(0) if pending else b"now"
            read.append(key)
            return key

        fake = types.ModuleType("msvcrt")
        fake.kbhit = lambda: bool(pending)  # type: ignore[attr-defined]
        fake.getch = getch  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "msvcrt", fake)
        monkeypatch.setattr(sys, "platform", "win32")
        return read

    def test_keys_pressed_while_the_server_ran_do_not_close_the_window(self, monkeypatch):
        # 伺服器跑的時候按過的鍵還在緩衝區：先丟掉，等的是看到訊息之後的那一下（和啟動器相同）
        read = self._msvcrt(monkeypatch, [b"a", b"\r"])
        monkeypatch.setattr(sys, "stdin", _Console())

        start.pause()

        assert read == [b"a", b"\r", b"now"]

    def test_does_not_wait_when_input_is_not_a_console(self, monkeypatch, capsys):
        read = self._msvcrt(monkeypatch, [])
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))

        start.pause()

        assert read == []
        assert "按任意鍵關閉" in capsys.readouterr().out


class _FakeProcess:
    """假的 subprocess.Popen：wait() 依序丟出或回傳 results 裡的東西。"""

    instances: list["_FakeProcess"] = []
    pid = 4242

    def __init__(self, cmd, cwd, env):
        self.cmd, self.cwd, self.env = cmd, cwd, env
        _FakeProcess.instances.append(self)

    results: list = []

    def wait(self):
        result = _FakeProcess.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class TestRunServer:
    @pytest.fixture(autouse=True)
    def _fake_popen(self, monkeypatch):
        _FakeProcess.instances = []
        self.jobs: list[str] = []
        monkeypatch.setattr(subprocess, "Popen", _FakeProcess)
        monkeypatch.setattr(start, "stop_with_this_process", self._fake_job)
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("APP_MODE", "docker")

    def _fake_job(self, pid: int):
        self.jobs.append(f"bind {pid}")
        return lambda: self.jobs.append("close")

    def test_runs_in_backend_with_the_launcher_env(self):
        _FakeProcess.results = [0]

        assert start.run_server(PKG, 8267) == 0

        (proc,) = _FakeProcess.instances
        assert proc.cmd == start.server_command(PKG, 8267)
        assert proc.cwd == PKG / "backend"
        # 啟動器設的變數蓋過使用者環境裡的同名變數，其他的照樣繼承
        assert {k: proc.env[k] for k in start.server_env(PKG)} == start.server_env(PKG)
        assert proc.env["PATH"] == "/usr/bin"

    def test_exit_code_is_returned(self):
        _FakeProcess.results = [3221225477]

        assert start.run_server(PKG, 8267) == 3221225477

    def test_server_is_bound_to_start_py_while_it_runs(self):
        # start.py 被單獨結束時伺服器跟著結束（Windows 上真的結束，在 tests/integration 測）
        _FakeProcess.results = [KeyboardInterrupt(), 0]

        start.run_server(PKG, 8267)

        assert self.jobs == ["bind 4242", "close"]

    def test_unexpected_error_while_waiting_also_closes_the_job(self):
        _FakeProcess.results = [RuntimeError("壞掉")]

        with pytest.raises(RuntimeError):
            start.run_server(PKG, 8267)

        assert self.jobs == ["bind 4242", "close"]

    def test_ctrl_c_waits_for_the_server_and_is_not_a_failure(self):
        # Ctrl+C 也送到了伺服器：等它自己收尾，不當成失敗（不停下來等按鍵）
        _FakeProcess.results = [KeyboardInterrupt(), 3221225786]

        assert start.run_server(PKG, 8267) == 0


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 上建立真的 Job Object，在整合測試測")
def test_other_platforms_do_not_bind_the_server():
    assert start.stop_with_this_process(4242) is None


class TestFiles:
    def test_start_bat_is_ascii_without_bom(self):
        data = (PORTABLE / "start.bat").read_bytes()

        assert data.isascii(), "start.bat 只能有 ASCII：cmd 會讀錯多位元組字元後面的行"
        assert portable_zip.batch_file_problems(data.replace(b"\n", b"\r\n")) == []

    def test_start_bat_runs_start_py_with_the_bundled_python(self):
        bat = (PORTABLE / "start.bat").read_text(encoding="ascii")

        assert bat.splitlines()[0] == "@echo off"
        # -I：不讀使用者的 site-packages 與 PYTHON* 環境變數；-X utf8：導向檔案時也輸出 UTF-8
        assert r'"%~dp0runtime\python.exe" -I -X utf8 "%~dp0bin\start.py" %*' in bat
        assert "pause" in bat  # 找不到 Python 時也停下來

    def test_build_puts_start_py_in_bin(self):
        script = (ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")
        assert 'Copy-Item (Join-Path $portableDir "start.py") (Join-Path $binDir "start.py")' in script
        assert {"start.bat", "bin/start.py"} <= set(portable_zip.required_files(script))
        # start.py 以 bin\start.py 的上一層當發布包的根目錄（不解析 subst 與網路磁碟機，同啟動器）
        assert start.ROOT == Path(os.path.abspath(start.__file__)).parent.parent


class TestReadme:
    def _readme(self) -> str:
        return (PORTABLE / "README.txt").read_text(encoding="utf-8")

    def test_only_placeholder_is_version(self):
        # build_release.ps1 只換 {VERSION}；其他的大括號字樣會原樣出現在使用者看到的檔案裡
        assert re.findall(r"\{[A-Z_]+\}", self._readme()) == ["{VERSION}"]

    def test_says_how_to_get_the_visual_cpp_runtime(self):
        # 本機轉錄要另外裝的可轉散發套件（#304）：和 start.py、啟動器提示的是同一個網址
        requirements = self._readme()[self._readme().index("硬體需求"):]
        assert "Microsoft Visual C++ 可轉散發套件" in requirements
        assert start.VC_REDIST_URL in requirements

    def test_troubleshooting_points_to_start_bat(self):
        readme = self._readme()
        troubleshooting = readme[readme.index("疑難排解"):]
        assert "start.bat" in troubleshooting
