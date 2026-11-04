"""試發布（#35）：在 CI 乾淨的 Windows runner 上，照使用者的做法跑一次免安裝版，記下數字與行為。

用法（.github/workflows/portable-trial.yml 呼叫；要 Windows 與系統管理員權限）：

    python tools/portable_trial/run_trial.py --zip build/Mimiji-trial1-win64.zip --out trial-results

照時間序做這些事，每一步的結果寫進 --out 的 results.json 與 summary.md：

1. 環境：Windows 版本、磁碟、長路徑設定、Defender、VC++ 執行階段、有沒有 NVIDIA 驅動。
2. 解壓：和使用者一樣解到「下載」資料夾（Downloads\\<zip 名稱>\\Mimiji）。
3. 第一次啟動（冷啟動）：雙擊 Mimiji.exe 的等價做法。PATH 只留 Windows 內建的資料夾，
   長路徑設定關掉（新裝的 Windows 預設關），經過 proxy.py 計下載量。記下首次佈建的下載量與耗時、
   uv 的輸出、health 就緒的秒數，再問幾個 API（health、版本、供應商、權重狀態、診斷資訊）。
4. 權重下載：在同一個伺服器上按「下載預設權重」的 API，記下載量與耗時（沒有顯卡也能下載）。
5. 第二次啟動（熱啟動）的 health 秒數。
6. import 探針：用佈建好的 runtime\\python.exe 逐一 import，記秒數、CUDA 與載入的 DLL。
7. 大小：佈建後的資料夾、uv 的下載快取、最長的路徑（離 260 字元還有多少）。
8. 簽章：發布包與佈建後每個 exe、dll、pyd 的 Authenticode 狀態。
9. VC++ 執行階段：先靜態看每個 PE 檔 import 了哪些 VC++ 的 DLL、發布包裡有沒有附；再把
   System32 裡 VC++ 的 DLL 暫時改名，重跑 import 探針、uv/ffmpeg，並用 Mimiji.exe 與 start.bat
   各啟動一次，最後改回來。runner 沒有 NVIDIA 驅動，這時不該提示安裝 VC++（#304）。
10. VC++ 提示（#304）：VC++ 一樣拿掉，在 System32 放一個空的 nvcuda.dll 假裝有 NVIDIA 驅動，刪掉
    佈建完成的標記讓它重跑佈建，用 Mimiji.exe 與 start.bat 各啟動一次：提示要出現在佈建之前、
    佈建完再說一次，診斷資訊說 PyTorch 因為缺 VC++ 載入失敗。最後拿掉假的 nvcuda.dll。
11. 斷網續傳：刪掉第一次的資料夾與 uv 快取，打開 Defender 的即時保護（能開的話），重新解壓、
    啟動；下載到一半時讓代理「斷網」，看啟動器怎麼結束、留下什麼，恢復網路後再啟動一次，
    記這次又下載了多少、花多久、health 幾秒就緒。
12. 在 uv 下載時斷網（#303）：同樣重新解壓，這次等 PyTorch 預先下載完、uv 開始下載其他套件之後才
    斷網。看 uv 的下載快取是不是留在程式資料夾的 runtime\\uv-cache、恢復網路後是不是只補下載剩下的，
    佈建完成後是不是清掉。

uv 的下載快取（#303）：每一步都記 runtime\\uv-cache 與 uv 預設的 %LOCALAPPDATA%\\uv\\cache。
佈建完成後前者要清掉，後者不該出現；摘要最後一節逐項判定。

每一步失敗都記下來、繼續做下一步；整支腳本只有在自己壞掉時才非零結束。
只在 CI 的試發布 workflow 用，不進發布包。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROXY_PORT = 18080
INTERRUPT_AT_BYTES = 1_500_000_000  # 斷網的時間點：torch（最大的一個檔）下載到一半左右
PYPI_FILES_HOST = "files.pythonhosted.org"
CUT_PYPI_BYTES = 30_000_000  # #303：uv 從 PyPI 下載到這麼多時斷網
GIVE_UP_SECONDS = 15 * 60  # 斷網之後等啟動器自己結束的上限；超過就當成使用者關掉視窗
RUN_TIMEOUT_SECONDS = 100 * 60
WEIGHTS_TIMEOUT_SECONDS = 45 * 60
VCRT = re.compile(
    r"^(msvcp140(_[a-z0-9_]+)?|vcruntime140(_\d)?|concrt140|vcomp140|vccorlib140|vcamp140|mfc140\w*)\.dll$",
    re.IGNORECASE)
LONG_PATHS_KEY = r"SYSTEM\CurrentControlSet\Control\FileSystem"
CREATE_NEW_PROCESS_GROUP = 0x00000200
ENDPOINTS = (
    "/api/v1/health",
    "/api/v1/version",
    "/api/v1/providers",
    "/api/v1/setting/local-models/status",
    "/api/v1/setting/local-models/readiness",
    "/api/v1/diagnostics",
    "/",
)

# 啟動器（tools/launcher.cs）與 start.py（tools/portable/start.py）印出的字（#304）
VC_HINT = "請下載安裝（需要系統管理員權限）"
VC_REDIST_URL = "https://aka.ms/vc14/vc_redist.x64.exe"
PROVISION_BANNER = "首次啟動：正在下載執行環境"
PROVISION_DONE = "執行環境佈建完成"
# 後端給的原因（backend/app/provider/local/weights.py 的 _torch_load_failed）
NO_GPU_TEXT = "這台電腦沒有可用的 NVIDIA 顯卡（找不到 NVIDIA 驅動）"
VC_TORCH_TEXT = "PyTorch 載入失敗：這台電腦沒有 Microsoft Visual C++ 可轉散發套件"
START_BAT_PORT = 8000  # start.bat 不帶參數時的埠

RESULTS: dict[str, Any] = {"errors": []}
OUT = Path()


def now() -> str:
    return time.strftime("%H:%M:%S")


def say(message: str) -> None:
    print(f"[{now()}] {message}", flush=True)


def save() -> None:
    (OUT / "results.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2),
                                      encoding="utf-8")


@contextlib.contextmanager
def phase(name: str) -> Iterator[dict[str, Any]]:
    say(f"── {name}")
    record: dict[str, Any] = {}
    RESULTS[name] = record
    started = time.time()
    try:
        yield record
    except Exception as e:
        record["error"] = f"{type(e).__name__}: {e}"
        RESULTS["errors"].append({"phase": name, "error": record["error"],
                                  "traceback": traceback.format_exc()[-4000:]})
        say(f"   {name} 失敗：{record['error']}")
    finally:
        record["phase_seconds"] = round(time.time() - started, 1)
        save()


def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          **kwargs)


def powershell(script: str, timeout: float = 1800) -> str:
    prefix = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ProgressPreference = 'SilentlyContinue'; "
    # workflow 的步驟在 pwsh 7 裡執行，PSModulePath 指向 pwsh 7 的模組；Windows PowerShell 5.1 沿用時
    # 載不進 Microsoft.PowerShell.Security（Get-AuthenticodeSignature 每個都失敗），所以拿掉
    env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    result = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", prefix + script],
                 timeout=timeout, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell 失敗（{result.returncode}）：{result.stderr.strip()[-2000:]}")
    return result.stdout.strip()


def ps_json(script: str, timeout: float = 1800) -> Any:
    text = powershell(f"{script} | ConvertTo-Json -Depth 5 -Compress", timeout)
    return json.loads(text) if text else None


def long(path: Path | str) -> str:
    """加上 \\\\?\\ 前綴：路徑超過 260 字元也能操作（長路徑設定關掉時）。"""
    text = str(path)
    return text if text.startswith("\\\\?\\") else "\\\\?\\" + text


def rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(long(path), ignore_errors=True)


def gib(n: float | None) -> str:
    return "?" if n is None else f"{n / 1024 ** 3:.2f} GiB"


def mb(n: float | None) -> str:
    return "?" if n is None else f"{n / 1000 ** 2:,.0f} MB"


def nic_received() -> int | None:
    try:
        text = powershell("(Get-NetAdapterStatistics | Measure-Object -Property ReceivedBytes -Sum).Sum")
        return int(float(text))
    except (RuntimeError, ValueError):
        return None


# ─── 環境 ────────────────────────────────────────────────────────────────

def registry_value(key: str, name: str) -> Any:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            return winreg.QueryValueEx(handle, name)[0]
    except OSError:
        return None


def set_long_paths(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, LONG_PATHS_KEY, 0, winreg.KEY_SET_VALUE) as handle:
        winreg.SetValueEx(handle, "LongPathsEnabled", 0, winreg.REG_DWORD, 1 if enabled else 0)


def system32() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


def vcrt_in_system32() -> list[str]:
    return sorted(p.name for p in system32().iterdir() if VCRT.match(p.name))


def defender_status() -> Any:
    try:
        return ps_json("Get-MpComputerStatus | Select-Object AMServiceEnabled, AntivirusEnabled, "
                       "RealTimeProtectionEnabled, OnAccessProtectionEnabled, IsTamperProtected")
    except (RuntimeError, ValueError) as e:
        return {"error": str(e)[-500:]}


def environment(record: dict[str, Any]) -> None:
    record["os"] = ps_json("Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, "
                           "BuildNumber, OSArchitecture")
    record["cpu"] = ps_json("Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, "
                            "NumberOfLogicalProcessors")
    record["ram_gb"] = round(float(powershell(
        "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory")) / 1024 ** 3, 1)
    record["disk_free_gb"] = {d: round(shutil.disk_usage(d).free / 1024 ** 3, 1)
                              for d in ("C:\\", "D:\\") if Path(d).exists()}
    record["long_paths_enabled"] = registry_value(LONG_PATHS_KEY, "LongPathsEnabled")
    record["defender"] = defender_status()
    record["vcredist_x64"] = {
        "installed": registry_value(r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64", "Installed"),
        "version": registry_value(r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64", "Version"),
        "system32_dlls": vcrt_in_system32(),
    }
    record["dotnet_framework_release"] = registry_value(
        r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", "Release")
    record["nvidia"] = {
        "nvidia_smi_on_path": shutil.which("nvidia-smi"),
        "nvcuda_dll": (system32() / "nvcuda.dll").exists(),
    }
    record["user_profile"] = os.environ.get("USERPROFILE")


# ─── 代理 ────────────────────────────────────────────────────────────────

class Proxy:
    def __init__(self, label: str, *, cut_host: str | None = None, cut_after: int | None = None) -> None:
        self.label = label
        self.cut = ["--cut-host", cut_host, "--cut-after-bytes", str(cut_after)] if cut_host else []
        self.stats_path = OUT / f"proxy-{label}-stats.json"
        self.tunnels_path = OUT / f"proxy-{label}-tunnels.jsonl"
        self.control_path = OUT / f"proxy-{label}-blackhole"
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        self.control_path.unlink(missing_ok=True)
        self.process = subprocess.Popen([
            sys.executable, str(HERE / "proxy.py"), "--port", str(PROXY_PORT),
            "--stats", str(self.stats_path), "--control", str(self.control_path),
            "--tunnels", str(self.tunnels_path), *self.cut])
        deadline = time.time() + 30
        while time.time() < deadline:
            with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", PROXY_PORT), 1):
                return
            time.sleep(0.3)
        raise RuntimeError("代理沒有起來")

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait(30)
        self.process = None

    def stats(self) -> dict[str, Any]:
        for _ in range(10):
            try:
                return json.loads(self.stats_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                time.sleep(0.1)
        return {}

    def down(self) -> int:
        return int(self.stats().get("down", 0))

    def blackhole(self, on: bool) -> None:
        if on:
            self.control_path.write_text("blackhole", encoding="utf-8")
        else:
            self.control_path.unlink(missing_ok=True)


# ─── 啟動器 ──────────────────────────────────────────────────────────────

def user_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """乾淨電腦上雙擊時的環境：PATH 只有 Windows 內建的資料夾，沒有 Python、uv、git 的設定。"""
    drop = ("PYTHON", "UV_", "PIP_", "VIRTUAL_ENV", "CONDA", "PYO3", "HF_", "HUGGINGFACE")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(drop)}
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    env["PATH"] = ";".join([
        rf"{windir}\system32", windir, rf"{windir}\System32\Wbem",
        rf"{windir}\System32\WindowsPowerShell\v1.0",
        rf"{os.environ.get('LOCALAPPDATA', '')}\Microsoft\WindowsApps",
    ])
    proxy = f"http://127.0.0.1:{PROXY_PORT}"
    env.update(HTTP_PROXY=proxy, HTTPS_PROXY=proxy, NO_PROXY="127.0.0.1,localhost",
               AIT_LAUNCHER_NO_BROWSER="1")
    env.update(extra or {})
    return env


def kill_tree(process: subprocess.Popen[bytes], root: Path) -> None:
    if process.poll() is None:
        run(["taskkill", "/PID", str(process.pid), "/T", "/F"])
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(60)
    # 首次佈建時 uv 不在啟動器的 Job Object 裡：殺掉啟動器之後可能還在
    with contextlib.suppress(RuntimeError):
        powershell("Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like "
                   f"'{root}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}")
    time.sleep(2)


UV_LINE = re.compile(r"^\s*(Resolved|Prepared|Installed|Uninstalled|Audited|Built|Building|"
                     r"Downloading|Downloaded|warning|error|×|╰─▶|help:|Caused by)", re.IGNORECASE)


def parse_launcher_logs(root: Path) -> dict[str, Any]:
    logs = sorted((root / "data" / "logs").glob("launcher-*.log"))
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in logs)
    found: dict[str, Any] = {
        "uv_exit": [{"code": m.group(1), "seconds": int(m.group(2))}
                    for m in re.finditer(r"uv 結束，代碼 (\S+)，花了 (\d+) 秒", text)],
        "ready_seconds": [int(m.group(1)) for m in re.finditer(r"伺服器在 (\d+) 秒後就緒", text)],
        "free_space": re.findall(r"可用空間：([^\n]+)", text),
        # 佈建完清 uv 的下載快取（#303，tools/launcher.cs 的 RemoveUvCache）
        "uv_cache_clean": [{"code": m.group(1), "seconds": int(m.group(2))}
                           for m in re.finditer(r"清 uv 的下載快取（[^）]*）結束，代碼 (\S+)，花了 (\d+) 秒", text)],
        "uv_cache_left": len(re.findall(r"uv 的下載快取沒有清乾淨", text)),
    }
    return found


def run_launcher(root: Path, label: str, proxy: Proxy, *, interrupt_at: int | None = None,
                 extra_env: dict[str, str] | None = None
                 ) -> tuple[dict[str, Any], subprocess.Popen[bytes] | None]:
    """雙擊 Mimiji.exe，等到就緒、結束或逾時。就緒時回傳還在跑的行程，由呼叫端停掉。"""
    console = OUT / f"{label}-console.log"
    result: dict[str, Any] = {"label": label, "events": {}, "timeline": []}
    events = result["events"]
    nic_before = nic_received()
    start_down = proxy.down()
    started = time.time()
    with console.open("wb") as f:
        process = subprocess.Popen(
            [str(root / "Mimiji.exe")], cwd=root, env=user_env(extra_env),
            stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
            creationflags=CREATE_NEW_PROCESS_GROUP)
    blackholed_at: float | None = None
    last_sample = -10.0
    ready = False
    while True:
        time.sleep(1)
        elapsed = time.time() - started
        text = console.read_bytes().decode("utf-8", errors="replace")
        snapshot = proxy.stats()
        down = int(snapshot.get("down", 0)) - start_down
        if blackholed_at is None and snapshot.get("cut_at") is not None:
            # 代理照 --cut-host／--cut-after-bytes 自己斷網（#303）
            blackholed_at = elapsed
            events["blackhole"] = round(elapsed, 1)
            events["blackhole_bytes"] = down
            say(f"   {label}：代理在下載 {mb(down)} 時自己斷網")
        if elapsed - last_sample >= 5:
            result["timeline"].append([round(elapsed), down])
            last_sample = elapsed
        if "provisioned" not in events and "執行環境佈建完成" in text:
            events["provisioned"] = round(elapsed, 1)
            events["provisioned_bytes"] = down
            say(f"   {label}：佈建完成，{elapsed:.0f} 秒，下載 {mb(down)}")
        if "伺服器已就緒" in text:
            events["ready"] = round(elapsed, 1)
            events["ready_bytes"] = down
            ready = True
            say(f"   {label}：就緒，{elapsed:.0f} 秒")
            break
        if interrupt_at is not None and blackholed_at is None and down >= interrupt_at:
            proxy.blackhole(True)
            blackholed_at = elapsed
            events["blackhole"] = round(elapsed, 1)
            events["blackhole_bytes"] = down
            say(f"   {label}：下載到 {mb(down)} 時斷網")
        if process.poll() is not None:
            events["exited"] = round(elapsed, 1)
            result["exit_code"] = process.returncode
            say(f"   {label}：啟動器結束，代碼 {process.returncode}，{elapsed:.0f} 秒")
            break
        if blackholed_at is not None and elapsed - blackholed_at > GIVE_UP_SECONDS:
            events["gave_up_after_blackhole"] = round(elapsed, 1)
            say(f"   {label}：斷網 {GIVE_UP_SECONDS} 秒後啟動器還沒結束，當成使用者關掉視窗")
            kill_tree(process, root)
            break
        if elapsed > RUN_TIMEOUT_SECONDS:
            events["timeout"] = round(elapsed, 1)
            kill_tree(process, root)
            break
    text = console.read_bytes().decode("utf-8", errors="replace")
    lines = text.splitlines()
    result["vc_hint"] = vc_hint(text)
    result["uv_cache_cleaning_shown"] = "正在清掉首次佈建時暫存的檔案" in text  # #303
    result["console_tail"] = lines[-150:]
    result["uv_lines"] = [line for line in lines if UV_LINE.match(line)][:400]
    result["launcher_log"] = parse_launcher_logs(root)
    result["proxy"] = proxy.stats()
    nic_after = nic_received()
    if nic_before is not None and nic_after is not None:
        result["nic_received_bytes"] = nic_after - nic_before
    url_file = root / "data" / "launcher-url.txt"
    if ready and url_file.exists():
        result["url"] = url_file.read_text(encoding="utf-8").strip()
    return result, (process if ready else None)


def vc_hint(text: str) -> dict[str, Any]:
    """視窗輸出裡安裝 VC++ 可轉散發套件的提示（#304）：出現幾次、有沒有網址、和佈建的先後。"""
    hints = [m.start() for m in re.finditer(re.escape(VC_HINT), text)]
    banner = text.find(PROVISION_BANNER)
    done = text.find(PROVISION_DONE)
    return {
        "count": len(hints),
        "url": VC_REDIST_URL in text,
        "provisioned_this_run": banner >= 0,
        "before_provisioning": bool(hints) and banner >= 0 and hints[0] < banner,
        "again_after_provisioning": bool(hints) and done >= 0 and hints[-1] > done,
        "lines": [line.strip() for line in text.splitlines()
                  if VC_HINT in line or "本機轉錄不能用。" in line][:8],
    }


