"""免安裝版的手動啟動（#267）：防毒軟體攔下 AI_Translate.exe 時，使用者雙擊 start.bat，由它執行這支。

build_release.ps1 把它放在發布包的 bin\\start.py；start.bat 用隨包的 runtime\\python.exe 執行它::

    runtime\\python.exe -I -X utf8 bin\\start.py [埠號]

做的事和啟動器（tools/launcher.cs）相同：第一次執行時用同一個指令佈建執行環境、刪掉 torch 執行時用不到的
.lib、寫同一個完成標記，再以同樣的環境變數啟動伺服器（tests/unit/test_portable_start.py 檢查兩邊一致）。
有 NVIDIA 驅動、卻沒裝 Microsoft Visual C++ 可轉散發套件（或太舊）時，也一樣在佈建之前提示安裝（#304）。
不同的是不會自動改用空的埠，也不會自動開啟瀏覽器。

單一實例也和啟動器共用：同名的 mutex 與 data\\launcher-url.txt，所以同一個資料夾的 AI_Translate.exe
與 start.bat 合起來只會跑一個伺服器（tests/integration/test_launcher.py 在 Windows 上兩個方向都測）。
這不只是避免開兩個視窗：伺服器啟動時會先把資料庫裡「處理中」的任務記成失敗（backend/main.py 的
啟動清掃），之後才綁埠，所以第二個實例就算綁不到埠，也已經把第一個實例正在轉錄的任務記成失敗
（#267 在 Windows 10 上實測到）。伺服器也和啟動器一樣放進「關閉時結束全部」的 Job Object：只有
start.py 被結束時（例如在工作管理員），伺服器跟著結束，不會留著跑而單一實例已經讓出。

為什麼不寫在 start.bat 裡：cmd 讀批次檔時，遇到多位元組字元（chcp 65001 下的 UTF-8 中文）會算錯
下一行的位置，把中文行切斷、當成指令執行（#267 在 Windows 10 上實測）。start.bat 只留 ASCII，
中文訊息與判斷都在這裡；Python 寫到 console 時用 Unicode 的 API，和 console 的碼頁無關。

只用標準函式庫：第一次執行時還沒佈建，runtime 裡只有 Python 本身。
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

# bin\start.py 的上一層就是發布包的根目錄。用 abspath 不用 resolve：啟動器以執行時的路徑
# （Path.GetFullPath）替 mutex 命名，resolve 會把 subst 的磁碟機與連線的網路磁碟機換成實際路徑
ROOT = Path(os.path.abspath(__file__)).parent.parent
DEFAULT_PORT = 8000
URL_PATTERN = re.compile(r"http://127\.0\.0\.1:([0-9]{1,5})")

PROVISION_BANNER = """\
═══════════════════════════════════════════════════════
 首次啟動：正在下載執行環境（約 3.5 GB，含 PyTorch）
 過程視網速需要數分鐘到數十分鐘；中斷後重開會續傳。
 沒有 NVIDIA 顯卡的電腦也會下載這些，只用 Gemini 時大部分用不到。
