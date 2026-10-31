"""tools/portable_zip.py：CI 建置免安裝版之後的 zip 檢查（#256）。

CI 的 portable job 在 Windows 上真的建置一次；這裡用自己做的 zip 測檢查本身：結構對的 zip
要過，缺檔、空檔、最上層不對、夾帶執行期資料、後端有白名單以外檔案的 zip 要擋下來。plant 放的
每一個檔案都要被擋，否則 CI 放了也考不到取檔的那一步。
"""
import zipfile
from pathlib import Path

import pytest

from tools import portable_zip

ROOT = Path(__file__).resolve().parents[2]
TOP = "AI_Translate"


def _script() -> str:
    return (ROOT / "build_release.ps1").read_text(encoding="utf-8-sig")


def _required() -> list[str]:
    return portable_zip.required_files(_script())


def _backend() -> list[str]:
    return portable_zip.backend_paths(_script())


def _check(archive: Path) -> list[str]:
    return portable_zip.check(archive, _required(), _backend())


def _zip(path: Path, names: list[str], *, sep: str = "/", empty: tuple[str, ...] = ()) -> Path:
    """在 path 做一個 zip：names 是 zip 裡的路徑（用 /），empty 裡的寫成空檔。"""
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            data = b"" if name in empty else b"x"
            archive.writestr(name.replace("/", sep), data)
    return path


def _good(*extra: str) -> list[str]:
    """build_release.ps1 的必要檔案都在的發布包，再加上 extra（最上層資料夾以下的路徑）。"""
    return [f"{TOP}/{rel}" for rel in [*_required(), "backend/app/__init__.py", *extra]]


class TestRequiredFiles:
    def test_reads_step_7_of_build_script(self):
        required = _required()

        # 路徑改用 /，和 zip 的寫法一致
        assert "AI_Translate.exe" in required
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
        archive = _zip(tmp_path / "ok.zip", _good())

        assert _check(archive) == []

    def test_backslash_separators_from_powershell_5_pass(self, tmp_path):
        # Windows PowerShell 5.1 的 Compress-Archive 用 \ 當 zip 裡的分隔符號
        archive = _zip(tmp_path / "ps51.zip", _good(), sep="\\")

        assert _check(archive) == []

    def test_lookalike_source_files_pass(self, tmp_path):
        # 名稱像執行期資料、其實是原始碼或隨包的執行環境
        archive = _zip(tmp_path / "ok.zip", _good(
            "backend/app/services/audio_store.py",
            "backend/app/.env.example",
            "runtime/sqlite3.dll",
            "runtime/_sqlite3.pyd",
            "frontend/dist/assets/data.js",
        ))

        assert _check(archive) == []

    def test_missing_and_empty_required_files_fail(self, tmp_path):
        names = [n for n in _good() if n != f"{TOP}/bin/ffmpeg.exe"]
        archive = _zip(tmp_path / "bad.zip", names, empty=(f"{TOP}/AI_Translate.exe",))

        # 照 build_release.ps1 清單的順序列出
        assert _check(archive) == [
            f"必要的檔案是空的：{TOP}/AI_Translate.exe",
            f"缺少必要的檔案：{TOP}/bin/ffmpeg.exe",
        ]

    def test_files_outside_a_single_top_folder_fail(self, tmp_path):
        archive = _zip(tmp_path / "flat.zip", [*_good(), "README.txt"])

        problems = _check(archive)

        assert problems == [f"zip 的最上層應該剛好是一個資料夾，實際是：{TOP}、README.txt"]

    def test_empty_zip_fails(self, tmp_path):
        archive = _zip(tmp_path / "empty.zip", [])

        assert _check(archive) == ["zip 是空的"]

    @pytest.mark.parametrize("planted", portable_zip.PLANTED)
    def test_every_planted_file_fails(self, tmp_path, planted):
        # CI 在建置前放進這些檔案：沒被排除而進了 zip，就要紅燈
        archive = _zip(tmp_path / "leak.zip", _good(planted))

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
        archive = _zip(tmp_path / "leak.zip", _good(leaked))

        (problem,) = _check(archive)

        assert reason in problem

    def test_folder_entries_leading_to_whitelisted_paths_pass(self, tmp_path):
        # zip 可能為資料夾寫一個項目（結尾是 /）
        archive = _zip(tmp_path / "ok.zip", _good())
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
        archive = _zip(tmp_path / "extra.zip", _good(extra))

        assert _check(archive) == [f"不該打包：{TOP}/{extra}（不在後端白名單 $BackendPaths 裡）"]

    def test_lookalike_of_whitelisted_path_fails(self, tmp_path):
        # 名稱開頭和白名單一樣、但不是那個檔案或資料夾
        archive = _zip(tmp_path / "extra.zip", _good("backend/main.py.bak", "backend/app_old/x.py"))

        assert _check(archive) == [
            f"不該打包：{TOP}/backend/app_old/x.py（不在後端白名單 $BackendPaths 裡）",
            f"不該打包：{TOP}/backend/main.py.bak（不在後端白名單 $BackendPaths 裡）",
        ]

    def test_empty_runtime_folder_entry_fails(self, tmp_path):
        # 排除失效、但資料夾剛好是空的：zip 裡只有資料夾本身
        archive = _zip(tmp_path / "leak.zip", _good())
        with zipfile.ZipFile(archive, "a") as z:
            z.writestr(f"{TOP}/backend/audio_store/", b"")

        (problem,) = _check(archive)

        assert problem.startswith(f"不該打包：{TOP}/backend/audio_store（")

    def test_long_leak_list_is_cut(self, tmp_path):
        venv = [f"backend/.venv/lib/m{i}.py" for i in range(portable_zip.MAX_LISTED + 5)]
        archive = _zip(tmp_path / "venv.zip", _good(*venv))

        problems = _check(archive)

        assert len(problems) == portable_zip.MAX_LISTED + 1
        assert problems[-1] == "不該打包的還有 5 個，沒有列出"


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
    def test_good_zip_exits_0(self, tmp_path, capsys):
        archive = _zip(tmp_path / "ok.zip", _good())

        assert portable_zip.main(["check", str(archive)]) == 0
        assert "後端只有白名單裡的檔案，沒有執行期資料" in capsys.readouterr().out

    def test_lists_every_file_with_its_size(self, tmp_path, capsys):
        # 改到打包的 PR 拿 main 與 PR 的 CI 日誌比對發布包的內容
        archive = _zip(tmp_path / "ok.zip", _good())

        portable_zip.main(["check", str(archive)])

        lines = capsys.readouterr().out.splitlines()
        assert f"{archive} 的內容（{len(_good())} 個檔案，位元組）：" in lines
        listed = [line.split()[-1] for line in lines if line.startswith("  ")]
        assert listed == sorted(_good())

    def test_bad_zip_exits_1_and_lists_problems(self, tmp_path, capsys):
        archive = _zip(tmp_path / "leak.zip", _good("backend/audio_store/planted.wav"))

        assert portable_zip.main(["check", str(archive)]) == 1
        out = capsys.readouterr().out
        assert "1 個問題" in out
        assert f"{TOP}/backend/audio_store/planted.wav" in out