def run_start_bat(root: Path, label: str, proxy: Proxy
                  ) -> tuple[dict[str, Any], subprocess.Popen[bytes] | None]:
    """雙擊 start.bat 的等價做法（防毒軟體攔下 Mimiji.exe 時的手動啟動，#267）：等到 health
    回應、結束或逾時。就緒時回傳還在跑的行程，由呼叫端停掉。"""
    console = OUT / f"{label}-console.log"
    result: dict[str, Any] = {"label": label, "events": {}}
    events = result["events"]
    base = f"http://127.0.0.1:{START_BAT_PORT}"
    start_down = proxy.down()
    started = time.time()
    with console.open("wb") as f:
        process = subprocess.Popen(
            ["cmd.exe", "/d", "/c", str(root / "start.bat")], cwd=root, env=user_env(),
            stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
            creationflags=CREATE_NEW_PROCESS_GROUP)
    ready = False
    while True:
        time.sleep(1)
        elapsed = time.time() - started
        text = console.read_bytes().decode("utf-8", errors="replace")
        if "provisioned" not in events and PROVISION_DONE in text:
            events["provisioned"] = round(elapsed, 1)
            events["provisioned_bytes"] = proxy.down() - start_down
        status, _ = http("GET", base + "/api/v1/health", timeout=2)
        if status == 200:
            events["ready"] = round(elapsed, 1)
            ready = True
            say(f"   {label}：就緒，{elapsed:.0f} 秒")
            break
        if process.poll() is not None:
            events["exited"] = round(elapsed, 1)
            result["exit_code"] = process.returncode
            say(f"   {label}：start.bat 結束，代碼 {process.returncode}，{elapsed:.0f} 秒")
            break
        if elapsed > RUN_TIMEOUT_SECONDS:
            events["timeout"] = round(elapsed, 1)
            kill_tree(process, root)
            break
    text = console.read_bytes().decode("utf-8", errors="replace")
    result["vc_hint"] = vc_hint(text)
    result["console_tail"] = text.splitlines()[-150:]
    result["proxy_bytes"] = proxy.down() - start_down
    if ready:
        result["url"] = base
    return result, (process if ready else None)


