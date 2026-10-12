"""單元測試：上傳檔名驗證（utils/paths.py 的 resolve_upload_path）

轉錄／批次／VAD 端點都拿前端送來的伺服器檔名去 temp_uploads 找檔案。
``base / name`` 遇到絕對路徑會丟掉 base，``..`` 也能跳出目錄，
所以只接受單純檔名，並以 resolve() 確認結果就在 temp_uploads 內。
"""
from pathlib import Path

import pytest

from app.utils.paths import UnsafeUploadFilenameError, resolve_upload_path


@pytest.fixture
def uploads(tmp_path):
    root = tmp_path / "uploads"
    root.mkdir()
    return root


class TestAcceptsPlainFilename:
    @pytest.mark.parametrize("name", [
        "audio.mp3",
        "會議 紀錄(1).m4a",
        "song..mp3",      # 檔名中間的 .. 不構成穿越（沒有分隔符就無處可跳）
        ".hidden.wav",
    ])
    def test_returns_path_inside_uploads(self, uploads, name):
        assert resolve_upload_path(name, uploads) == uploads / name

    def test_keeps_relative_base_unresolved(self, uploads, monkeypatch):
        """docker 模式 API 與主機 GPU worker 靠 cwd 相對路徑共享上傳檔，回傳值不能變成絕對路徑。"""
        monkeypatch.chdir(uploads.parent)
        assert resolve_upload_path("a.mp3", Path("uploads")) == Path("uploads") / "a.mp3"


class TestRejectsUnsafeFilename:
    @pytest.mark.parametrize("name", [
        "",
        ".",
        "..",
        "../secret.txt",
        "..\\secret.txt",
        "sub/a.mp3",
        "sub\\a.mp3",
        "/etc/passwd",
        "\\Windows\\win.ini",
        "C:\\Windows\\win.ini",
        "C:/Windows/win.ini",
        "C:secret.txt",          # 磁碟機相對路徑：Windows 上會跳到 C: 的目前目錄
        "\\\\server\\share\\a.mp3",
        "a.mp3\x00.txt",
    ])
    def test_raises(self, uploads, name):
        with pytest.raises(UnsafeUploadFilenameError):
            resolve_upload_path(name, uploads)

    def test_absolute_path_to_existing_file_is_rejected(self, uploads, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("x")
        with pytest.raises(UnsafeUploadFilenameError):
            resolve_upload_path(str(secret), uploads)

    def test_error_message_is_user_readable(self, uploads):
        with pytest.raises(UnsafeUploadFilenameError) as exc_info:
            resolve_upload_path("../secret.txt", uploads)
        message = str(exc_info.value)
        assert "檔案名稱不合法" in message
        # 不把伺服器路徑回顯給使用者
        assert str(uploads) not in message