═══════════════════════════════════════════════════════"""

# Microsoft Visual C++ 可轉散發套件（#304）：本機轉錄要從 System32 載入的 DLL，以及第一個
# （msvcp140.dll）至少要的版本。依據寫在 backend/app/provider/local/weights.py 的同名常數；
# 這裡、weights.py 與啟動器三邊要相同（tests/unit/test_vc_runtime.py 比對）
VC_REDIST_URL = "https://aka.ms/vc14/vc_redist.x64.exe"
VC_RUNTIME_DLLS = ("msvcp140.dll", "vcomp140.dll")
VC_RUNTIME_MIN_VERSION = (14, 38)


def python_exe(root: Path) -> Path:
    return root / "runtime" / "python.exe"


def provisioned_marker(root: Path) -> Path:
    """首次佈建完成的標記，和啟動器的相同：用哪一個啟動，另一個都認得已經佈建好。"""
    return root / "runtime" / ".provisioned"


def torch_lib(root: Path) -> Path:
    """torch 的 .lib 靜態庫所在的資料夾，和啟動器的 RemoveStaticLibraries 相同。"""
    return root / "runtime" / "Lib" / "site-packages" / "torch" / "lib"


def remove_static_libraries(root: Path) -> None:
    """刪掉 torch\\lib 的 .lib 靜態庫（約 2.8 GB），和啟動器相同（#305）。

    只有編譯要連結 torch 的 C++ 擴充時才用得到，app 執行時用不到：#239 實測刪掉前後，本機轉錄的
    每種輸出與 Silero 的切點都逐位元組相同。首次佈建成功後刪，之後每次啟動也補刪（首次佈建時被
    防毒軟體鎖住沒刪掉的）。刪不掉時照樣啟動；start.py 沒有日誌檔，寫在視窗裡。
    """
    try:
        files = [path for path in torch_lib(root).iterdir()
                 if path.suffix.lower() == ".lib" and path.is_file()]
    except OSError:  # 沒有 torch\lib，例如還沒佈建
        return
    failed: list[str] = []
    for path in files:
        try:
            path.unlink()
        except OSError as e:
            failed.append(f"{path.name}（{type(e).__name__}：{e.strerror or e}）")
    if failed:
        print(f"注意：torch\\lib 裡有 {len(failed)} 個用不到的 .lib 刪不掉，不影響使用，下次啟動再試："
              + "、".join(failed), flush=True)


def provision_command(root: Path) -> list[str]:
    """首次佈建的指令，和啟動器的相同（在 root 執行）。"""
    return [str(root / "bin" / "uv.exe"), "pip", "install",
            "--python", str(python_exe(root)),
            "--target", str(root / "runtime" / "Lib" / "site-packages"),
            "-r", str(root / "backend" / "requirements-standalone.txt")]


def server_env(root: Path) -> dict[str, str]:
    """啟動器設給伺服器的環境變數。"""
    data = root / "data"
    return {
        "APP_MODE": "standalone",
        "AIT_DATA_DIR": str(data),
        "AIT_FFMPEG_DIR": str(root / "bin"),
        "AIT_STATIC_DIR": str(root / "frontend" / "dist"),
        "HF_HOME": str(data / "models" / "hf_cache"),
        "PYTHONIOENCODING": "utf-8",
    }


def server_command(root: Path, port: int) -> list[str]:
    """啟動伺服器的指令，和啟動器的相同（在 root\\backend 執行）。

    -s：不載入使用者自己裝的套件（%APPDATA%\\Python\\Python311\\site-packages 與那裡的 .pth，
    #301）；python311._pth 只開了隔離模式，沒有關掉它。不用 -I：它會連 PYTHON* 環境變數一起
    忽略，server_env() 設的 PYTHONIOENCODING 就失效了。
    """
    return [str(python_exe(root)), "-s", "-m", "uvicorn", "main:app",
            "--host", "127.0.0.1", "--port", str(port)]


def instance_name(root: Path) -> str:
    """單一實例的 mutex 名稱，和啟動器的相同（AcquireInstance 與 PathHash）：以資料夾路徑命名，
    同一份解壓的資料夾只能跑一個，另一個資料夾（例如舊版）不受影響。"""
    path = os.path.abspath(root).rstrip("\\/")
    # 啟動器用 ToUpperInvariant：一個字元換成一個字元。str.upper 會把 ß 換成 SS 這類，那些字元照原樣
    path = "".join(c.upper() if len(c.upper()) == 1 else c for c in path)
    return "Local\\AI_Translate-launcher-" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]


def url_file(root: Path) -> Path:
    """第一個實例寫下網址，第二個實例讀它（和啟動器共用）。"""
    return root / "data" / "launcher-url.txt"


def acquire_instance(root: Path) -> Callable[[], None] | None:
    """取得這個資料夾的單一實例；回傳讓出的函式。已經有實例在執行（AI_Translate.exe 或另一個
    start.bat）時回傳 None。Windows 以外的平台不檢查（只有開發時的測試會在那裡執行）。"""
    if sys.platform != "win32":
        return lambda: None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.CreateMutexW(None, True, instance_name(root))
    error = ctypes.get_last_error()
    if not handle:
        if error == 5:  # ERROR_ACCESS_DENIED：另一個實例建立的 mutex 打不開，當成已在執行
            return None
        raise ctypes.WinError(error)
    if error == 183:  # ERROR_ALREADY_EXISTS：要等得到才算取得
        # WAIT_OBJECT_0；WAIT_ABANDONED 是上一個實例沒收尾就結束了，一樣算取得
        if kernel32.WaitForSingleObject(handle, 0) not in (0x0, 0x80):
            kernel32.CloseHandle(handle)
            return None

    def release() -> None:
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)

    return release


def write_url_file(root: Path, url: str) -> None:
    """寫不進去只影響第二個實例顯示的網址，照樣啟動（和啟動器相同）。"""
    try:
        url_file(root).parent.mkdir(parents=True, exist_ok=True)
        url_file(root).write_text(url, encoding="ascii")
    except OSError:
        pass


def read_url_file(root: Path) -> str | None:
    """第一個實例記下的網址；只接受啟動器與 start.py 自己寫的格式，不顯示檔案裡的任意文字。"""
    try:
        text = url_file(root).read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    match = URL_PATTERN.fullmatch(text)
    return text if match and 1 <= int(match.group(1)) <= 65535 else None


def probe_health(url: str) -> bool:
    """伺服器有沒有在回應；本機位址不經過代理伺服器（和啟動器相同）。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url + "/api/v1/health", timeout=2) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def show_running_instance(root: Path, probe: Callable[[str], bool]) -> None:
    url = read_url_file(root)
    if url is not None and probe(url):
        print("AI_Translate 已經在執行，不會再啟動第二個。")
        print(f"請用瀏覽器開啟 {url}")
    else:
        print("AI_Translate 已經在另一個視窗啟動中，不會再啟動第二個。")
        print("首次佈建可能要數分鐘到數十分鐘，請切換到那個視窗查看進度。")