def local_state(base: str) -> dict[str, Any]:
    """伺服器眼中的本機轉錄：health、readiness 的原因與訊息、診斷資訊裡驅動與顯卡那幾行。"""
    state: dict[str, Any] = {}
    state["health"], _ = http("GET", base + "/api/v1/health")
    readiness: dict[str, Any] = {}
    deadline = time.time() + 120
    while time.time() < deadline:  # readiness 在背景檢查，剛起來時可能還沒查完
        _, body = http("GET", base + "/api/v1/setting/local-models/readiness")
        try:
            readiness = json.loads(body)
        except ValueError:
            readiness = {"raw": body[:300].decode("utf-8", errors="replace")}
            break
        if readiness.get("checked", True):
            break
        time.sleep(2)
    state["readiness"] = {k: readiness.get(k) for k in ("checked", "ready", "reason", "message", "raw")
                          if k in readiness}
    _, body = http("GET", base + "/api/v1/diagnostics")
    try:
        text = str(json.loads(body).get("text", ""))
    except (ValueError, AttributeError):
        text = body[:3000].decode("utf-8", errors="replace")
    state["diagnostics_gpu"] = [line for line in text.splitlines()
                                if line.startswith(("- NVIDIA 驅動", "- 顯卡", "- PyTorch 的錯誤"))]
    return state


