"""執行期資料夾不能被打包進 Docker 映像或免安裝版。

Docker 模式與從原始碼執行時，上傳暫存、去靜音的除錯產物與保留的音檔，都以 cwd 相對路徑
寫在 backend/ 底下（config.py 的 temp_uploads_dir、vad_artifacts_dir、audio_store_dir）。

- backend/Dockerfile 是 `COPY . .`：靠 backend/.dockerignore 排除，漏掉其中一個，重建映像時
  使用者的音檔就會被一起打包進去。
- build_release.ps1 只用 git archive 取後端白名單（$BackendPaths）裡已 commit 的檔案（#266）：
  沒進版控的執行期資料進不了發布包。這裡檢查白名單取得到的檔案裡沒有執行期資料，
  以及取檔的方式沒有被換回從工作目錄複製。

資料夾名稱一律從 config.py 的預設值取得，改名時 .dockerignore 要跟著改，這裡會紅燈提醒。
CI 建置免安裝版之後的 zip 檢查（tools/portable_zip.py，#256）也要認得這些名稱，而且建置前
要真的放一份進 backend/，取檔的方式出錯時 CI 才會紅燈。
"""
import re
import subprocess
from pathlib import Path, PurePosixPath

import pytest

from app.core.config import Settings
from tools import portable_zip

ROOT = Path(__file__).resolve().parents[2]

RUNTIME_DIR_FIELDS = ("temp_uploads_dir", "vad_artifacts_dir", "audio_store_dir")


def _runtime_dirs() -> list[str]:
    return [Settings.model_fields[name].default for name in RUNTIME_DIR_FIELDS]


def _dockerignore_patterns() -> list[str]:
    text = (ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8-sig")
    lines = (line.strip() for line in text.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _build_script() -> str:
    return (ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")


def _release_backend_files() -> list[str]:
    """build_release.ps1 會打包的後端檔案：白名單（$BackendPaths）裡進了版控的檔案。"""
    paths = portable_zip.backend_paths(_build_script())
    listed = subprocess.run(["git", "ls-files", "-z", "--", *paths], cwd=ROOT,
                            capture_output=True, check=True).stdout
    files = [name for name in listed.decode("utf-8").split("\0") if name]
    assert files, f"後端白名單在 git 裡沒有任何檔案：{paths}"
    return files


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
def test_release_package_takes_nothing_from_runtime_dir(field):
    name = Settings.model_fields[field].default
    inside = [f for f in _release_backend_files() if name in PurePosixPath(f).parts]
    assert not inside, f"build_release.ps1 的後端白名單會把 {name} 裡的檔案打包：{inside}"


def test_release_backend_files_have_no_runtime_data():
    # 白名單裡進了版控的檔案，zip 檢查（tools/portable_zip.py）都要放行：
    # 有人把 .env、資料庫或音檔 commit 進白名單的路徑時，在這裡就紅燈，不必等 CI 建置
    leaked = {f: reason for f in _release_backend_files()
              if (reason := portable_zip.runtime_data(f))}
    assert not leaked, f"build_release.ps1 的後端白名單會打包這些執行期資料：{leaked}"


def test_release_backend_comes_from_git_archive_of_the_whitelist():
    # 從工作目錄複製 backend/（robocopy、Copy-Item）會把沒進版控的東西一起帶進去
    script = _build_script()
    assert re.search(r"^git -C \$Root archive .* HEAD -- \$BackendPaths$", script, re.M), (
        "build_release.ps1 的後端要用 git archive 取 $BackendPaths 已 commit 的版本")
    assert not re.search(r'Join-Path \$Root "backend"', script), (
        "build_release.ps1 又從工作目錄取 backend/：後端只能從 git archive 取")


@pytest.mark.parametrize("field", RUNTIME_DIR_FIELDS)
def test_portable_zip_check_rejects_runtime_dir(field):
    name = Settings.model_fields[field].default
    assert name in portable_zip.RUNTIME_DIRS, (
        f"tools/portable_zip.py 的 RUNTIME_DIRS 沒有 {name}：CI 檢查 zip 時認不出來")


@pytest.mark.parametrize("field", RUNTIME_DIR_FIELDS)
def test_ci_plants_runtime_dir_before_building(field):
    name = Settings.model_fields[field].default
    planted = [p for p in portable_zip.PLANTED if p.startswith(f"backend/{name}/")]
    assert planted, (
        f"tools/portable_zip.py 的 PLANTED 沒有 backend/{name}/ 底下的檔案：CI 建置前沒放，"
        "排除清單漏掉它也不會紅燈")