def exit_code_text(code: int) -> str:
    """結束代碼給人看的寫法：程式當掉時 Windows 回報的是 0xC0000005 這類很大的數字。"""
    if 0 <= code <= 255:
        return str(code)
    return f"0x{code & 0xFFFFFFFF:08X}"


def parse_port(argv: Sequence[str]) -> int | None:
    """命令列的埠號；沒給時用 8000，給錯時回傳 None。"""
    if not argv:
        return DEFAULT_PORT
    try:
        port = int(argv[0])
    except ValueError:
        return None
    return port if 1 <= port <= 65535 else None


def pause() -> None:
    """失敗時停下來，雙擊執行的人才看得到原因。輸入不是 console（例如導向檔案）時不等。

    伺服器跑的時候按過的鍵還留在 console 的緩衝區：先丟掉，否則一停下來就被它們關掉（和啟動器相同）。
    """
    print("按任意鍵關閉...", flush=True)
    if sys.platform == "win32" and sys.stdin is not None and sys.stdin.isatty():
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getch()
        msvcrt.getch()


def provision(root: Path, run: Callable[..., int]) -> bool:
    print(PROVISION_BANNER, flush=True)
    code = run(provision_command(root), cwd=root)
    if code != 0:
        print()
        print(f"執行環境佈建失敗（結束代碼 {exit_code_text(code)}，多半是網路中斷）。"
              "已下載的部分會保留，")
        print("重新執行 start.bat 即可續傳。")
        return False
    remove_static_libraries(root)
    provisioned_marker(root).write_text(datetime.now().isoformat(), encoding="utf-8")
    print("執行環境佈建完成。", flush=True)
    return True


# ─── Microsoft Visual C++ 可轉散發套件（#304），和啟動器的 WarnVcRuntime 相同 ─────────────
# torch 從 System32 載入 msvcp140.dll 等 DLL，免安裝版只附 vcruntime140*.dll。缺了伺服器照樣起得來、
# Gemini 照樣能用，只有本機轉錄不能用，所以只提示、不擋。伺服器啟動時才第一次載入 torch：首次佈建
# 之前就說，使用者趁下載時裝好，就不必重新開啟。沒有 NVIDIA 驅動時不說：本機轉錄本來就不能用，
# 轉錄頁會說明。


def system_folder() -> Path:
    """System32。隨包的 Python 是 64 位元，不會被轉到 SysWOW64。"""
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


