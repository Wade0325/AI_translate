"""整合測試（只在 Windows）：start.py（tools/portable/start.py，#267）被單獨結束時，伺服器跟著結束。

start.py 把伺服器放進「關閉時結束全部」的 Job Object，和啟動器相同。沒有的話，在工作管理員只結束
start.py 時伺服器留著跑，單一實例卻已讓出：下一個 start.bat 照常啟動，先把那個伺服器正在轉錄的任務
記成失敗才綁不到埠（#267 在 Windows 10 上實測到）。
"""
from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="要 Windows：Job Object")

# 在另一個行程執行 start.run_server。伺服器換成一個把自己的行程編號寫進檔案、然後一直等的 Python
HOST = r'''
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from tools.portable import start

SERVER = ("import os, pathlib, sys, time; "
          "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(120)")
start.server_command = lambda root, port: [sys.executable, "-c", SERVER, sys.argv[2]]
start.run_server(Path(sys.argv[3]), 8267)
'''


def _alive(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def _wait(condition, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "等太久"
        time.sleep(0.1)


def test_server_stops_when_start_py_is_killed(tmp_path):
    (tmp_path / "backend").mkdir()
    host, pid_file = tmp_path / "host.py", tmp_path / "server.pid"
    host.write_text(HOST, encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(host), str(ROOT), str(pid_file), str(tmp_path)])
    server = None
    try:
        _wait(lambda: pid_file.exists() and pid_file.read_text(encoding="ascii").strip() != "")
        server = int(pid_file.read_text(encoding="ascii"))
        time.sleep(0.5)  # 伺服器寫檔之前 start.py 就已經把它放進 Job Object；多等一下保險
        assert _alive(server)

        proc.kill()  # TerminateProcess：和在工作管理員結束 start.py 相同
        proc.wait()

        _wait(lambda: not _alive(server), timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if server is not None and _alive(server):
            os.kill(server, signal.SIGTERM)  # 測試失敗時也不留下行程（Windows 上是 TerminateProcess）