def expect_vc(run_: dict[str, Any], state: dict[str, Any] | None, *, driver: bool) -> dict[str, Any]:
    """對照 #304 的預期結果。driver：System32 有沒有 nvcuda.dll。"""
    hint = run_.get("vc_hint") or {}
    state = state or {}
    gpu_lines = state.get("diagnostics_gpu") or []
    reason = (state.get("readiness") or {}).get("reason")
    checks: dict[str, bool] = {"health_200": state.get("health") == 200}
    if driver:
        checks["hint_shown"] = hint.get("count", 0) >= 1
        checks["hint_has_url"] = bool(hint.get("url"))
        if hint.get("provisioned_this_run"):
            checks["hint_before_provisioning"] = bool(hint.get("before_provisioning"))
            checks["hint_again_after_provisioning"] = bool(hint.get("again_after_provisioning"))
        checks["reason_torch_load_failed"] = reason == "torch_load_failed"
        checks["diagnostics_says_vc"] = any(VC_TORCH_TEXT in line for line in gpu_lines)
    else:
        checks["no_hint"] = hint.get("count", 0) == 0
        checks["reason_no_gpu"] = reason == "no_gpu"
        checks["diagnostics_says_no_driver"] = any(NO_GPU_TEXT in line for line in gpu_lines)
    return {"ok": all(checks.values()), "checks": checks}


def http(method: str, url: str, timeout: float = 120) -> tuple[int | None, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (OSError, ValueError) as e:
        return None, f"{type(e).__name__}: {e}".encode()


def probe(base: str) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for path in ENDPOINTS:
        started = time.time()
        status, body = http("GET", base + path)
        entry: dict[str, Any] = {"status": status, "seconds": round(time.time() - started, 2)}
        try:
            entry["json"] = json.loads(body)
        except ValueError:
            entry["text"] = body[:300].decode("utf-8", errors="replace")
            entry["bytes"] = len(body)
        answers[path] = entry
    return answers


def copy_logs(root: Path, label: str) -> None:
    logs = root / "data" / "logs"
    if logs.is_dir():
        shutil.copytree(logs, OUT / f"{label}-data-logs", dirs_exist_ok=True)


# ─── 量測 ────────────────────────────────────────────────────────────────

def tree_stats(path: Path) -> dict[str, Any]:
    total = files = 0
    longest, longest_len = "", 0
    for dirpath, _dirs, names in os.walk(long(path)):
        for name in names:
            full = os.path.join(dirpath, name)
            files += 1
            with contextlib.suppress(OSError):
                total += os.path.getsize(full)
            if len(full) - 4 > longest_len:
                longest, longest_len = full[4:], len(full) - 4
    return {"bytes": total, "files": files, "longest_path": longest, "longest_len": longest_len}


def breakdown(path: Path, depth: int, top: int = 15) -> list[list[Any]]:
    """``path`` 底下第 ``depth`` 層的每個資料夾（或檔案）佔多少，由大到小取前 ``top`` 個。"""
    sizes: dict[str, int] = {}
    base = len(long(path)) + 1
    for dirpath, _dirs, names in os.walk(long(path)):
        for name in names:
            full = os.path.join(dirpath, name)
            key = "\\".join(full[base:].split("\\")[:depth])
            with contextlib.suppress(OSError):
                sizes[key] = sizes.get(key, 0) + os.path.getsize(full)
    return [[k, v] for k, v in sorted(sizes.items(), key=lambda kv: -kv[1])[:top]]


def uv_cache() -> Path:
    """uv 預設的下載快取。#303 之後首次佈建不該用到它。"""
    return Path(os.environ["LOCALAPPDATA"]) / "uv" / "cache"


def package_uv_cache(root: Path) -> Path:
    """首次佈建時 uv 的下載快取（#303）：放在程式資料夾裡，佈建完成後清掉。"""
    return root / "runtime" / "uv-cache"


def maybe_stats(path: Path) -> dict[str, Any] | None:
    return tree_stats(path) if path.exists() else None


def disk_free(root: Path) -> int:
    return shutil.disk_usage(root.anchor).free


def signatures(root: Path) -> dict[str, Any]:
    rows = ps_json(
        f"$root = '{root}'; Get-ChildItem -LiteralPath $root -Recurse -File | "
        "Where-Object { $_.Extension -in '.exe', '.dll', '.pyd' } | ForEach-Object { $s = Get-AuthenticodeSignature -LiteralPath $_.FullName; "
        "[pscustomobject]@{ p = $_.FullName.Substring($root.Length + 1); s = [string]$s.Status; "
        "c = if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { $null } } }",
        timeout=3600) or []
    if isinstance(rows, dict):
        rows = [rows]
    by_status: dict[str, int] = {}
    by_package: dict[str, dict[str, int]] = {}
    for row in rows:
        by_status[row["s"]] = by_status.get(row["s"], 0) + 1
        parts = row["p"].split("\\")
        package = "\\".join(parts[:4]) if parts[:3] == ["runtime", "Lib", "site-packages"] else "\\".join(parts[:2])
        counts = by_package.setdefault(package, {})
        counts[row["s"]] = counts.get(row["s"], 0) + 1
    top = [row for row in rows if "\\" not in row["p"]
           or (row["p"].split("\\")[0] in ("bin", "runtime") and row["p"].count("\\") == 1)]
    return {"by_status": by_status, "by_package": by_package, "top_level": top}


def pe_vcrt(root: Path) -> dict[str, Any]:
    """每個 PE 檔直接（或延遲）import 的 VC++ DLL，以及發布包裡自己附的 VC++ DLL。"""
    try:
        import pefile
    except ImportError:
        return {"error": "沒有 pefile"}
    directories = [pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                   pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]]
    bundled: dict[str, list[str]] = {}
    importers: dict[str, list[dict[str, Any]]] = {}
    errors = []
    scanned = 0
    for dirpath, _dirs, names in os.walk(long(root)):
        for name in names:
            full = os.path.join(dirpath, name)
            rel = full[4 + len(str(root)) + 1:]
            if VCRT.match(name):
                bundled.setdefault(name.lower(), []).append(rel)
            if not name.lower().endswith((".dll", ".pyd", ".exe")):
                continue
            scanned += 1
            try:
                pe = pefile.PE(full, fast_load=True)
                pe.parse_data_directories(directories=directories)
            except Exception as e:  # 壞掉或不是 PE 的檔案：記下來就好
                errors.append({"file": rel, "error": f"{type(e).__name__}: {e}"})
                continue
            for attr, delay in (("DIRECTORY_ENTRY_IMPORT", False), ("DIRECTORY_ENTRY_DELAY_IMPORT", True)):
                for entry in getattr(pe, attr, []):
                    dll = entry.dll.decode("ascii", errors="replace")
                    if VCRT.match(dll):
                        importers.setdefault(dll.lower(), []).append({"file": rel, "delay": delay})
            pe.close()
    summary = {}
    for dll, users in sorted(importers.items()):
        copies = bundled.get(dll, [])
        copy_dirs = {os.path.dirname(c) for c in copies}
        not_beside = [u["file"] for u in users if os.path.dirname(u["file"]) not in copy_dirs]
        summary[dll] = {
            "importers": len(users),
            "bundled_copies": copies,
            "importers_without_copy_beside": len(not_beside),
            "examples_without_copy_beside": not_beside[:25],
        }
    return {"scanned": scanned, "summary": summary, "bundled": bundled, "errors": errors[:20]}