def file_version(path: Path) -> tuple[int, int] | None:
    """Windows 檔案的「檔案版本」的主、次版號（例如 msvcp140.dll 的 14.44）；不是 Windows 或讀不到
    時是 None。和 weights.py 的 _file_version 相同（只用標準函式庫，這時還沒佈建，不能 import 後端）。"""
    if sys.platform != "win32":
        return None
    import ctypes

    version_dll = ctypes.WinDLL("version")
    size = version_dll.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    data = ctypes.create_string_buffer(size)
    if not version_dll.GetFileVersionInfoW(str(path), 0, size, data):
        return None
    fixed, length = ctypes.c_void_p(), ctypes.c_uint()
    if not version_dll.VerQueryValueW(data, "\\", ctypes.byref(fixed), ctypes.byref(length)):
        return None
    if length.value < 16 or not fixed.value:
        return None
    # VS_FIXEDFILEINFO 的前四個 DWORD：dwSignature、dwStrucVersion、dwFileVersionMS、dwFileVersionLS
    words = ctypes.cast(fixed, ctypes.POINTER(ctypes.c_uint32 * 4)).contents
    if words[0] != 0xFEEF04BD:
        return None
    return words[2] >> 16, words[2] & 0xFFFF


def vc_runtime_problem(system: Path,
                       version: Callable[[Path], tuple[int, int] | None] = file_version) -> str | None:
    """給使用者看的原因；沒有 NVIDIA 驅動（System32 沒有 nvcuda.dll），或都沒問題時是 None。
    讀不到版本時不當成太舊。"""
    if not (system / "nvcuda.dll").is_file():
        return None
    if not all((system / dll).is_file() for dll in VC_RUNTIME_DLLS):
        return "這台電腦沒有 Microsoft Visual C++ 可轉散發套件"
    current = version(system / VC_RUNTIME_DLLS[0])
    if current is not None and current < VC_RUNTIME_MIN_VERSION:
        return ("這台電腦的 Microsoft Visual C++ 可轉散發套件太舊"
                f"（目前 {current[0]}.{current[1]}，"
                f"需要 {VC_RUNTIME_MIN_VERSION[0]}.{VC_RUNTIME_MIN_VERSION[1]} 以上）")
    return None


def check_vc_runtime() -> str | None:
    """這台電腦的 vc_runtime_problem；Windows 以外的平台不查（只有開發時的測試會在那裡執行）。
    查的時候出錯（例如沒有權限讀）就不提示：只是提示，不能因此擋住啟動（和啟動器相同）。"""
    if sys.platform != "win32":
        return None
    try:
        return vc_runtime_problem(system_folder())
    except OSError:
        return None


def warn_vc_runtime(problem: str) -> None:
    print("───────────────────────────────────────────────────────")
    print(f" {problem}，本機轉錄不能用。")
    print(f" 請下載安裝（需要系統管理員權限）：{VC_REDIST_URL}")
    print(" 在伺服器啟動之前裝好就不必重新開啟；之後才裝的話，裝好後關閉這個視窗，")
    print(" 再執行一次 start.bat。只用 Gemini 的話可以不裝。")
    print("───────────────────────────────────────────────────────", flush=True)


def stop_with_this_process(pid: int) -> Callable[[], None] | None:
    """把行程 pid 放進「關閉時結束全部」的 Job Object，和啟動器相同：start.py 被結束（例如在工作
    管理員只結束它）時系統關掉這個 handle，伺服器跟著結束。否則伺服器留著跑、單一實例卻已讓出，
    下一個 start.bat 會把它正在轉錄的任務記成失敗（#267 實測）。回傳關閉 handle 的函式；
    Windows 以外的平台或建立失敗時回傳 None，照樣啟動（啟動器也是）。"""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimit),
                    ("IoInfo", ctypes.c_uint64 * 6),  # IO_COUNTERS
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                 wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    extended_limit_information = 9  # JobObjectExtendedLimitInformation
    process = kernel32.OpenProcess(0x0100 | 0x0001, False, pid)  # PROCESS_SET_QUOTA | TERMINATE
    assigned = bool(
        process
        and kernel32.SetInformationJobObject(job, extended_limit_information,
                                             ctypes.byref(info), ctypes.sizeof(info))
        and kernel32.AssignProcessToJobObject(job, process))
    if process:
        kernel32.CloseHandle(process)
    if not assigned:
        kernel32.CloseHandle(job)
        return None

    def close() -> None:
        kernel32.CloseHandle(job)

    return close


