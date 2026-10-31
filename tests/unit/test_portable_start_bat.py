"""免安裝版的 start.bat 與 README.txt（#267），內容在 tools/portable/，build_release.ps1 放進發布包。

start.bat 是防毒軟體攔下 AI_Translate.exe 時的手動啟動，要和啟動器（tools/launcher.cs）做一樣的事：
設一樣的環境變數，用一樣的指令佈建與啟動。兩邊各寫一份（cmd 與 C#），這裡檢查沒有分岔。
發布包裡的換行與 BOM 由 CI 檢查 zip（tools/portable_zip.py）：build_release.ps1 寫檔時才轉成 CRLF。
"""
import re
from pathlib import Path, PureWindowsPath

from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
PORTABLE = ROOT / "tools" / "portable"

# 啟動器設給伺服器的環境變數。路徑以發布包的根目錄為基準：start.bat 寫成 %ROOT%<路徑>
SERVER_ENV = {
    "APP_MODE": "standalone",
    "AIT_DATA_DIR": "data",
    "AIT_FFMPEG_DIR": "bin",
    "AIT_STATIC_DIR": r"frontend\dist",
    "HF_HOME": r"data\models\hf_cache",
    "PYTHONIOENCODING": "utf-8",
}


def _launcher() -> str:
    return (ROOT / "tools" / "launcher.cs").read_text(encoding="utf-8-sig")


def _bat() -> str:
    return (PORTABLE / "start.bat").read_text(encoding="utf-8")


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


def _bat_env() -> dict[str, str]:
    """start.bat 用 set "名稱=值" 設的變數；%ROOT%（發布包的根目錄，結尾有 \\）拿掉。"""
    return {name: value.replace("%ROOT%", "")
            for name, value in re.findall(r'^set "(\w+)=([^"]*)"\s*$', _bat(), re.M)}


class TestStartBatMatchesLauncher:
    def test_launcher_sets_these_variables(self):
        # 啟動器多設或改了一個變數時這裡紅燈：start.bat 與 SERVER_ENV 一起改
        assert _launcher_env() == SERVER_ENV

    def test_start_bat_sets_the_same_variables(self):
        env = _bat_env()

        assert {name: env.get(name) for name in SERVER_ENV} == SERVER_ENV

    def test_hf_home_is_where_config_puts_it_without_the_variable(self, monkeypatch):
        # 沒設 HF_HOME 時，免安裝模式的預設也在資料目錄的同一個位置（config.py 的 _default_hf_home）。
        # 別的測試 import 過 provider/local/weights.py 時，它已經替這個行程設了 HF_HOME
        monkeypatch.delenv("HF_HOME", raising=False)
        data = Path("X:/pkg/data")
        default = Path(Settings(_env_file=None, app_mode="standalone", data_dir=str(data)).hf_home)
        set_by_bat = PureWindowsPath(SERVER_ENV["HF_HOME"]).relative_to(SERVER_ENV["AIT_DATA_DIR"])

        assert default.relative_to(data).parts == set_by_bat.parts

    def test_same_server_command(self):
        launcher = _launcher()
        command = re.search(r'"(-m uvicorn [^"]*)\{0\}"', launcher)
        assert command, "tools/launcher.cs 裡找不到啟動 uvicorn 的參數"
        assert "psi.WorkingDirectory = backend;" in launcher

        bat = _bat()
        assert f'"%PYTHON%" {command.group(1)}%PORT%' in bat
        assert 'cd /d "%ROOT%backend"' in bat

    def test_same_provisioning(self):
        # 佈建的指令與完成標記相同：用哪一個啟動，另一個都認得已經佈建好
        launcher = _launcher()
        assert r'"pip install --python \"{0}\" --target \"{1}\" -r \"{2}\""' in launcher
        assert 'Path.Combine(root, "runtime", "Lib", "site-packages")' in launcher
        assert 'Path.Combine(root, "backend", "requirements-standalone.txt")' in launcher
        assert 'Path.Combine(root, "runtime", ".provisioned")' in launcher

        bat = _bat()
        assert (r'"%ROOT%bin\uv.exe" pip install --python "%PYTHON%" '
                r'--target "%ROOT%runtime\Lib\site-packages" '
                r'-r "%ROOT%backend\requirements-standalone.txt"') in bat
        assert r'if exist "%ROOT%runtime\.provisioned" goto :run' in bat
        assert r'> "%ROOT%runtime\.provisioned" echo' in bat


class TestStartBatFormat:
    def test_first_two_lines_are_ascii_without_bom(self):
        # 中文要等第二行的 chcp 65001 之後，cmd 才用 UTF-8 讀；BOM 會黏在第一行的指令上
        data = (PORTABLE / "start.bat").read_bytes()
        assert not data.startswith(b"\xef\xbb\xbf")
        first, second = data.splitlines()[:2]
        assert (first, second) == (b"@echo off", b"chcp 65001 > nul")

    def test_no_parenthesized_blocks(self):
        # 括號區塊裡 echo 的半形右括號會提早結束區塊，%ERRORLEVEL% 也在進區塊時就展開；一律用 goto
        assert not re.search(r"\(\s*$", _bat(), re.M)

    def test_failures_pause_before_the_window_closes(self):
        # 雙擊執行時，失敗後視窗不能直接關掉，使用者才看得到原因
        bat = _bat()
        fail = bat[bat.index(":fail"):]
        assert "pause" in fail


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