def run_imports(root: Path, label: str) -> dict[str, Any]:
    out = OUT / f"imports-{label}.json"
    script_dir = OUT / "probe"
    script_dir.mkdir(exist_ok=True)
    script = script_dir / "imports.py"
    shutil.copy(HERE / "imports.py", script)
    data_dir = OUT / f"imports-{label}-data"
    data_dir.mkdir(exist_ok=True)
    started = time.time()
    result = run([str(root / "runtime" / "python.exe"), str(script), str(root / "backend"), str(out)],
                 cwd=root / "backend", env=user_env({"AIT_DATA_DIR": str(data_dir)}), timeout=1800)
    record: dict[str, Any] = {"exit_code": result.returncode, "seconds": round(time.time() - started, 1),
                              "stderr_tail": result.stderr.splitlines()[-40:]}
    if out.exists():
        data = json.loads(out.read_text(encoding="utf-8"))
        record["modules"] = [{k: m.get(k) for k in ("module", "ok", "seconds", "version", "error")}
                             for m in data["modules"]]
        record["torch"] = data.get("torch")
        dlls = data.get("loaded_dlls", [])
        windir = os.environ.get("SystemRoot", r"C:\Windows").lower()
        record["vcrt_loaded_from"] = [d for d in dlls if VCRT.match(os.path.basename(d))]
        record["loaded_outside_package_and_windows"] = [
            d for d in dlls if not d.lower().startswith((str(root).lower(), windir))]
        record["loaded_dll_count"] = len(dlls)
    return record


class HiddenVcrt:
    """把 System32 裡 VC++ 執行階段的 DLL 暫時改名，模擬沒裝 VC++ 可轉散發套件的電腦。"""

    def __init__(self) -> None:
        self.moved: list[tuple[Path, Path]] = []
        self.failed: list[str] = []

    def __enter__(self) -> HiddenVcrt:
        for path in sorted(p for p in system32().iterdir() if VCRT.match(p.name)):
            run(["takeown", "/f", str(path)])
            run(["icacls", str(path), "/grant", "*S-1-5-32-544:F"])
            hidden = path.with_name(path.name + ".trial-hidden")
            try:
                os.replace(path, hidden)
                self.moved.append((path, hidden))
            except OSError as e:
                self.failed.append(f"{path.name}: {e}")
        return self

    def __exit__(self, *exc: object) -> None:
        for path, hidden in self.moved:
            with contextlib.suppress(OSError):
                os.replace(hidden, path)


class FakeNvidiaDriver:
    """在 System32 放一個空的 nvcuda.dll，假裝裝了 NVIDIA 驅動：啟動器、start.py 與後端都只看這個檔案
    在不在（#304）。VC++ 拿掉時 torch 在載入 c10.dll 就失敗，不會去載入它。runner 本來就有時不動。"""

    def __init__(self) -> None:
        self.path = system32() / "nvcuda.dll"
        self.created = False

    def __enter__(self) -> FakeNvidiaDriver:
        if not self.path.exists():
            self.path.write_bytes(b"")
            self.created = True
        return self

    def __exit__(self, *exc: object) -> None:
        if self.created:
            with contextlib.suppress(OSError):
                self.path.unlink()


def defender_on() -> dict[str, Any]:
    record: dict[str, Any] = {"before": defender_status()}
    try:
        powershell("Set-MpPreference -DisableRealtimeMonitoring $false")
        record["set"] = "ok"
    except RuntimeError as e:
        record["set"] = str(e)[-500:]
    time.sleep(5)
    record["after"] = defender_status()
    return record


def extract(zip_path: Path, dest: Path) -> dict[str, Any]:
    rmtree(dest)
    started = time.time()
    powershell(f"Expand-Archive -LiteralPath '{zip_path}' -DestinationPath '{dest}' -Force")
    return {"seconds": round(time.time() - started, 1), "dest": str(dest)}


# ─── 摘要 ────────────────────────────────────────────────────────────────

