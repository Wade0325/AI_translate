"""執行期資料夾不能被打包進 Docker 映像或免安裝包。

backend/Dockerfile 是 `COPY . .`，build_release.ps1 以 robocopy 複製整個 backend/。
Docker 模式與從原始碼執行時，上傳暫存、去靜音的除錯產物與保留的音檔，都以 cwd 相對路徑
寫在 backend/ 底下（config.py 的 temp_uploads_dir、vad_artifacts_dir、audio_store_dir）。
任一份排除清單漏掉其中一個，重建映像或打包時，使用者的音檔就會被一起打包進去。

資料夾名稱一律從 config.py 的預設值取得，改名時兩份排除清單要跟著改，這裡會紅燈提醒。
"""
import re
from pathlib import Path

import pytest

from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]

RUNTIME_DIR_FIELDS = ("temp_uploads_dir", "vad_artifacts_dir", "audio_store_dir")


def _runtime_dirs() -> list[str]:
    return [Settings.model_fields[name].default for name in RUNTIME_DIR_FIELDS]


def _dockerignore_patterns() -> list[str]:
    text = (ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8-sig")
    lines = (line.strip() for line in text.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _release_backend_excluded_dirs() -> list[str]:
    """build_release.ps1 複製 backend/ 時，robocopy /XD 之後列出的資料夾。"""
    text = (ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")
    match = re.search(
        r'Copy-Tree \(Join-Path \$Root "backend"\).*?@\((.*?)\)', text, re.S)
    assert match, "build_release.ps1 裡找不到複製 backend/ 的 Copy-Tree"
    args = re.findall(r'"([^"]*)"', match.group(1))
    assert "/XD" in args, "複製 backend/ 的 Copy-Tree 沒有 /XD 排除清單"
    start = args.index("/XD") + 1
    end = next((i for i in range(start, len(args)) if args[i].startswith("/")),
               len(args))
    return args[start:end]


def test_runtime_dir_names_come_from_config():
    assert _runtime_dirs() == ["temp_uploads", "vad_artifacts", "audio_store"]


@pytest.mark.parametrize("field", RUNTIME_DIR_FIELDS)
def test_backend_dockerignore_excludes_runtime_dir(field):
    name = Settings.model_fields[field].default
    patterns = _dockerignore_patterns()
    # .dockerignore 以 context（backend/）的根目錄比對；這幾種寫法都排除整個資料夾
    accepted = {name, f"{name}/", f"/{name}", f"/{name}/", f"**/{name}", f"**/{name}/"}
    assert accepted & set(patterns), f"backend/.dockerignore 沒有排除 {name}/"
    reincluded = [p for p in patterns if p.startswith("!") and name in p]
    assert not reincluded, f"backend/.dockerignore 又把 {name} 加回來：{reincluded}"


@pytest.mark.parametrize("field", RUNTIME_DIR_FIELDS)
def test_release_package_excludes_runtime_dir(field):
    name = Settings.model_fields[field].default
    assert name in _release_backend_excluded_dirs(), (
        f"build_release.ps1 複製 backend/ 時沒有用 /XD 排除 {name}")