def run_server(root: Path, port: int) -> int:
    """啟動伺服器並等它結束；回傳結束代碼。按 Ctrl+C 時伺服器也收到，等它自己收尾，回傳 0。"""
    env = {**os.environ, **server_env(root)}
    proc = subprocess.Popen(server_command(root, port), cwd=root / "backend", env=env)
    close_job = stop_with_this_process(proc.pid)
    interrupted = False
    try:
        while True:
            try:
                code = proc.wait()
                break
            except KeyboardInterrupt:
                interrupted = True
    finally:
        if close_job is not None:
            close_job()  # 伺服器已經結束；沒結束（start.py 出了例外）時也一併結束它
    return 0 if interrupted else code


def _call(cmd: Sequence[str], cwd: Path) -> int:
    return subprocess.call(list(cmd), cwd=cwd)


def main(argv: Sequence[str], root: Path = ROOT, *,
         run: Callable[..., int] = _call,
         serve: Callable[[Path, int], int] = run_server,
         acquire: Callable[[Path], Callable[[], None] | None] = acquire_instance,
         probe: Callable[[str], bool] = probe_health,
         vc_problem: Callable[[], str | None] | None = None) -> int:
    port = parse_port(argv)
    if port is None:
        print(f"埠號要是 1 到 65535 的數字，例如 start.bat 8001（收到的是：{argv[0]}）。")
        pause()
        return 1

    needed = [python_exe(root), root / "bin" / "uv.exe", root / "backend" / "main.py",
              root / "backend" / "requirements-standalone.txt"]
    missing = [path.relative_to(root) for path in needed if not path.exists()]
    if missing:
        print("找不到 " + "、".join(str(path) for path in missing) + "，請確認 zip 已完整解壓。")
        pause()
        return 1

    release = acquire(root)
    if release is None:
        show_running_instance(root, probe)
        pause()
        return 0
    try:
        started = _start(root, port, run, serve, vc_problem or check_vc_runtime)
    finally:
        # 先讓出單一實例再停下來等按鍵：視窗還停著時再雙擊，可以直接重新啟動（和啟動器相同）
        try:
            url_file(root).unlink(missing_ok=True)
        except OSError:
            pass
        release()
    if not started:
        pause()
        return 1
    return 0


def _start(root: Path, port: int, run: Callable[..., int],
           serve: Callable[[Path, int], int], vc_problem: Callable[[], str | None]) -> bool:
    """第一次執行時佈建，再啟動伺服器並等它結束；失敗時印出原因，回傳 False。"""
    problem = vc_problem()
    if problem is not None:
        warn_vc_runtime(problem)
    if provisioned_marker(root).exists():
        remove_static_libraries(root)  # 每次啟動補刪，和啟動器相同
    else:
        if not provision(root, run):
            return False
        if problem is not None:
            # 佈建前提示過、佈建完再查一次：還沒裝就再說一次（uv 的輸出把前一次推上去了），
            # 裝好了就說一聲（和啟動器的 RecheckVcRuntime 相同）
            problem = vc_problem()
            if problem is None:
                print("已經裝好 Microsoft Visual C++ 可轉散發套件。", flush=True)
            else:
                warn_vc_runtime(problem)

    url = f"http://127.0.0.1:{port}"
    write_url_file(root, url)
    print(f"正在啟動 AI_Translate 伺服器（port {port}）...")
    print("首次啟動需載入模型函式庫，可能需要一兩分鐘，請稍候。")
    print(f"視窗出現「Uvicorn running on {url}」之後，用瀏覽器開啟 {url}")
    print("關閉此視窗即停止 AI_Translate。")
    print(flush=True)
    code = serve(root, port)
    if code != 0:
        print()
        print(f"伺服器已停止（結束代碼 {exit_code_text(code)}），請檢視上方日誌；"
              "日誌檔在 data\\logs。")
        print(f"埠 {port} 被占用時，在這個資料夾開啟命令提示字元，"
              f"執行 start.bat {port + 1 if port < 65535 else 8001} 換一個埠。")
        return False
    return True


def entry(argv: Sequence[str]) -> int:
    """start.bat 執行的入口：沒料到的例外也印出來並停下來，視窗才不會一閃就關掉。"""
    try:
        return main(argv)
    except Exception:
        import traceback
        traceback.print_exc()
        print()
        print("start.bat 發生沒有預料到的錯誤。回報問題時，請附上上面的訊息與 data\\logs 裡的日誌檔。")
        pause()
        return 1


if __name__ == "__main__":
    sys.exit(entry(sys.argv[1:]))
