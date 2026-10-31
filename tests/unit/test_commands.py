"""執行外部指令只拿標準輸出：問不到時（沒裝、失敗、卡住）一律是 None，呼叫的地方照樣往下走。"""
import sys

from app.utils import commands
from app.utils.commands import command_output


def test_returns_the_output():
    assert command_output(sys.executable, "-c", "print('576.02')") == "576.02\n"


def test_missing_command():
    assert command_output("no-such-command-for-diagnostics") is None


def test_failed_command():
    assert command_output(sys.executable, "-c", "import sys; sys.exit(9)") is None


def test_command_that_hangs(monkeypatch):
    monkeypatch.setattr(commands, "TIMEOUT_SECONDS", 0.5)

    assert command_output(sys.executable, "-c", "import time; time.sleep(30)") is None
