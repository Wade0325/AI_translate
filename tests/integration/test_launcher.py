"""整合測試：免安裝版的啟動器（tools/launcher.cs，#268）。

和 build_release.ps1 一樣用 Windows 內建的 csc 編譯啟動器，放進一個假的程式資料夾；
runtime\\python.exe 與 bin\\uv.exe 換成替身（tests/fixtures/launcher_stub.cs），照環境變數假裝
伺服器提早結束、一直沒就緒、就緒後崩潰，或首次佈建失敗。每種情況都檢查視窗印出的訊息、結束代碼，
以及 data\\logs 裡啟動器的日誌（去識別：不寫使用者名稱與家目錄）。

沒有 C# 編譯器時跳過：CI 的 Windows 腿會跑。其他平台裝了 Mono（mcs 與 mono）時也會跑，用
-langversion:5 擋下內建 csc 不支援的語法；單一實例與 Windows 的結束代碼只在 Windows 測。
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_SOURCE = ROOT / "tools" / "launcher.cs"
STUB_SOURCE = ROOT / "tests" / "fixtures" / "launcher_stub.cs"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
WINDOWS = sys.platform == "win32"

USER = "王小明"
TODAY_LOG = f"launcher-{date.today().isoformat()}.log"

windows_only = pytest.mark.skipif(not WINDOWS, reason="要 Windows：具名 mutex 與 32 位元的結束代碼")


def _compile(source: Path, out: Path) -> None:
    if WINDOWS:
        cmd = [str(CSC), "/nologo", "/optimize", f"/out:{out}", str(source)]
    else:
        cmd = ["mcs", "-langversion:5", f"-out:{out}", str(source)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stdout + result.stderr


def _has_compiler() -> bool:
    if WINDOWS:
        return CSC.is_file()
    return shutil.which("mcs") is not None and shutil.which("mono") is not None


pytestmark = pytest.mark.skipif(not _has_compiler(), reason="沒有 C# 編譯器（Windows 內建 csc，或 Mono）")


@pytest.fixture(scope="module")
def binaries(tmp_path_factory) -> tuple[Path, Path]:
    folder = tmp_path_factory.mktemp("launcher-bin")
    launcher, stub = folder / "AI_Translate.exe", folder / "stub.exe"
    _compile(LAUNCHER_SOURCE, launcher)
    _compile(STUB_SOURCE, stub)
    return launcher, stub


@dataclass
class Result:
    returncode: int
    output: str
    log: str


@dataclass
class App:
    """假的程式資料夾：解壓後的免安裝版長這樣，只是 python.exe 與 uv.exe 是替身。"""

    root: Path
    home: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def sentinel(self) -> Path:
        return self.root / "runtime" / ".provisioned"

    def env(self, server: str, uv_exit: int, timeout: int) -> dict[str, str]:
        env = {**os.environ,
               "USERPROFILE": str(self.home), "USERNAME": USER,
               "AIT_LAUNCHER_NO_BROWSER": "1", "AIT_LAUNCHER_HEALTH_TIMEOUT": str(timeout),
               "LAUNCHER_STUB_SERVER": server, "LAUNCHER_STUB_UV_EXIT": str(uv_exit)}
        return env

    def cmd(self) -> list[str]:
        exe = str(self.root / "AI_Translate.exe")
        return [exe] if WINDOWS else ["mono", exe]

    def start(self, server: str = "serve", uv_exit: int = 0, timeout: int = 30,
              name: str = "first") -> tuple[subprocess.Popen, Path]:
        """在背景啟動；輸出寫進檔案（替身沿用啟動器的輸出，接管線的話要等替身也結束才讀得完）。"""
        output = self.root.parent / f"{name}-output.txt"
        with output.open("wb") as out:
            process = subprocess.Popen(
                self.cmd(), cwd=self.root, env=self.env(server, uv_exit, timeout),
                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
        return process, output

    def run(self, server: str = "serve", uv_exit: int = 0, timeout: int = 30,
            name: str = "run") -> Result:
        """執行到結束：輸入接到空的地方，「按任意鍵關閉」直接過。"""
        process, output = self.start(server, uv_exit, timeout, name)
        try:
            returncode = process.wait(timeout=60)
        finally:
            if process.poll() is None:
                process.kill()
        return Result(returncode, _read(output), self.log())

    def log(self) -> str:
        path = self.data / "logs" / TODAY_LOG
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def calls(self) -> list[list[str]]:
        """替身被執行的紀錄：[名稱, 行程編號, 參數…]，照順序。"""
        path = self.root / "stub-calls.txt"
        if not path.exists():
            return []
        return [line.split() for line in path.read_text(encoding="utf-8").splitlines()]


def _read(path: Path) -> str:
    # 啟動器的標準輸出與錯誤輸出各自可能先寫一個 BOM
    return path.read_bytes().decode("utf-8", errors="replace").replace("\ufeff", "")


def _make_app(base: Path, binaries: tuple[Path, Path], home: Path) -> App:
    launcher, stub = binaries
    root = base / "AI_Translate"
    for folder in ("runtime", "bin", "backend"):
        (root / folder).mkdir(parents=True)
    shutil.copy(launcher, root / "AI_Translate.exe")
    shutil.copy(stub, root / "runtime" / "python.exe")
    shutil.copy(stub, root / "bin" / "uv.exe")
    (root / "backend" / "requirements-standalone.txt").write_text("fastapi\n", encoding="utf-8")
    (root / "backend" / "VERSION").write_text("v0.0.0-test", encoding="ascii")
    (root / "runtime" / ".provisioned").write_text("", encoding="ascii")
    return App(root, home)


@pytest.fixture
def app(tmp_path, binaries) -> App:
    """解壓在使用者的「下載」資料夾裡：路徑帶著帳號名稱。"""
    home = tmp_path / "Users" / USER
    return _make_app(home / "Downloads", binaries, home)


def _alive(pid: int) -> bool:
    if WINDOWS:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait(condition, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "等太久"
        time.sleep(0.1)


LOG_FOLDER_HINT = "日誌在："


class TestServerFailures:
    def test_server_that_exits_before_ready_reports_its_exit_code(self, app):
        result = app.run(server="exit:3")

        assert result.returncode == 1
        assert "伺服器還沒就緒就結束了（結束代碼 3）" in result.output
        assert "秒內沒有就緒" not in result.output
        assert f"{LOG_FOLDER_HINT}{app.data / 'logs'}" in result.output
        # 按任意鍵才關；記下的網址已經刪掉，下一次雙擊不會以為它還在跑
        assert result.output.rstrip().endswith("按任意鍵關閉...")
        assert not (app.data / "launcher-url.txt").exists()

    def test_server_that_never_gets_ready_times_out_and_is_stopped(self, app):
        result = app.run(server="hang", timeout=2)

        assert result.returncode == 1
        assert "伺服器在 2 秒內沒有就緒，已經停止它" in result.output
        assert "還沒就緒就結束" not in result.output
        assert f"{LOG_FOLDER_HINT}{app.data / 'logs'}" in result.output
        [[_, pid, *_]] = app.calls()
        assert not _alive(int(pid))

    def test_server_that_crashes_after_ready_stops_the_window(self, app):
        result = app.run(server="serve-then-exit:7")

        assert result.returncode == 7
        ready = result.output.index("伺服器已就緒：http://127.0.0.1:")
        crashed = result.output.index("伺服器意外停止了（結束代碼 7）")
        assert ready < crashed
        assert f"{LOG_FOLDER_HINT}{app.data / 'logs'}" in result.output
        assert result.output.rstrip().endswith("按任意鍵關閉...")

    @windows_only
    def test_windows_status_codes_are_shown_in_hex_with_their_meaning(self, app):
        result = app.run(server="exit:-1073741819")  # 0xC0000005

        assert "結束代碼 0xC0000005，記憶體存取違規" in result.output


class TestProvisioning:
    def test_failure_lists_common_causes_and_the_log_folder(self, app):
        app.sentinel.unlink()

        result = app.run(uv_exit=2)

        assert result.returncode == 1
        assert "執行環境佈建失敗（uv 結束代碼 2）" in result.output
        for cause in ("網路中斷", "磁碟空間不足", "防毒軟體", "防火牆", "路徑太長"):
            assert cause in result.output
        assert f"{LOG_FOLDER_HINT}{app.data / 'logs'}" in result.output
        assert not app.sentinel.exists()
        # 佈建失敗就不啟動伺服器
        assert [call[0] for call in app.calls()] == ["uv"]

    def test_success_marks_the_runtime_and_starts_the_server(self, app):
        app.sentinel.unlink()

        app.run(server="exit:3")

        assert app.sentinel.exists()
        uv, server = app.calls()
        assert uv[0] == "uv" and uv[2:4] == ["pip", "install"]
        assert server[0] == "python"


class TestServerCommand:
    def test_server_does_not_load_the_users_own_packages(self, app):
        # -s：使用者自己裝的套件（%APPDATA%\Python\Python311\site-packages）不進 sys.path，那裡的 .pth
        # 也不執行（#301）；python311._pth 只開了隔離模式，沒有關掉它。旗標要在 -m 前面，之後的參數
        # 都交給 uvicorn。-I 與 -E 會連 PYTHON* 環境變數一起忽略，啟動器設的 PYTHONIOENCODING 就失效
        app.run(server="exit:3")

        [server] = app.calls()
        args = server[2:]
        flags = args[:args.index("-m")]
        assert "-s" in flags
        assert not {"-I", "-E"} & set(flags)
        assert args[args.index("-m") + 1:][:2] == ["uvicorn", "main:app"]


class TestIoErrors:
    def test_data_folder_that_cannot_be_created_names_the_path(self, app):
        app.data.write_text("佔住 data 這個名稱的檔案", encoding="utf-8")

        result = app.run()

        assert result.returncode == 1
        assert f"無法建立資料夾：{app.data}" in result.output
        if WINDOWS:
            assert "那個位置已經有一個同名的檔案" in result.output
        assert "日誌沒有寫成" in result.output
        assert app.calls() == []

    @windows_only
    def test_data_folder_without_write_permission_is_reported_before_starting(self, app):
        # 實測時伺服器先起來、才在 traceback 最後一行寫 PermissionError：啟動器要自己先說清楚
        app.data.mkdir()
        user = os.environ["USERNAME"]
        subprocess.run(["icacls", str(app.data), "/deny", f"{user}:(OI)(CI)(W,AD)"],
                       check=True, capture_output=True)
        try:
            result = app.run()
        finally:
            subprocess.run(["icacls", str(app.data), "/remove:d", user],
                           check=True, capture_output=True)

        assert result.returncode == 1
        assert f"無法寫入資料夾：{app.data}" in result.output
        assert "原因：沒有寫入權限（存取被拒）" in result.output
        assert "不要放在 C:\\Program Files 底下" in result.output
        assert app.calls() == []

    def test_log_folder_that_cannot_be_created_does_not_stop_the_launch(self, app):
        app.data.mkdir()
        (app.data / "logs").write_text("佔住 logs 這個名稱的檔案", encoding="utf-8")

        result = app.run(server="exit:3")

        assert "注意：日誌檔寫不進去，只顯示在這個視窗" in result.output
        assert "伺服器還沒就緒就結束了（結束代碼 3）" in result.output
        assert "日誌沒有寫成：無法建立" in result.output
        # 例外訊息自己的句號不再多接一個
        assert "。。" not in result.output and ".。" not in result.output
        # 沒有日誌資料夾時，不說伺服器的日誌在「同一個資料夾」
        assert "同一個資料夾" not in result.output


@windows_only
class TestSingleInstance:
    def test_second_launch_opens_the_running_server_instead_of_starting_another(self, app):
        first, output = app.start(server="serve")
        try:
            _wait(lambda: "伺服器已就緒：" in _read(output))
            url = _read(output).split("伺服器已就緒：", 1)[1].split()[0]

            second = app.run(name="second")

            assert second.returncode == 0
            assert "已經在執行，不會再啟動第二個" in second.output
            assert f"已在瀏覽器開啟：{url}" in second.output
            assert [call[0] for call in app.calls()] == ["python"]
            assert first.poll() is None  # 第一個照樣在跑
        finally:
            first.kill()
            first.wait()
            for call in app.calls():
                _wait(lambda pid=int(call[1]): not _alive(pid))  # 啟動器結束時，伺服器跟著結束

    def test_second_launch_while_the_first_is_still_starting_points_to_its_window(self, app):
        first, output = app.start(server="hang", timeout=30)
        try:
            _wait(lambda: len(app.calls()) == 1)

            second = app.run(name="second")

            assert second.returncode == 0
            assert "已經在另一個視窗啟動中" in second.output
            assert len(app.calls()) == 1
        finally:
            first.kill()
            first.wait()


class TestLog:
    def test_writes_what_the_window_showed_into_the_data_folder(self, app):
        result = app.run(server="exit:3")

        assert "啟動器開始：版本 v0.0.0-test" in result.log
        if WINDOWS:
            # 真正的 Windows 版本，不是相容性設定降成的 6.2.9200（Windows 8）
            major = int(result.log.split("啟動器開始：版本 v0.0.0-test，Windows ", 1)[1].split(".")[0])
            assert major >= 10
        assert "正在啟動 AI_Translate 伺服器" in result.log
        assert " - ERROR - " in result.log
        assert "伺服器還沒就緒就結束了（結束代碼 3）" in result.log

    def test_writes_the_home_folder_as_tilde(self, app):
        result = app.run(server="exit:3")

        assert USER not in result.log
        assert str(app.home) not in result.log
        assert f"程式資料夾：~{os.sep}Downloads{os.sep}AI_Translate" in result.log

    def test_writes_the_user_name_in_other_paths_as_a_placeholder(self, tmp_path, binaries):
        # 解壓在家目錄以外、但路徑裡有帳號名稱的資料夾（例如 D:\王小明\AI_Translate）
        app = _make_app(tmp_path / "D" / USER, binaries, home=tmp_path / "Users" / USER)

        result = app.run(server="exit:3")

        assert USER not in result.log
        assert f"{os.sep}%USERNAME%{os.sep}AI_Translate" in result.log

    def test_keeps_the_last_seven_days_of_launcher_logs(self, app):
        logs = app.data / "logs"
        logs.mkdir(parents=True)
        for days_ago in range(1, 10):
            day = date.today() - timedelta(days=days_ago)
            (logs / f"launcher-{day.isoformat()}.log").write_text("舊的", encoding="utf-8")
        # 伺服器的日誌與名稱不是日誌檔的不動
        old_app_log = f"app-{(date.today() - timedelta(days=9)).isoformat()}.log"
        (logs / old_app_log).write_text("", encoding="utf-8")
        (logs / "launcher-notes.log").write_text("", encoding="utf-8")

        app.run(server="exit:3")

        assert sorted(p.name for p in logs.iterdir()) == sorted(
            [f"launcher-{(date.today() - timedelta(days=d)).isoformat()}.log" for d in range(7)]
            + [old_app_log, "launcher-notes.log"])