def summary_markdown() -> str:
    r = RESULTS
    lines = ["# 試發布（#35）在 CI Windows runner 上的量測", ""]
    build = r.get("build", {})
    lines += [f"- commit：`{build.get('commit')}`；zip：{build.get('zip_name')}，"
              f"{mb(build.get('zip_bytes'))}（{build.get('zip_bytes')} bytes）", ""]
    env = r.get("environment", {})
    lines += [f"- runner：{(env.get('os') or {}).get('Caption')} {(env.get('os') or {}).get('Version')}，"
              f"RAM {env.get('ram_gb')} GB，磁碟剩餘 {env.get('disk_free_gb')}",
              f"- 長路徑設定（runner 原本）：{env.get('long_paths_enabled')}；VC++ x64："
              f"{env.get('vcredist_x64')}；NVIDIA：{env.get('nvidia')}",
              f"- Defender（runner 原本）：{env.get('defender')}", ""]

    def run_line(title: str, key: str) -> None:
        data = r.get(key, {})
        run_ = data.get("run", {})
        events = run_.get("events", {})
        log = run_.get("launcher_log", {})
        lines.append(f"## {title}")
        lines.append("")
        lines.append(f"- 事件（秒）：{events}")
        lines.append(f"- 經過代理的下載量：{mb((run_.get('proxy') or {}).get('down'))}")
        lines.append(f"- 啟動器日誌：uv {log.get('uv_exit')}；health 就緒 {log.get('ready_seconds')} 秒")
        if run_.get("exit_code") is not None:
            lines.append(f"- 啟動器結束代碼：{run_.get('exit_code')}")
        lines.append(f"- VC++ 提示：{(run_.get('vc_hint') or {}).get('count')} 次")
        hosts = (run_.get("proxy") or {}).get("hosts") or {}
        for host, counts in sorted(hosts.items(), key=lambda kv: -kv[1]["down"]):
            lines.append(f"  - {host}：{mb(counts['down'])}，{counts['connections']} 條連線")
        uv = run_.get("uv_lines") or []
        if uv:
            lines.append("- uv 的輸出（節錄）：")
            lines.append("")
            lines.append("```")
            lines.extend(uv[:60])
            lines.append("```")
        if data.get("error"):
            lines.append(f"- **錯誤**：{data['error']}")
        lines.append("")

    run_line("第一次啟動（冷啟動，首次佈建）", "first_start")
    weights = r.get("weights_download", {})
    lines += ["## 權重下載（沒有顯卡的電腦）", "",
              f"- 結果：{weights.get('final_state')}；{weights.get('seconds')} 秒；經過代理 "
              f"{mb(weights.get('proxy_bytes'))}；hf_cache {gib(weights.get('hf_cache_bytes'))}",
              f"- 下載後的 readiness：{weights.get('readiness_after')}", ""]
    run_line("第二次啟動（熱啟動）", "second_start")
    imports = r.get("imports", {})
    lines += ["## import 探針", "", f"- torch：{imports.get('torch')}"]
    for m in imports.get("modules", []):
        lines.append(f"  - {m['module']}：{'OK' if m['ok'] else '失敗 ' + str(m.get('error'))}，{m['seconds']} 秒")
    lines += [f"- VC++ DLL 從哪裡載入：{imports.get('vcrt_loaded_from')}", ""]
    sizes = r.get("sizes", {})
    lines += ["## 大小與路徑", "",
              f"- 佈建後的資料夾：{gib((sizes.get('root') or {}).get('bytes'))}，"
              f"{(sizes.get('root') or {}).get('files')} 個檔案",
              f"- site-packages：{gib((sizes.get('site_packages') or {}).get('bytes'))}",
              f"- uv 快取：{gib((sizes.get('uv_cache') or {}).get('bytes'))}",
              f"- 最長的路徑：{(sizes.get('root') or {}).get('longest_len')} 字元，"
              f"程式資料夾以下 {sizes.get('longest_relative_len')} 字元：`{(sizes.get('root') or {}).get('longest_path')}`",
              f"- 程式資料夾的路徑最多可以 {sizes.get('max_root_len_for_max_path')} 字元（MAX_PATH 259）",
              f"- data\\models：{[(k, gib(v)) for k, v in sizes.get('models_breakdown') or []]}",
              f"- site-packages 前幾大：{[(k, gib(v)) for k, v in (sizes.get('site_packages_breakdown') or [])[:8]]}",
              f"- uv 快取：{[(k, gib(v)) for k, v in sizes.get('uv_cache_breakdown') or []]}", ""]
    package_sig = r.get("extract", {}).get("signatures") or {}
    lines += ["## 簽章", "", f"- 發布包：{package_sig.get('by_status')}",
              f"- 佈建後：{(r.get('signatures_provisioned') or {}).get('by_status')}"]
    for row in package_sig.get("top_level", []):
        lines.append(f"  - {row['p']}：{row['s']}（{row['c']}）")
    by_package = (r.get("signatures_provisioned") or {}).get("by_package") or {}
    for package, counts in sorted(by_package.items(), key=lambda kv: -sum(kv[1].values()))[:25]:
        lines.append(f"  - {package}：{counts}")
    lines.append("")
    vc = r.get("vcrt", {})
    lines += ["## VC++ 執行階段", "", f"- 靜態分析：{json.dumps((vc.get('static') or {}).get('summary'), ensure_ascii=False)[:3000]}",
              f"- 拿掉 System32 的 VC++ DLL：改名 {vc.get('hidden')}，失敗 {vc.get('hide_failed')}",
              f"- 拿掉之後 import：{[(m['module'], m['ok']) for m in (vc.get('imports') or {}).get('modules', [])]}",
              f"- 拿掉之後 VC++ DLL 從哪裡載入：{(vc.get('imports') or {}).get('vcrt_loaded_from')}",
              f"- 拿掉之後 bin 的程式：{vc.get('binaries')}", ""]
    driver = r.get("vcrt_driver", {})
    lines += ["## VC++ 提示（#304）", "",
              "| 情境 | 啟動方式 | 符合預期 | 提示 | 就緒（秒） | readiness | 診斷資訊 |",
              "|---|---|---|---|---|---|---|"]
    for title, data in (("沒有 VC++、沒有 NVIDIA 驅動", vc),
                        ("沒有 VC++、有 NVIDIA 驅動（假的 nvcuda.dll）", driver)):
        for how, run_key, state_key, expect_key in (("Mimiji.exe", "start", "state", "expect"),
                                                    ("start.bat", "start_bat", "state_bat", "expect_bat")):
            run_ = data.get(run_key) or {}
            state = data.get(state_key) or {}
            expect = data.get(expect_key) or {}
            failed = [k for k, v in (expect.get("checks") or {}).items() if not v]
            verdict = "是" if expect.get("ok") else f"**否**：{failed}" if expect else "沒跑到"
            hint = run_.get("vc_hint") or {}
            hint_text = (f"{hint.get('count')} 次；網址 {hint.get('url')}；佈建前 {hint.get('before_provisioning')}；"
                         f"佈建後再說 {hint.get('again_after_provisioning')}") if hint else ""
            readiness = state.get("readiness") or {}
            lines.append(f"| {title} | {how} | {verdict} | {hint_text} | {(run_.get('events') or {}).get('ready')} | "
                         f"{readiness.get('reason')} | {'；'.join(state.get('diagnostics_gpu') or [])} |")
    lines.append("")
    for data in (vc, driver):
        for run_key in ("start", "start_bat"):
            hint_lines = ((data.get(run_key) or {}).get("vc_hint") or {}).get("lines")
            if hint_lines:
                lines.append(f"- {(data.get(run_key) or {}).get('label')} 的提示：{hint_lines}")
    if driver:
        lines += [f"- 假的 nvcuda.dll：建立 {driver.get('fake_nvcuda_created')}，結束後還在 "
                  f"{driver.get('nvcuda_after')}；System32 的 VC++ 還原為 {driver.get('system32_restored')}"]
    lines.append("")
    run_line("斷網（下載到一半）", "interrupted")
    lines += [f"- 斷網後 uv 快取：{gib((r.get('interrupted', {}).get('uv_cache_after') or {}).get('bytes'))}", ""]
    run_line("恢復網路後再啟動（續傳）", "resumed")
    run_line("在 uv 下載時斷網（#303）", "interrupted_uv")
    run_line("恢復網路後再啟動（#303）", "resumed_uv")
    lines += uv_cache_verdict()
    if r.get("errors"):
        lines += ["## 腳本的錯誤", ""]
        for e in r["errors"]:
            lines.append(f"- {e['phase']}：{e['error']}")
    return "\n".join(lines) + "\n"


