"""整合測試：免安裝版的啟動器（tools/launcher.cs，#268）。

和 build_release.ps1 一樣用 Windows 內建的 csc 編譯啟動器，放進一個假的程式資料夾；
runtime\\python.exe 與 bin\\uv.exe 換成替身（tests/fixtures/launcher_stub.cs），照環境變數假裝
伺服器提早結束、一直沒就緒、就緒後崩潰，或首次佈建失敗（預先下載 torch 或 uv）。每種情況都檢查
視窗印出的訊息、結束代碼，以及 data\\logs 裡啟動器的日誌（去識別：不寫使用者名稱與家目錄）。
System32 也換成假的資料夾（AIT_LAUNCHER_SYSTEM_DIR），由測試決定有沒有 NVIDIA 驅動與 VC++ 可轉散發
套件的 DLL（#304）。

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
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pytest

from tools.portable import start

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_SOURCE = ROOT / "tools" / "launcher.cs"
STUB_SOURCE = ROOT / "tests" / "fixtures" / "launcher_stub.cs"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
WINDOWS = sys.platform == "win32"

USER = "王小明"
TODAY_LOG = f"launcher-{date.today().isoformat()}.log"

windows_only = pytest.mark.skipif(not WINDOWS, reason="要 Windows：具名 mutex 與 32 位元的結束代碼")


def _compile(source: Path, out: Path, library: bool = False) -> None:
    if WINDOWS:
        cmd = [str(CSC), "/nologo", "/optimize", f"/out:{out}", str(source)]
    else:
        cmd = ["mcs", "-langversion:5", f"-out:{out}", str(source)]
    if library:
        cmd.insert(1, "/target:library" if WINDOWS else "-target:library")
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
    launcher, stub = folder / "Mimiji.exe", folder / "stub.exe"
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
    extra_env: dict[str, str] = field(default_factory=dict)

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def system(self) -> Path:
        """代替 System32 的資料夾；一開始是空的：沒有 NVIDIA 驅動，也沒有 VC++ 可轉散發套件。"""
        return self.root.parent / "System32"

    @property
    def sentinel(self) -> Path:
        return self.root / "runtime" / ".provisioned"

    @property
    def downloads(self) -> Path:
        """首次佈建時預先下載的 torch 放在這裡（#303）。"""
        return self.root / "runtime" / "downloads"

    def env(self, server: str, uv_exit: int, timeout: int, prefetch_exit: int = 0) -> dict[str, str]:
        env = {**os.environ,
               "USERPROFILE": str(self.home), "USERNAME": USER,
               "AIT_LAUNCHER_NO_BROWSER": "1", "AIT_LAUNCHER_HEALTH_TIMEOUT": str(timeout),
               "LAUNCHER_STUB_SERVER": server, "LAUNCHER_STUB_UV_EXIT": str(uv_exit),
               "LAUNCHER_STUB_PREFETCH_EXIT": str(prefetch_exit),
               "AIT_LAUNCHER_SYSTEM_DIR": str(self.system), **self.extra_env}
        return env

    def cmd(self) -> list[str]:
        exe = str(self.root / "Mimiji.exe")
        return [exe] if WINDOWS else ["mono", exe]

    def start(self, server: str = "serve", uv_exit: int = 0, timeout: int = 30,
              name: str = "first", prefetch_exit: int = 0) -> tuple[subprocess.Popen, Path]:
        """在背景啟動；輸出寫進檔案（替身沿用啟動器的輸出，接管線的話要等替身也結束才讀得完）。"""
        output = self.root.parent / f"{name}-output.txt"
        with output.open("wb") as out:
            process = subprocess.Popen(
                self.cmd(), cwd=self.root, env=self.env(server, uv_exit, timeout, prefetch_exit),
                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
        return process, output

    def run(self, server: str = "serve", uv_exit: int = 0, timeout: int = 30,
            name: str = "run", prefetch_exit: int = 0) -> Result:
        """執行到結束：輸入接到空的地方，「按任意鍵關閉」直接過。"""
        process, output = self.start(server, uv_exit, timeout, name, prefetch_exit)
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
    root = base / "Mimiji"
    for folder in ("runtime", "bin", "backend"):
        (root / folder).mkdir(parents=True)
    (base / "System32").mkdir()
    shutil.copy(launcher, root / "Mimiji.exe")
    shutil.copy(stub, root / "runtime" / "python.exe")
    shutil.copy(stub, root / "bin" / "uv.exe")
    # 替身看到這個檔名就假裝是預先下載 torch，不讀它的內容
    (root / "bin" / "prefetch_wheels.py").write_text("# 替身\n", encoding="utf-8")
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


def _is_prefetch(call: list[str]) -> bool:
    return call[0] == "python" and call[-2].endswith("prefetch_wheels.py")


class TestProvisioning:
    def test_failure_lists_common_causes_and_the_log_folder(self, app):
        app.sentinel.unlink()

        result = app.run(uv_exit=2)

        assert result.returncode == 1
        assert "執行環境佈建失敗（uv 結束代碼 2）" in result.output
        for cause in ("網路中斷", "磁碟空間不足", "防毒軟體", "防火牆", "路徑太長"):
            assert cause in result.output
        assert "PyTorch 與已下載完的套件會保留" in result.output
        assert f"{LOG_FOLDER_HINT}{app.data / 'logs'}" in result.output
        assert not app.sentinel.exists()
        # 佈建失敗就不啟動伺服器；下載好的 torch 留著，重新執行時不用再下載
        prefetch, uv = app.calls()
        assert _is_prefetch(prefetch) and uv[0] == "uv"
        assert (app.downloads / "torch-stub.whl").exists()

    def test_success_marks_the_runtime_and_starts_the_server(self, app):
        app.sentinel.unlink()

        app.run(server="exit:3")

        assert app.sentinel.exists()
        prefetch, uv, server = app.calls()
        # 先預先下載 torch，uv 再從那個資料夾找 torch 的 wheel
        assert prefetch[2:] == ["-I", "-X", "utf8", str(app.root / "bin" / "prefetch_wheels.py"),
                                str(app.downloads)]
        assert uv[0] == "uv" and uv[2:4] == ["pip", "install"]
        assert uv[-2:] == ["--find-links", str(app.downloads)]
        assert server[0] == "python" and not _is_prefetch(server)
        # 裝好之後刪掉下載的檔案
        assert not app.downloads.exists()

    @pytest.mark.parametrize(("code", "message", "kept"), [
        (2, "PyTorch 沒有下載完", "已下載的部分會保留：網路恢復後重新執行 Mimiji.exe，會從中斷的地方接著下載"),
        (3, "下載的 PyTorch 和預期的不同，已經刪掉", "請重新執行 Mimiji.exe 再下載一次"),
        (4, "PyTorch 下載到一半時寫不進資料夾", "清出磁碟空間後重新執行 Mimiji.exe，會從中斷的地方接著下載"),
    ], ids=["interrupted", "mismatch", "disk"])
    def test_torch_download_that_stops_says_what_to_do(self, app, code, message, kept):
        app.sentinel.unlink()

        result = app.run(prefetch_exit=code)

        assert result.returncode == 1
        assert message in result.output and kept in result.output
        assert f"{LOG_FOLDER_HINT}{app.data / 'logs'}" in result.output
        assert result.output.rstrip().endswith("按任意鍵關閉...")
        # 不執行 uv、不啟動伺服器；下載到一半的部分留著，下次接著下載
        [prefetch] = app.calls()
        assert _is_prefetch(prefetch)
        assert not app.sentinel.exists()
        assert (app.downloads / "torch-stub.whl.part").exists()
        assert f"下載 PyTorch 結束，代碼 {code}" in result.log

    @pytest.mark.parametrize("code", [5, 1])
    def test_torch_that_cannot_be_prefetched_is_left_to_uv(self, app, code):
        # 5：來源下載不到（例如伺服器上沒有這個檔案）；1：prefetch_wheels.py 自己出錯
        app.sentinel.unlink()

        app.run(server="exit:3", prefetch_exit=code)

        assert app.sentinel.exists()
        assert [call[0] for call in app.calls()] == ["python", "uv", "python"]
        assert not app.downloads.exists()

    def test_leftover_downloads_are_removed_on_the_next_start(self, app):
        # 上次佈建成功、但下載的檔案沒刪掉（例如防毒軟體正在掃描）
        app.downloads.mkdir(parents=True)
        (app.downloads / "torch-stub.whl").write_text("stub", encoding="utf-8")

        app.run(server="exit:3")

        assert not app.downloads.exists()
        assert [call[0] for call in app.calls()] == ["python"]


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


SITE_PACKAGES = ("runtime", "Lib", "site-packages")
# 替身 uv 不裝東西：先放好 uv 裝完的樣子。名稱取自 #239 實測的 torch\lib（KINETO.LIB 換成大寫）
TORCH_LIB_FILES = {"dnnl.lib": 300, "KINETO.LIB": 200, "torch_cpu.lib": 100,
                   "torch_cpu.dll": 7, "c10.dll": 5,
                   "notes.libx": 3}  # 檔名比對 *.lib 時會被誤刪的副檔名
KEPT = {"torch_cpu.dll", "c10.dll", "notes.libx"}


def _install_torch(app: App) -> tuple[Path, Path]:
    torch_lib = app.root.joinpath(*SITE_PACKAGES, "torch", "lib")
    torch_lib.mkdir(parents=True)
    for name, size in TORCH_LIB_FILES.items():
        (torch_lib / name).write_bytes(b"x" * size)
    other = app.root.joinpath(*SITE_PACKAGES, "numpy", "_core", "lib", "npymath.lib")
    other.parent.mkdir(parents=True)
    other.write_bytes(b"x")
    return torch_lib, other


class TestStaticLibraries:
    """首次佈建後刪掉 torch\\lib 的 .lib（#305）：執行時用不到，約 2.8 GB。"""

    def test_first_provisioning_removes_them_and_keeps_the_dlls(self, app):
        app.sentinel.unlink()
        torch_lib, other = _install_torch(app)

        result = app.run(server="exit:3")

        assert {p.name for p in torch_lib.iterdir()} == KEPT
        assert other.exists()  # 只刪 torch 的
        assert app.sentinel.exists()
        # 預先下載 PyTorch、uv、伺服器
        assert [call[0] for call in app.calls()] == ["python", "uv", "python"]
        assert "刪掉 torch\\lib 裡執行時用不到的 .lib：3 個，600 位元組" in result.log

    def test_provisioned_runtime_removes_what_is_left_at_the_next_start(self, app):
        # 首次佈建時刪不掉的，或這個版本之前佈建的
        marked = app.sentinel.read_bytes()
        torch_lib, _ = _install_torch(app)

        result = app.run(server="exit:3")

        assert {p.name for p in torch_lib.iterdir()} == KEPT
        assert [call[0] for call in app.calls()] == ["python"]  # 不重新佈建
        assert app.sentinel.read_bytes() == marked
        assert "刪掉 torch\\lib 裡執行時用不到的 .lib：3 個" in result.log

        again = app.run(server="exit:3", name="again")

        assert "torch\\lib" not in again.log[len(result.log):]  # 沒東西可刪時不寫

    def test_runtime_without_torch_starts_as_usual(self, app):
        result = app.run(server="exit:3")

        assert "伺服器還沒就緒就結束了（結束代碼 3）" in result.output
        assert "torch\\lib" not in result.log

    @windows_only
    def test_one_that_cannot_be_removed_does_not_stop_provisioning(self, app):
        # 防毒軟體掃描時開著檔案：Python 的 open 不帶 FILE_SHARE_DELETE，DeleteFile 會失敗
        app.sentinel.unlink()
        torch_lib, _ = _install_torch(app)

        with (torch_lib / "dnnl.lib").open("rb"):
            result = app.run(server="exit:3")

        assert {p.name for p in torch_lib.iterdir()} == KEPT | {"dnnl.lib"}
        assert app.sentinel.exists()
        # 預先下載 PyTorch、uv、伺服器
        assert [call[0] for call in app.calls()] == ["python", "uv", "python"]
        assert "佈建失敗" not in result.output
        assert "刪掉 torch\\lib 裡執行時用不到的 .lib：2 個，300 位元組" in result.log
        assert "torch\\lib 裡有 1 個 .lib 刪不掉，下次啟動再試：dnnl.lib（IOException：" in result.log
        assert USER not in result.log  # 例外訊息裡的路徑也去識別


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


@windows_only
class TestSharedWithStartBat:
    """start.bat（tools/portable/start.py）和啟動器共用單一實例（#267）：同一個資料夾合起來只跑一個
    伺服器。伺服器啟動時會先把「處理中」的任務記成失敗才綁埠，第二個綁不到埠也已經記了。
    兩邊各自實作 mutex 的名稱，這裡用真的 mutex 確認對得上（路徑裡有中文的帳號名稱）。"""

    def test_launcher_does_not_start_a_server_while_start_bat_runs(self, app):
        release = start.acquire_instance(app.root)
        assert release is not None
        try:
            second = app.run(name="second")
        finally:
            release()

        assert second.returncode == 0
        assert "已經在另一個視窗啟動中" in second.output
        assert app.calls() == []

    def test_start_bat_does_not_start_a_server_while_the_launcher_runs(self, app, capsys):
        (app.root / "backend" / "main.py").write_text("", encoding="utf-8")
        first, output = app.start(server="serve")
        try:
            _wait(lambda: "伺服器已就緒：" in _read(output))
            url = _read(output).split("伺服器已就緒：", 1)[1].split()[0]

            def serve(root: Path, port: int) -> int:
                raise AssertionError("不該啟動第二個伺服器")

            assert start.main([], app.root, serve=serve) == 0
        finally:
            first.kill()
            first.wait()

        out = capsys.readouterr().out
        assert "Mimiji 已經在執行，不會再啟動第二個" in out
        assert f"請用瀏覽器開啟 {url}" in out

    def test_launcher_starts_once_start_bat_has_released(self, app):
        release = start.acquire_instance(app.root)
        assert release is not None
        release()

        result = app.run(server="exit:3")

        assert "已經在" not in result.output
        assert [call[0] for call in app.calls()] == ["python"]


class TestLog:
    def test_writes_what_the_window_showed_into_the_data_folder(self, app):
        result = app.run(server="exit:3")

        assert "啟動器開始：版本 v0.0.0-test" in result.log
        if WINDOWS:
            # 真正的 Windows 版本，不是相容性設定降成的 6.2.9200（Windows 8）
            major = int(result.log.split("啟動器開始：版本 v0.0.0-test，Windows ", 1)[1].split(".")[0])
            assert major >= 10
        assert "正在啟動 Mimiji 伺服器" in result.log
        assert " - ERROR - " in result.log
        assert "伺服器還沒就緒就結束了（結束代碼 3）" in result.log

    def test_writes_the_home_folder_as_tilde(self, app):
        result = app.run(server="exit:3")

        assert USER not in result.log
        assert str(app.home) not in result.log
        assert f"程式資料夾：~{os.sep}Downloads{os.sep}Mimiji" in result.log

    def test_writes_the_user_name_in_other_paths_as_a_placeholder(self, tmp_path, binaries):
        # 解壓在家目錄以外、但路徑裡有帳號名稱的資料夾（例如 D:\王小明\Mimiji）
        app = _make_app(tmp_path / "D" / USER, binaries, home=tmp_path / "Users" / USER)

        result = app.run(server="exit:3")

        assert USER not in result.log
        assert f"{os.sep}%USERNAME%{os.sep}Mimiji" in result.log

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


VC_MISSING = "這台電腦沒有 Microsoft Visual C++ 可轉散發套件，本機轉錄不能用。"
VC_URL = "https://aka.ms/vc14/vc_redist.x64.exe"
VC_INSTALLED = "已經裝好 Microsoft Visual C++ 可轉散發套件。"
PROVISION_BANNER = "首次啟動：正在下載執行環境"
VERSIONED_DLL = """[assembly: System.Reflection.AssemblyFileVersion("{version}")]
public class Fake {{}}
"""


@pytest.fixture(scope="module")
def msvcp140(tmp_path_factory) -> dict[str, Path]:
    """帶檔案版本的假 msvcp140.dll：14.29（VS 2019 的最後一版）與 14.44。"""
    folder = tmp_path_factory.mktemp("msvcp140")
    dlls = {}
    for version in ("14.29.30133.0", "14.44.35211.0"):
        source = folder / f"{version}.cs"
        source.write_text(VERSIONED_DLL.format(version=version), encoding="utf-8")
        (folder / version).mkdir()
        dlls[version] = folder / version / "msvcp140.dll"
        _compile(source, dlls[version], library=True)
    return dlls


def _install_vc_runtime(folder: Path, msvcp140: Path) -> None:
    folder.mkdir(exist_ok=True)
    shutil.copy(msvcp140, folder / "msvcp140.dll")
    (folder / "vcomp140.dll").write_bytes(b"")


class TestVcRuntime:
    """有 NVIDIA 驅動、卻沒裝 VC++ 可轉散發套件（或太舊）時提示安裝，但照樣啟動（#304）。"""

    @pytest.fixture
    def nvidia(self, app) -> App:
        (app.system / "nvcuda.dll").write_bytes(b"")
        return app

    def test_missing_runtime_is_reported_before_the_download_and_again_after(self, nvidia):
        nvidia.sentinel.unlink()

        result = nvidia.run(server="serve-then-exit:7")

        output = result.output
        first = output.index(VC_MISSING)
        assert first < output.index(PROVISION_BANNER) < output.index(VC_MISSING, first + 1)
        assert output.count(VC_URL) == 2
        assert "只用 Gemini 的話可以不裝" in output
        # 不擋啟動：伺服器照樣起來
        assert "伺服器已就緒：http://127.0.0.1:" in output
        # 預先下載 PyTorch、uv、伺服器
        assert [call[0] for call in nvidia.calls()] == ["python", "uv", "python"]
        assert VC_MISSING in result.log
        assert "System32 沒有 msvcp140.dll" in result.log

    def test_installing_during_the_download_is_noticed(self, nvidia, msvcp140, tmp_path):
        nvidia.sentinel.unlink()
        installer = tmp_path / "vc_redist"
        _install_vc_runtime(installer, msvcp140["14.44.35211.0"])
        nvidia.extra_env.update(LAUNCHER_STUB_UV_COPY_FROM=str(installer),
                                LAUNCHER_STUB_UV_COPY_TO=str(nvidia.system))

        result = nvidia.run(server="exit:3")

        assert result.output.count(VC_MISSING) == 1
        assert result.output.index(PROVISION_BANNER) < result.output.index(VC_INSTALLED)

    def test_already_provisioned_reports_once(self, nvidia):
        result = nvidia.run(server="exit:3")

        assert result.output.count(VC_MISSING) == 1
        assert VC_INSTALLED not in result.output

    def test_old_runtime_is_reported_with_both_versions(self, nvidia, msvcp140):
        _install_vc_runtime(nvidia.system, msvcp140["14.29.30133.0"])

        result = nvidia.run(server="exit:3")

        assert ("這台電腦的 Microsoft Visual C++ 可轉散發套件太舊（目前 14.29，需要 14.38 以上），"
                "本機轉錄不能用。") in result.output
        assert VC_URL in result.output
        assert "msvcp140.dll 的版本：14.29.30133.0" in result.log

    def test_recent_runtime_is_not_mentioned(self, nvidia, msvcp140):
        _install_vc_runtime(nvidia.system, msvcp140["14.44.35211.0"])

        result = nvidia.run(server="exit:3")

        assert "可轉散發套件" not in result.output

    def test_missing_vcomp140_counts_as_missing(self, nvidia, msvcp140):
        _install_vc_runtime(nvidia.system, msvcp140["14.44.35211.0"])
        (nvidia.system / "vcomp140.dll").unlink()

        result = nvidia.run(server="exit:3")

        assert VC_MISSING in result.output
        assert "System32 沒有 vcomp140.dll" in result.log

    def test_unreadable_version_is_not_called_old(self, nvidia):
        (nvidia.system / "msvcp140.dll").write_bytes(b"not a PE file")
        (nvidia.system / "vcomp140.dll").write_bytes(b"")

        result = nvidia.run(server="exit:3")

        assert "可轉散發套件" not in result.output

    def test_without_nvidia_driver_nothing_is_said(self, app):
        # 本機轉錄本來就不能用，轉錄頁會說明是沒有顯卡
        app.sentinel.unlink()

        result = app.run(server="exit:3")

        assert "可轉散發套件" not in result.output
        assert "可轉散發套件" not in result.log
