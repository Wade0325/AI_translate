"""tools/portable_zip.py：CI 建置免安裝版之後的 zip 檢查（#256）。

CI 的 portable job 在 Windows 上真的建置一次；這裡用自己做的 zip 測檢查本身：結構對的 zip
要過，缺檔、空檔、最上層不對、名稱不是 Mimiji、夾帶執行期資料、後端有白名單以外檔案的 zip 要擋下來。
plant 放的每一個檔案都要被擋，否則 CI 放了也考不到取檔的那一步。exe 的版本資訊與圖示（#277）用假的
讀取結果測判斷；真的 exe 在 tests/integration/test_launcher_details.py 讀。
"""
import re
import zipfile
from pathlib import Path

import pytest

from tools import portable_zip, release_assets
from tools.portable import start

ROOT = Path(__file__).resolve().parents[2]
TOP = "Mimiji"
VERSION = "ci"
ZIP = f"Mimiji-{VERSION}-win64.zip"


def _script() -> str:
    return (ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")


def _required() -> list[str]:
    return portable_zip.required_files(_script())


def _backend() -> list[str]:
    return portable_zip.backend_paths(_script())


def _check(archive: Path) -> list[str]:
    return portable_zip.check(archive, _required(), _backend())


def _zip(path: Path, names: list[str], *, sep: str = "/", empty: tuple[str, ...] = (),
         version: str = VERSION) -> Path:
    """在 path 做一個 zip：names 是 zip 裡的路徑（用 /），empty 裡的寫成空檔；backend/VERSION 寫 version。"""
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            data = b"" if name in empty else (version.encode() if name.endswith("/VERSION") else b"x")
            archive.writestr(name.replace("/", sep), data)
    return path


def _good(*extra: str) -> list[str]:
    """build_release.ps1 的必要檔案都在的發布包，再加上 extra（最上層資料夾以下的路徑）。"""
    return [f"{TOP}/{rel}" for rel in [*_required(), "backend/app/__init__.py", *extra]]


class TestRequiredFiles:
    def test_reads_step_7_of_build_script(self):
        required = _required()

        # 路徑改用 /，和 zip 的寫法一致
        assert "Mimiji.exe" in required
        assert "runtime/python.exe" in required
        assert "backend/main.py" in required
        assert "frontend/dist/index.html" in required
        assert all("\\" not in rel for rel in required)

    def test_missing_list_is_an_error_not_an_empty_check(self):
        with pytest.raises(ValueError, match="必要檔案清單"):
            portable_zip.required_files('$Other = @("a")\n')


class TestBackendPaths:
    def test_reads_whitelist_of_build_script(self):
        # 執行需要的：程式進入點、程式本身、首次佈建的依賴清單
        assert _backend() == [
            "backend/main.py",
            "backend/requirements-standalone.txt",
            "backend/app",
        ]

    def test_every_required_backend_file_is_whitelisted_or_generated(self):
        # 第 7 步要求的後端檔案，第 4 步要真的取得到
        for rel in _required():
            if rel.startswith("backend/"):
                assert rel in portable_zip.BACKEND_GENERATED or any(
                    rel == path or rel.startswith(f"{path}/") for path in _backend()), rel

    def test_missing_list_is_an_error_not_an_empty_check(self):
        with pytest.raises(ValueError, match="後端白名單"):
            portable_zip.backend_paths('$required = @("a")\n')


class TestCheck:
    def test_complete_package_passes(self, tmp_path):
        archive = _zip(tmp_path / ZIP, _good())

        assert _check(archive) == []

    def test_backslash_separators_from_powershell_5_pass(self, tmp_path):
        # Windows PowerShell 5.1 的 Compress-Archive 用 \ 當 zip 裡的分隔符號
        archive = _zip(tmp_path / ZIP, _good(), sep="\\")

        assert _check(archive) == []

    def test_lookalike_source_files_pass(self, tmp_path):
        # 名稱像執行期資料、其實是原始碼或隨包的執行環境
        archive = _zip(tmp_path / ZIP, _good(
            "backend/app/services/audio_store.py",
            "backend/app/.env.example",
            "runtime/sqlite3.dll",
            "runtime/_sqlite3.pyd",
            "frontend/dist/assets/data.js",
        ))

        assert _check(archive) == []

    def test_missing_and_empty_required_files_fail(self, tmp_path):
        names = [n for n in _good() if n != f"{TOP}/bin/ffmpeg.exe"]
        archive = _zip(tmp_path / ZIP, names, empty=(f"{TOP}/Mimiji.exe",))

        # 照 build_release.ps1 清單的順序列出
        assert _check(archive) == [
            f"必要的檔案是空的：{TOP}/Mimiji.exe",
            f"缺少必要的檔案：{TOP}/bin/ffmpeg.exe",
        ]

    def test_files_outside_a_single_top_folder_fail(self, tmp_path):
        archive = _zip(tmp_path / ZIP, [*_good(), "README.txt"])

        problems = _check(archive)

        assert problems == [f"zip 的最上層應該剛好是一個資料夾，實際是：{TOP}、README.txt"]

    def test_empty_zip_fails(self, tmp_path):
        archive = _zip(tmp_path / ZIP, [])

        assert _check(archive) == ["zip 是空的"]

    @pytest.mark.parametrize("planted", portable_zip.PLANTED)
    def test_every_planted_file_fails(self, tmp_path, planted):
        # CI 在建置前放進這些檔案：沒被排除而進了 zip，就要紅燈
        archive = _zip(tmp_path / ZIP, _good(planted))

        problems = _check(archive)

        assert len(problems) == 1
        assert problems[0].startswith(f"不該打包：{TOP}/{planted}（")

    @pytest.mark.parametrize("leaked, reason", [
        ("backend/audio_store/x", "使用者的音檔"),
        ("backend/.env.local", "API 金鑰"),
        ("backend/app.db-wal", "SQLite"),
        ("backend/app.log", "日誌檔"),
        ("backend/app/services/foo.pyc", "Python 的快取"),
        ("data/logs/app-2026-10-31.log", "資料目錄"),
    ])
    def test_problem_says_why_the_file_must_not_ship(self, tmp_path, leaked, reason):
        archive = _zip(tmp_path / ZIP, _good(leaked))

        (problem,) = _check(archive)

        assert reason in problem

    def test_folder_entries_leading_to_whitelisted_paths_pass(self, tmp_path):
        # zip 可能為資料夾寫一個項目（結尾是 /）
        archive = _zip(tmp_path / ZIP, _good())
        with zipfile.ZipFile(archive, "a") as z:
            z.writestr(f"{TOP}/backend/", b"")
            z.writestr(f"{TOP}/backend/app/", b"")
            z.writestr(f"{TOP}/backend/app/core/", b"")

        assert _check(archive) == []

    @pytest.mark.parametrize("extra", [
        # 從工作目錄整個複製 backend/ 時會帶進來的：Docker、型別檢查、開發用的依賴清單
        "backend/Dockerfile",
        "backend/.dockerignore",
        "backend/requirements-dev.txt",
        "backend/typings/torch/__init__.pyi",
        "backend/__init__.py",
        # 沒進版控、也沒被舊的排除清單擋下來的
        "backend/fake_gemini/server.py",
        "backend/config.json",
        "backend/scratch/notes.txt",
    ])
    def test_backend_files_outside_whitelist_fail(self, tmp_path, extra):
        archive = _zip(tmp_path / ZIP, _good(extra))

        assert _check(archive) == [f"不該打包：{TOP}/{extra}（不在後端白名單 $BackendPaths 裡）"]

    def test_lookalike_of_whitelisted_path_fails(self, tmp_path):
        # 名稱開頭和白名單一樣、但不是那個檔案或資料夾
        archive = _zip(tmp_path / ZIP, _good("backend/main.py.bak", "backend/app_old/x.py"))

        assert _check(archive) == [
            f"不該打包：{TOP}/backend/app_old/x.py（不在後端白名單 $BackendPaths 裡）",
            f"不該打包：{TOP}/backend/main.py.bak（不在後端白名單 $BackendPaths 裡）",
        ]

    def test_empty_runtime_folder_entry_fails(self, tmp_path):
        # 排除失效、但資料夾剛好是空的：zip 裡只有資料夾本身
        archive = _zip(tmp_path / ZIP, _good())
        with zipfile.ZipFile(archive, "a") as z:
            z.writestr(f"{TOP}/backend/audio_store/", b"")

        (problem,) = _check(archive)

        assert problem.startswith(f"不該打包：{TOP}/backend/audio_store（")

    def test_long_leak_list_is_cut(self, tmp_path):
        venv = [f"backend/.venv/lib/m{i}.py" for i in range(portable_zip.MAX_LISTED + 5)]
        archive = _zip(tmp_path / ZIP, _good(*venv))

        problems = _check(archive)

        assert len(problems) == portable_zip.MAX_LISTED + 1
        assert problems[-1] == "不該打包的還有 5 個，沒有列出"


class TestNames:
    """產品名稱 Mimiji（#26、#277）：zip 的檔名、最上層的資料夾，以及檔名裡的版本和 backend/VERSION 相同。"""

    def test_old_zip_name_fails(self, tmp_path):
        archive = _zip(tmp_path / "AI_Translate-ci-win64.zip", _good())

        assert _check(archive) == [
            "zip 的檔名應該是 Mimiji-<版本>-win64.zip，實際是 AI_Translate-ci-win64.zip"]

    def test_old_top_folder_fails(self, tmp_path):
        names = [n.replace(f"{TOP}/", "AI_Translate/", 1) for n in _good()]
        archive = _zip(tmp_path / ZIP, names)

        assert _check(archive) == ["zip 最上層的資料夾應該是 Mimiji，實際是 AI_Translate"]

    def test_version_in_zip_name_must_match_version_file(self, tmp_path):
        archive = _zip(tmp_path / "Mimiji-v0.1.0-win64.zip", _good())

        assert _check(archive) == [f"zip 檔名的版本 v0.1.0 和 {TOP}/backend/VERSION 的 ci 不同"]

    def test_release_version_passes(self, tmp_path):
        # PowerShell 寫的 VERSION 結尾有 CRLF
        archive = _zip(tmp_path / "Mimiji-v0.1.0-rc.1-win64.zip", _good(), version="v0.1.0-rc.1\r\n")

        assert _check(archive) == []


class TestProductName:
    """產品名稱在每個地方都一樣：改名時少改一處就紅燈（#277）。"""

    def test_build_script_launcher_and_manual_start_agree(self):
        script = _script()
        assert re.findall(r'^\$ProductName = "([^"]*)"$', script, re.M) == [portable_zip.PRODUCT]
        assert "$StageDir = Join-Path $BuildDir $ProductName" in script
        assert '$launcherExe = Join-Path $StageDir "$ProductName.exe"' in script
        assert '$zipName = "$ProductName-$Version-win64.zip"' in script
        assert f"{portable_zip.PRODUCT}.exe" in _required()

        launcher = (ROOT / "tools" / "launcher.cs").read_text(encoding="utf-8")
        assert re.findall(r'const string AppName = "([^"]*)";', launcher) == [portable_zip.PRODUCT]
        assert 'const string ExeName = AppName + ".exe";' in launcher
        assert start.APP_NAME == portable_zip.PRODUCT

    def test_launcher_details_use_the_product_name_and_notice(self):
        # 「內容 → 詳細資料」的產品名稱與檔案描述；著作權和 NOTICE 相同
        launcher = (ROOT / "tools" / "launcher.cs").read_text(encoding="utf-8")
        assert "[assembly: AssemblyTitle(Launcher.AppName)]" in launcher
        assert "[assembly: AssemblyProduct(Launcher.AppName)]" in launcher
        (copyright_,) = re.findall(r'^\[assembly: AssemblyCopyright\("([^"]+)"\)\]$', launcher, re.M)
        assert copyright_ in (ROOT / "NOTICE").read_text(encoding="utf-8")

    def test_build_script_compiles_icon_and_version_into_the_exe(self):
        script = _script()
        assert '$launcherIcon = Join-Path $Root "tools\\portable\\mimiji.ico"' in script
        assert ('& $csc /nologo /optimize "/win32icon:$launcherIcon" "/out:$launcherExe" $launcherSrc $versionSrc'
                in script)
        assert (ROOT / "tools" / "portable" / "mimiji.ico").is_file()

    def test_workflows_use_the_zip_name_the_build_script_makes(self):
        # 發版找不到 zip 時 tools/release_assets.py prepare 會失敗；發版與 CI 檢查的也要是這個名稱
        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        assert f'run: python tools/portable_zip.py check "build/{portable_zip.PRODUCT}-$env:TAG-win64.zip"' in release
        assert release_assets.zip_name("v1.2.3") == f"{portable_zip.PRODUCT}-v1.2.3-win64.zip"
        assert release_assets.title("v1.2.3") == f"{portable_zip.PRODUCT} v1.2.3 beta"
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert "run: .\\build_release.ps1 -Version ci -SkipFrontend" in ci
        assert f"run: python tools/portable_zip.py check build/{portable_zip.PRODUCT}-ci-win64.zip" in ci


def _info(**strings: str) -> portable_zip.ExeInfo:
    """版本資訊都對的 exe；strings 蓋過其中幾個。"""
    base = {"ProductName": "Mimiji", "FileDescription": "Mimiji", "ProductVersion": VERSION,
            "FileVersion": "0.0.0.0", "LegalCopyright": "Copyright 2026 Wade", "OriginalFilename": "Mimiji.exe"}
    return portable_zip.ExeInfo({**base, **strings}, "0.0.0.0", 1)


class TestExe:
    """Mimiji.exe 的版本資訊與圖示（#277）：判斷用假的讀取結果測，真的 exe 在 Windows 上讀。"""

    NAME = f"{TOP}/Mimiji.exe"

    def test_good_details_pass(self):
        assert portable_zip.exe_problems(_info(), self.NAME, VERSION) == []

    def test_missing_version_info_fails(self):
        assert portable_zip.exe_problems(None, self.NAME, VERSION) == [f"{self.NAME} 沒有版本資訊"]

    @pytest.mark.parametrize("info, problem", [
        (_info(ProductName="AI_Translate"), " 的產品名稱是「AI_Translate」，應該是 Mimiji"),
        (_info(FileDescription=""), " 的檔案描述是「」，應該是 Mimiji"),
        (_info(ProductVersion="dev"), " 的產品版本是「dev」，應該和 backend/VERSION 一樣是 ci"),
        (_info(FileVersion="ci"), " 的檔案版本是「ci」（數字的是 0.0.0.0），應該是 4 個數字，兩者相同"),
        (_info(FileVersion="0.1.0.0"), " 的檔案版本是「0.1.0.0」（數字的是 0.0.0.0），應該是 4 個數字，兩者相同"),
        (portable_zip.ExeInfo(_info().strings, "0.0.0.0", 0), " 沒有圖示"),
    ])
    def test_wrong_details_fail(self, info, problem):
        assert portable_zip.exe_problems(info, self.NAME, VERSION) == [self.NAME + problem]

    def test_check_reads_the_exe_inside_the_zip(self, tmp_path):
        archive = _zip(tmp_path / ZIP, _good())
        seen = []

        def read_exe(path: Path) -> portable_zip.ExeInfo:
            seen.append((path.name, path.read_bytes()))
            return _info(ProductVersion="v9")

        problems = portable_zip.check(archive, _required(), _backend(), read_exe)

        assert seen == [("Mimiji.exe", b"x")]
        assert problems == [f"{self.NAME} 的產品版本是「v9」，應該和 backend/VERSION 一樣是 ci"]

    def test_empty_exe_is_reported_once(self, tmp_path):
        # 空的 exe 由必要檔案那一項報，不再交給 read_exe
        archive = _zip(tmp_path / ZIP, _good(), empty=(self.NAME,))

        problems = portable_zip.check(archive, _required(), _backend(), lambda path: pytest.fail(str(path)))

        assert problems == [f"必要的檔案是空的：{self.NAME}"]


class TestBatchFiles:
    """start.bat（#267）：只有 ASCII、CRLF、不帶 BOM；在 zip 裡檢查，換了寫法也抓得到。"""

    def _with_bat(self, tmp_path, data: bytes) -> Path:
        names = [n for n in _good() if n != f"{TOP}/start.bat"]
        archive = _zip(tmp_path / ZIP, names)
        with zipfile.ZipFile(archive, "a") as z:
            z.writestr(f"{TOP}/start.bat", data)
        return archive

    def test_crlf_without_bom_passes(self, tmp_path):
        archive = self._with_bat(tmp_path, b"@echo off\r\nchcp 65001 > nul\r\n")

        assert _check(archive) == []

    @pytest.mark.parametrize("data, problem", [
        (b"\xef\xbb\xbf@echo off\r\n", "開頭有 BOM"),
        (b"@echo off\nchcp 65001 > nul\n", "換行不是 CRLF"),
        (b"@echo off\r\nchcp 65001 > nul\n", "換行不是 CRLF"),
        ("@echo off\r\necho 首次啟動\r\n".encode("utf-8"), "ASCII 以外的字元"),
    ])
    def test_bom_or_lf_fails(self, tmp_path, data, problem):
        archive = self._with_bat(tmp_path, data)

        (found,) = _check(archive)

        assert found.startswith(f"批次檔 {TOP}/start.bat ")
        assert problem in found

    def test_start_bat_is_required(self):
        # CI 的 zip 檢查照這份清單：少了 start.bat 就紅燈
        assert "start.bat" in _required()


class TestPlant:
    def test_creates_every_planted_file(self, tmp_path):
        created = portable_zip.plant(tmp_path)

        assert sorted(p.relative_to(tmp_path).as_posix() for p in created) == sorted(
            portable_zip.PLANTED)
        assert all(p.read_bytes() == portable_zip.PLANTED_CONTENT for p in created)

    def test_never_overwrites_existing_files(self, tmp_path):
        env = tmp_path / "backend" / ".env"
        env.parent.mkdir()
        env.write_text("GOOGLE_API_KEY=real-key\n", encoding="utf-8")

        created = portable_zip.plant(tmp_path)

        assert env not in created
        assert env.read_text(encoding="utf-8") == "GOOGLE_API_KEY=real-key\n"
        assert len(created) == len(portable_zip.PLANTED) - 1


class TestMain:
    @pytest.fixture(autouse=True)
    def no_exe_reader(self, monkeypatch):
        # 和平台無關：預設不讀 exe（Windows 上的 main 會讀，假的 exe 沒有版本資訊）
        monkeypatch.setattr(portable_zip, "EXE_READER", None)

    def test_good_zip_exits_0(self, tmp_path, capsys):
        archive = _zip(tmp_path / ZIP, _good())

        assert portable_zip.main(["check", str(archive)]) == 0
        out = capsys.readouterr().out
        assert "名稱是 Mimiji，" in out
        assert "後端只有白名單裡的檔案，沒有執行期資料" in out
        assert "不是 Windows：沒有檢查 Mimiji.exe 的版本資訊與圖示" in out

    def test_exe_is_checked_with_the_platform_reader(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(portable_zip, "EXE_READER", lambda path: _info())
        archive = _zip(tmp_path / ZIP, _good())

        assert portable_zip.main(["check", str(archive)]) == 0
        assert "Mimiji.exe 的產品名稱、產品版本、檔案版本與圖示都對" in capsys.readouterr().out

    def test_exe_without_details_exits_1(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(portable_zip, "EXE_READER", lambda path: None)
        archive = _zip(tmp_path / ZIP, _good())

        assert portable_zip.main(["check", str(archive)]) == 1
        assert f"{TOP}/Mimiji.exe 沒有版本資訊" in capsys.readouterr().out

    def test_lists_every_file_with_its_size(self, tmp_path, capsys):
        # 改到打包的 PR 拿 main 與 PR 的 CI 日誌比對發布包的內容
        archive = _zip(tmp_path / ZIP, _good())

        portable_zip.main(["check", str(archive)])

        lines = capsys.readouterr().out.splitlines()
        assert f"{archive} 的內容（{len(_good())} 個檔案，位元組）：" in lines
        listed = [line.split()[-1] for line in lines if line.startswith("  ")]
        assert listed == sorted(_good())

    def test_bad_zip_exits_1_and_lists_problems(self, tmp_path, capsys):
        archive = _zip(tmp_path / ZIP, _good("backend/audio_store/planted.wav"))

        assert portable_zip.main(["check", str(archive)]) == 1
        out = capsys.readouterr().out
        assert "1 個問題" in out
        assert f"{TOP}/backend/audio_store/planted.wav" in out