def uv_cache_verdict() -> list[str]:
    """#303：uv 的下載快取放在程式資料夾的 runtime\\uv-cache、佈建完清掉，預設的位置不該出現。"""
    r = RESULTS
    first, sizes = r.get("first_start", {}), r.get("sizes", {})
    cut, again = r.get("interrupted_uv", {}), r.get("resumed_uv", {})
    first_run, cut_run, again_run = first.get("run") or {}, cut.get("run") or {}, again.get("run") or {}
    first_total = (first_run.get("events") or {}).get("provisioned_bytes")
    again_down = (again_run.get("proxy") or {}).get("down")
    clean = (first_run.get("launcher_log") or {}).get("uv_cache_clean") or []

    def same(before: Any, after: Any) -> bool:
        # 預設位置的快取：佈建前後不變（runner 原本就沒有時，佈建後也沒有）
        if before is None or after is None:
            return before is None and after is None
        return before.get("bytes") == after.get("bytes") and before.get("files") == after.get("files")

    checks = [
        ("第一次佈建就緒", (first_run.get("events") or {}).get("ready") is not None),
        ("佈建完成後印出「正在清掉首次佈建時暫存的檔案」", first_run.get("uv_cache_cleaning_shown") is True),
        ("啟動器日誌：清快取的 uv 結束代碼 0", bool(clean) and clean[0].get("code") == "0"),
        ("第一次佈建後 runtime\\uv-cache 不在", first.get("package_uv_cache_after") is None),
        ("第一次佈建前後 %LOCALAPPDATA%\\uv\\cache 沒有變",
         same(first.get("default_uv_cache_before"), first.get("default_uv_cache_after"))),
        ("熱啟動之後 runtime\\uv-cache 也不在", sizes.get("package_uv_cache") is None),
        ("代理在 uv 從 PyPI 下載時斷網", cut.get("cut_at") is not None),
        ("在 uv 下載時斷網：啟動器停下、沒寫完成標記",
         cut_run.get("exit_code") not in (None, 0) and cut.get("sentinel_exists") is False),
        ("斷網後 runtime\\uv-cache 留著（已下載的套件）",
         bool((cut.get("package_uv_cache_after") or {}).get("bytes"))),
        ("斷網後 %LOCALAPPDATA%\\uv\\cache 沒有出現",
         cut.get("default_uv_cache_before") is None and cut.get("default_uv_cache_after") is None),
        ("恢復網路後就緒、寫了完成標記",
         (again_run.get("events") or {}).get("ready") is not None and again.get("sentinel_exists") is True),
        ("恢復網路後只補下載剩下的（不到第一次的一成）",
         bool(first_total) and again_down is not None and again_down < first_total * 0.1),
        ("恢復網路、佈建完成後 runtime\\uv-cache 清掉", again.get("package_uv_cache_after") is None),
        ("恢復網路後 %LOCALAPPDATA%\\uv\\cache 沒有出現", again.get("default_uv_cache_after") is None),
    ]
    free_before, free_after = first.get("disk_free_before"), first.get("disk_free_after")
    lines = ["## uv 的下載快取（#303）", "", "| 檢查 | 結果 |", "|---|---|"]
    lines += [f"| {name} | {'通過' if ok else '**沒通過**'} |" for name, ok in checks]
    lines += ["",
              f"- 第一次佈建：清快取 {clean}；磁碟可用空間少了 "
              f"{gib(free_before - free_after) if free_before is not None and free_after is not None else None}"
              f"（含日誌等其他檔案）",
              f"- %LOCALAPPDATA%\\uv\\cache：第一次佈建前 {first.get('default_uv_cache_before')}，"
              f"後 {first.get('default_uv_cache_after')}",
              f"- 在 uv 下載時斷網：{cut.get('cut')}，代理在第 {cut.get('cut_at')} 秒斷網；"
              f"斷網時總共下載 {mb((cut_run.get('events') or {}).get('blackhole_bytes'))}；runtime\\uv-cache "
              f"{gib((cut.get('package_uv_cache_after') or {}).get('bytes'))}，"
              f"{(cut.get('package_uv_cache_after') or {}).get('files')} 個檔案；runtime\\downloads "
              f"{gib((cut.get('downloads_after') or {}).get('bytes'))}",
              f"- 恢復網路後下載 {mb(again_down)}（第一次 {mb(first_total)}）",
              f"- **{'全部通過' if all(ok for _, ok in checks) else '有沒通過的項目'}**", ""]
    return lines


# ─── 主流程 ──────────────────────────────────────────────────────────────

def stop(process: subprocess.Popen[bytes] | None, root: Path) -> None:
    if process is not None:
        kill_tree(process, root)


