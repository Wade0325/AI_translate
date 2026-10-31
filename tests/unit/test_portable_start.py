"""免安裝版的手動啟動（start.bat → bin\\start.py）與 README.txt（#267），內容在 tools/portable/。

start.bat 是防毒軟體攔下 AI_Translate.exe 時的手動啟動，只用隨包的 Python 執行 start.py；佈建、啟動
與訊息都在 start.py。它要和啟動器（tools/launcher.cs）做一樣的事：設一樣的環境變數，用一樣的指令
佈建與啟動。兩邊各寫一份（Python 與 C#），這裡檢查沒有分岔，並測 start.py 的每一條路徑。

start.bat 只能是 ASCII：cmd 遇到多位元組字元會算錯下一行的位置，把後面的字當成指令執行（#267 在
Windows 10 上實測到）。發布包裡的換行、BOM 與 ASCII 由 CI 檢查 zip（tools/portable_zip.py）。
"""
import io
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
        args = re.search(r'"(-m uvicorn [^"]*)\{0\}"', launcher)
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
        monkeypatch.setattr(subprocess, "Popen", _FakeProcess)
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("APP_MODE", "docker")

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

    def test_ctrl_c_waits_for_the_server_and_is_not_a_failure(self):
        # Ctrl+C 也送到了伺服器：等它自己收尾，不當成失敗（不停下來等按鍵）
        _FakeProcess.results = [KeyboardInterrupt(), 3221225786]

        assert start.run_server(PKG, 8267) == 0


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
        # start.py 以 bin\start.py 的上一層當發布包的根目錄
        assert start.ROOT == Path(start.__file__).resolve().parent.parent


class TestReadme:
    def _readme(self) -> str:
        return (PORTABLE / "README.txt").read_text(encoding="utf-8")

    def test_only_placeholder_is_version(self):
        # build_release.ps1 只換 {VERSION}；其他的大括號字樣會原樣出現在使用者看到的檔案裡
        assert re.findall(r"\{[A-Z_]+\}", self._readme()) == ["{VERSION}"]

    def test_troubleshooting_points_to_start_bat(self):
        readme = self._readme()
        troubleshooting = readme[readme.index("疑難排解"):]
        assert "start.bat" in troubleshooting