def main() -> int:
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--commit", default="")
    args = parser.parse_args()
    OUT = args.out.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    zip_path = args.zip.resolve()
    RESULTS["build"] = {"commit": args.commit, "zip_name": zip_path.name,
                        "zip_bytes": zip_path.stat().st_size}
    downloads = Path(os.environ["USERPROFILE"]) / "Downloads"
    downloads.mkdir(exist_ok=True)
    user_zip = downloads / zip_path.name
    shutil.copy(zip_path, user_zip)
    dest = downloads / zip_path.stem
    root = dest / "Mimiji"
    original_long_paths = registry_value(LONG_PATHS_KEY, "LongPathsEnabled")

    with phase("environment") as record:
        environment(record)

    with phase("extract") as record:
        record.update(extract(user_zip, dest))
        record["signatures"] = signatures(root)

    proxy = Proxy("first")
    process: subprocess.Popen[bytes] | None = None
    with phase("first_start") as record:
        set_long_paths(False)
        record["long_paths_enabled"] = registry_value(LONG_PATHS_KEY, "LongPathsEnabled")
        record["default_uv_cache_before"] = maybe_stats(uv_cache())
        record["disk_free_before"] = disk_free(root)
        proxy.start()
        record["run"], process = run_launcher(root, "first", proxy)
        # 就緒時佈建與清快取都做完了（啟動器先清快取才啟動伺服器）
        record["disk_free_after"] = disk_free(root)
        record["package_uv_cache_after"] = maybe_stats(package_uv_cache(root))
        record["default_uv_cache_after"] = maybe_stats(uv_cache())
        if process is not None:
            record["probe"] = probe(record["run"]["url"])

    with phase("weights_download") as record:
        if process is None:
            raise RuntimeError("第一次啟動沒有就緒，跳過")
        base = RESULTS["first_start"]["run"]["url"]
        before = proxy.down()
        nic_before = nic_received()
        started = time.time()
        status, body = http("POST", base + "/api/v1/setting/local-models/download")
        record["start_response"] = {"status": status, "body": body[:500].decode("utf-8", errors="replace")}
        samples = []
        state = None
        while time.time() - started < WEIGHTS_TIMEOUT_SECONDS:
            time.sleep(5)
            status, body = http("GET", base + "/api/v1/setting/local-models/status")
            with contextlib.suppress(ValueError):
                download = json.loads(body).get("download") or {}
                state = download.get("state")
                samples.append([round(time.time() - started), proxy.down() - before,
                                download.get("downloaded_bytes"), state])
                if state in ("completed", "failed"):
                    record["final_status"] = json.loads(body)
                    break
        record["final_state"] = state
        record["seconds"] = round(time.time() - started, 1)
        record["proxy_bytes"] = proxy.down() - before
        nic_after = nic_received()
        if nic_before is not None and nic_after is not None:
            record["nic_received_bytes"] = nic_after - nic_before
        record["samples"] = samples[::6]
        record["hf_cache_bytes"] = tree_stats(root / "data" / "models")["bytes"]
        status, body = http("GET", base + "/api/v1/setting/local-models/readiness")
        record["readiness_after"] = body[:800].decode("utf-8", errors="replace")
        status, body = http("GET", base + "/api/v1/diagnostics")
        record["diagnostics_after"] = body[:3000].decode("utf-8", errors="replace")

    stop(process, root)
    copy_logs(root, "first")
    proxy.stop()

    with phase("second_start") as record:
        proxy = Proxy("second")
        proxy.start()
        record["run"], process = run_launcher(root, "second", proxy)
        stop(process, root)
        proxy.stop()

    with phase("imports") as record:
        record.update(run_imports(root, "normal"))

    set_long_paths(True)
    with phase("sizes") as record:
        record["root"] = tree_stats(root)
        record["site_packages"] = tree_stats(root / "runtime" / "Lib" / "site-packages")
        record["models"] = tree_stats(root / "data" / "models")
        record["uv_cache"] = maybe_stats(uv_cache())
        record["package_uv_cache"] = maybe_stats(package_uv_cache(root))
        record["models_breakdown"] = breakdown(root / "data" / "models", 3)
        record["site_packages_breakdown"] = breakdown(root / "runtime" / "Lib" / "site-packages", 1)
        record["uv_cache_breakdown"] = breakdown(uv_cache(), 1) if uv_cache().exists() else []
        record["longest_relative_len"] = record["root"]["longest_len"] - len(str(root)) - 1
        record["max_root_len_for_max_path"] = 259 - record["longest_relative_len"] - 1
        record["root_path_len"] = len(str(root))

    with phase("signatures_provisioned") as record:
        record.update(signatures(root))

    with phase("vcrt") as record:
        record["static"] = pe_vcrt(root)
        set_long_paths(False)
        proxy = Proxy("vcrt")
        proxy.start()
        try:
            with HiddenVcrt() as hidden:
                record["hidden"] = [p.name for p, _ in hidden.moved]
                record["hide_failed"] = hidden.failed
                record["system32_after_hide"] = vcrt_in_system32()
                record["imports"] = run_imports(root, "no-vcrt")
                record["binaries"] = {}
                for exe, flag in (("uv.exe", "--version"), ("ffmpeg.exe", "-version"), ("ffprobe.exe", "-version")):
                    result = run([str(root / "bin" / exe), flag], timeout=120)
                    record["binaries"][exe] = {"exit_code": result.returncode,
                                               "first_line": (result.stdout or result.stderr).splitlines()[:1]}
                record["nvcuda_dll"] = (system32() / "nvcuda.dll").exists()
                # runner 沒有 NVIDIA 驅動：Mimiji.exe 與 start.bat 都不該提示 VC++，
                # 診斷資訊先說顯卡（#304）
                record["start"], process = run_launcher(root, "no-vcrt", proxy)
                if process is not None:
                    record["state"] = local_state(record["start"]["url"])
                stop(process, root)
                record["expect"] = expect_vc(record["start"], record.get("state"), driver=False)
                record["start_bat"], process = run_start_bat(root, "no-vcrt-bat", proxy)
                if process is not None:
                    record["state_bat"] = local_state(record["start_bat"]["url"])
                stop(process, root)
                record["expect_bat"] = expect_vc(record["start_bat"], record.get("state_bat"), driver=False)
            record["system32_restored"] = vcrt_in_system32()
        finally:
            proxy.stop()
            set_long_paths(True)

    with phase("vcrt_driver") as record:
        set_long_paths(False)
        proxy = Proxy("vcrt-driver")
        proxy.start()
        try:
            sentinel = root / "runtime" / ".provisioned"
            with HiddenVcrt() as hidden, FakeNvidiaDriver() as fake:
                record["hidden"] = [p.name for p, _ in hidden.moved]
                record["hide_failed"] = hidden.failed
                record["fake_nvcuda_created"] = fake.created
                # 刪掉佈建完成的標記：重跑一次佈建（套件都在，uv 只檢查），看提示是不是在佈建之前
                sentinel.unlink(missing_ok=True)
                record["start"], process = run_launcher(root, "no-vcrt-driver", proxy)
                if process is not None:
                    record["state"] = local_state(record["start"]["url"])
                stop(process, root)
                record["expect"] = expect_vc(record["start"], record.get("state"), driver=True)
                record["sentinel_after_exe"] = sentinel.exists()
                sentinel.unlink(missing_ok=True)
                record["start_bat"], process = run_start_bat(root, "no-vcrt-driver-bat", proxy)
                if process is not None:
                    record["state_bat"] = local_state(record["start_bat"]["url"])
                stop(process, root)
                record["expect_bat"] = expect_vc(record["start_bat"], record.get("state_bat"), driver=True)
                record["sentinel_after_bat"] = sentinel.exists()
            record["system32_restored"] = vcrt_in_system32()
            record["nvcuda_after"] = (system32() / "nvcuda.dll").exists()
        finally:
            proxy.stop()
            set_long_paths(True)

    with phase("interrupted") as record:
        clean = run([str(root / "bin" / "uv.exe"), "cache", "clean"], env=user_env(), timeout=1800)
        record["uv_cache_clean"] = {"exit_code": clean.returncode, "tail": clean.stderr.splitlines()[-5:]}
        rmtree(dest)
        rmtree(uv_cache())
        record["uv_cache_before"] = tree_stats(uv_cache()) if uv_cache().exists() else None
        record["defender"] = defender_on()
        record["extract"] = extract(user_zip, dest)
        set_long_paths(False)
        proxy = Proxy("interrupted")
        proxy.start()
        first_total = ((RESULTS["first_start"].get("run") or {}).get("events") or {}).get("provisioned_bytes")
        interrupt_at = int(first_total * 0.45) if first_total else INTERRUPT_AT_BYTES
        record["interrupt_at_bytes"] = interrupt_at
        record["run"], process = run_launcher(root, "interrupted", proxy, interrupt_at=interrupt_at)
        stop(process, root)
        proxy.stop()
        record["sentinel_exists"] = (root / "runtime" / ".provisioned").exists()
        record["uv_cache_after"] = tree_stats(uv_cache()) if uv_cache().exists() else None
        record["package_uv_cache_after"] = maybe_stats(package_uv_cache(root))
        record["site_packages_after"] = tree_stats(root / "runtime" / "Lib" / "site-packages")
        copy_logs(root, "interrupted")

    with phase("resumed") as record:
        proxy = Proxy("resumed")
        proxy.start()
        record["run"], process = run_launcher(root, "resumed", proxy)
        if process is not None:
            status, _ = http("GET", record["run"]["url"] + "/api/v1/health")
            record["health"] = status
        stop(process, root)
        proxy.stop()
        record["defender_after"] = defender_status()
        record["package_uv_cache_after"] = maybe_stats(package_uv_cache(root))
        record["default_uv_cache_after"] = maybe_stats(uv_cache())
        copy_logs(root, "resumed")

    # 12. 在 uv 下載時斷網（#303）：PyTorch（約九成的下載量）預先下載完之後才斷
    with phase("interrupted_uv") as record:
        rmtree(dest)
        record["default_uv_cache_before"] = maybe_stats(uv_cache())
        record["extract"] = extract(user_zip, dest)
        set_long_paths(False)
        # PyPI 的套件只有 uv 下載（PyTorch 由 prefetch_wheels.py 從 download.pytorch.org 下載）：
        # 從 PyPI 下載到 CUT_PYPI_BYTES 時代理自己斷網，這時 uv 已經下載完一部分、還沒下載完全部
        proxy = Proxy("interrupted-uv", cut_host=PYPI_FILES_HOST, cut_after=CUT_PYPI_BYTES)
        proxy.start()
        record["cut"] = {"host": PYPI_FILES_HOST, "after_bytes": CUT_PYPI_BYTES}
        record["run"], process = run_launcher(root, "interrupted-uv", proxy)
        record["cut_at"] = (record["run"].get("proxy") or {}).get("cut_at")
        stop(process, root)
        proxy.stop()
        record["sentinel_exists"] = (root / "runtime" / ".provisioned").exists()
        record["downloads_after"] = maybe_stats(root / "runtime" / "downloads")
        record["package_uv_cache_after"] = maybe_stats(package_uv_cache(root))
        record["default_uv_cache_after"] = maybe_stats(uv_cache())
        copy_logs(root, "interrupted-uv")

    with phase("resumed_uv") as record:
        proxy = Proxy("resumed-uv")
        proxy.start()
        record["run"], process = run_launcher(root, "resumed-uv", proxy)
        if process is not None:
            status, _ = http("GET", record["run"]["url"] + "/api/v1/health")
            record["health"] = status
        stop(process, root)
        proxy.stop()
        record["sentinel_exists"] = (root / "runtime" / ".provisioned").exists()
        record["package_uv_cache_after"] = maybe_stats(package_uv_cache(root))
        record["default_uv_cache_after"] = maybe_stats(uv_cache())
        copy_logs(root, "resumed-uv")

    if original_long_paths is not None:
        set_long_paths(bool(original_long_paths))
    text = summary_markdown()
    (OUT / "summary.md").write_text(text, encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(text)
    print(text)
    save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
