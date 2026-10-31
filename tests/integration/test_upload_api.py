"""
整合測試：檔案上傳 API
測試範圍：POST /api/v1/upload、GET /api/v1/upload/limits

收不收的規則本身在 tests/unit/test_upload_formats.py；這裡經端點看瀏覽器給的 MIME 類型不影響結果、
不收的原因原樣回給畫面，以及影片上傳後只留下抽出的音訊（#258）。影片用真的 ffmpeg 處理。
"""
import shutil
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api import upload  # noqa: F401  app_log 只收得到已經建立的 logger
from app.core.upload_formats import limits
from tests.support.synthetic_video import audio_with_cover, stream_types, synthetic_video


def post(client: TestClient, tmp_path, name: str, content: bytes, content_type: str):
    with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
        return client.post("/api/v1/upload", files={"file": (name, content, content_type)})


def saved_files(folder) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


# ─── 上傳成功 ────────────────────────────────────────────────────────────────

class TestUploadSuccess:
    def test_upload_valid_mp3(self, client: TestClient, tmp_path):
        """上傳有效的 MP3 檔案應回傳 200 及 filename"""
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("test.mp3", b"\xff\xfb" + b"\x00" * 512, "audio/mpeg")},
            )
        assert response.status_code == 200
        data = response.json()
        assert "filename" in data
        assert data["filename"].endswith(".mp3")

    def test_upload_valid_wav(self, client: TestClient, tmp_path):
        """上傳有效的 WAV 檔案應回傳 200"""
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("audio.wav", b"RIFF" + b"\x00" * 512, "audio/wav")},
            )
        assert response.status_code == 200

    def test_upload_m4a(self, client: TestClient, tmp_path):
        """上傳 M4A 檔案應回傳 200"""
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("audio.m4a", b"\x00" * 512, "audio/x-m4a")},
            )
        assert response.status_code == 200

    def test_saved_under_a_random_name_without_the_original_one(self, client: TestClient, tmp_path):
        """磁碟上是隨機名稱：原檔名只留在請求與任務紀錄，log、暫存檔與送到 Gemini 的檔案都看不到（#231 Q5）"""
        content = b"\xff\xfb" + b"\x00" * 512
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("王小明的會議.mp3", content, "audio/mpeg")},
            )
        assert response.status_code == 200
        saved = response.json()["filename"]
        assert "王小明" not in saved
        assert saved.endswith(".mp3")
        assert [p.name for p in tmp_path.iterdir()] == [saved]
        assert (tmp_path / saved).read_bytes() == content

    def test_same_name_uploaded_twice_is_kept_twice(self, client: TestClient, tmp_path):
        """同名檔案重複上傳，兩個都留著、名稱不同"""
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            first = client.post(
                "/api/v1/upload",
                files={"file": ("dup.mp3", b"\x01" * 512, "audio/mpeg")},
            ).json()["filename"]
            second = client.post(
                "/api/v1/upload",
                files={"file": ("dup.mp3", b"\x02" * 512, "audio/mpeg")},
            ).json()["filename"]
        assert first != second
        assert (tmp_path / first).read_bytes() == b"\x01" * 512
        assert (tmp_path / second).read_bytes() == b"\x02" * 512

    def test_log_names_the_saved_file_not_the_original(self, client: TestClient, tmp_path, app_log):
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            saved = client.post(
                "/api/v1/upload",
                files={"file": ("王小明的會議.mp3", b"\x00" * 512, "audio/mpeg")},
            ).json()["filename"]
        assert any(saved in entry for entry in app_log)
        assert not any("王小明" in entry for entry in app_log)


# ─── 瀏覽器給的 MIME 類型不影響結果 ─────────────────────────────────────────

class TestMimeTypeIsNotTrusted:
    """Windows 上的瀏覽器照登錄檔給 MIME：常常是空的或對不上，收不收只看副檔名。"""

    @pytest.mark.parametrize("name, content_type", [
        ("meeting.m4a", ""),
        ("meeting.m4a", "audio/x-m4a"),
        ("meeting.FLAC", "application/octet-stream"),
        ("meeting.wav", "audio/x-wav"),
        ("meeting.mp3", "video/mp4"),
    ])
    def test_audio_with_any_mime_type_is_accepted(self, client: TestClient, tmp_path,
                                                  name, content_type):
        response = post(client, tmp_path, name, b"\x00" * 512, content_type)

        assert response.status_code == 200, response.text
        assert response.json()["filename"].lower().endswith(name[name.rindex("."):].lower())

    @pytest.mark.parametrize("name, content_type", [
        ("notes.txt", "audio/mpeg"),
        ("recording", "audio/wav"),
        ("photo.jpg", "image/jpeg"),
    ])
    def test_other_files_are_rejected_even_with_an_audio_mime_type(
            self, client: TestClient, tmp_path, name, content_type):
        response = post(client, tmp_path, name, b"\x00" * 512, content_type)

        assert response.status_code == 400
        assert response.json()["detail"].startswith("不支援這種檔案格式")
        assert saved_files(tmp_path) == []


# ─── 影片 ────────────────────────────────────────────────────────────────────

class TestVideo:
    """影片在上傳時就抽出音訊：回傳的是 FLAC 的檔名，影片本身不留（#258）。"""

    @pytest.fixture
    def source(self, tmp_path):
        """做合成影片的資料夾，和上傳的暫存資料夾分開。"""
        folder = tmp_path / "source"
        folder.mkdir()
        return folder

    def test_only_the_extracted_audio_is_kept(self, client: TestClient, tmp_path, source):
        video = synthetic_video(source / "meeting.mp4")
        uploads = tmp_path / "uploads"

        response = post(client, uploads, "王小明的會議.mp4", video.read_bytes(), "video/mp4")

        assert response.status_code == 200, response.text
        saved = response.json()["filename"]
        assert saved.endswith(".flac")
        assert "王小明" not in saved
        assert saved_files(uploads) == [saved]
        assert stream_types(uploads / saved) == ["audio"]

    @pytest.mark.parametrize("content_type", ["video/quicktime", "", "application/octet-stream"])
    def test_video_with_any_mime_type_is_extracted(self, client: TestClient, tmp_path, source,
                                                   content_type):
        video = synthetic_video(source / "clip.mov")
        uploads = tmp_path / "uploads"

        response = post(client, uploads, "clip.mov", video.read_bytes(), content_type)

        assert response.status_code == 200, response.text
        assert response.json()["filename"].endswith(".flac")

    def test_video_renamed_as_audio_is_extracted_too(self, client: TestClient, tmp_path, source):
        # 改了副檔名的 MP4：副檔名是音檔，裡面還是影片，一樣只留抽出的音訊
        video = synthetic_video(source / "clip.mp4")
        uploads = tmp_path / "uploads"

        response = post(client, uploads, "meeting.m4a", video.read_bytes(), "audio/x-m4a")

        assert response.status_code == 200, response.text
        saved = response.json()["filename"]
        assert saved.endswith(".flac")
        assert stream_types(uploads / saved) == ["audio"]

    def test_audio_with_an_album_cover_is_kept_as_it_is(self, client: TestClient, tmp_path, source):
        # 專輯封面是一張圖，不是影片：照原檔留著
        audio = audio_with_cover(source / "song.mp3")
        uploads = tmp_path / "uploads"

        response = post(client, uploads, "song.mp3", audio.read_bytes(), "audio/mpeg")

        assert response.status_code == 200, response.text
        saved = response.json()["filename"]
        assert saved.endswith(".mp3")
        assert (uploads / saved).read_bytes() == audio.read_bytes()

    def test_video_without_sound_is_rejected_and_not_kept(self, client: TestClient, tmp_path, source):
        video = synthetic_video(source / "screen.mp4", with_audio=False)
        uploads = tmp_path / "uploads"

        response = post(client, uploads, "screen.mp4", video.read_bytes(), "video/mp4")

        assert response.status_code == 400
        assert response.json()["detail"] == "這個影片沒有聲音，沒有可以轉錄的內容"
        assert saved_files(uploads) == []

    def test_unreadable_video_is_rejected_and_not_kept(self, client: TestClient, tmp_path):
        response = post(client, tmp_path, "broken.mp4", b"\x00" * 1024, "video/mp4")

        assert response.status_code == 400
        assert response.json()["detail"].startswith("沒辦法從這個影片抽出聲音")
        assert saved_files(tmp_path) == []


# ─── 格式與大小的清單 ────────────────────────────────────────────────────────

def test_limits_list_the_formats_and_the_maximum_size(client: TestClient):
    response = client.get("/api/v1/upload/limits")

    assert response.status_code == 200
    assert response.json() == limits()


# ─── 上傳失敗 ────────────────────────────────────────────────────────────────

class TestUploadFailure:
    def test_unsupported_format_returns_400_with_what_can_be_uploaded(
            self, client: TestClient, tmp_path):
        """不支援的格式回 400，原因列出可以上傳的格式（顯示在轉錄頁的檔案卡上）"""
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("image.jpg", b"\xff\xd8\xff" + b"\x00" * 512, "image/jpeg")},
            )
        assert response.status_code == 400
        assert response.json()["detail"] == (
            "不支援這種檔案格式（.jpg）。可以上傳的音檔：MP3、WAV、M4A、FLAC；"
            "影片：MP4、MOV、MKV、WebM、AVI、WMV、M4V、3GP、MPG、MPEG")

    def test_file_over_the_limit_returns_400_and_is_not_kept(
            self, client: TestClient, tmp_path, monkeypatch):
        """超過上限回 400；上限照 app/core/upload_formats.py，這裡改小，不必真的傳 2 GB"""
        monkeypatch.setattr("app.core.upload_formats.MAX_UPLOAD_BYTES", 1000)

        response = post(client, tmp_path, "long.wav", b"\x00" * 1001, "audio/wav")

        assert response.status_code == 400
        assert response.json()["detail"].startswith("檔案太大")
        assert saved_files(tmp_path) == []

    def test_text_file_returns_400(self, client: TestClient, tmp_path):
        """文字檔案應回傳 400"""
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("doc.txt", b"hello", "text/plain")},
            )
        assert response.status_code == 400

    def test_empty_file_returns_400(self, client: TestClient, tmp_path):
        """空檔案應回傳 400"""
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("empty.mp3", b"", "audio/mpeg")},
            )
        assert response.status_code == 400
        assert response.json()["detail"].startswith("檔案是空的")

    def test_save_failure_returns_500_without_the_exception_text(
            self, client: TestClient, tmp_path, monkeypatch, app_log):
        """存不進磁碟時回固定訊息：例外的文字帶著使用者電腦上的路徑，原因只記在 log"""
        def disk_full(src, dst):
            raise OSError(28, "No space left on device",
                          r"C:\Users\wang.xiaoming\AppData\Local\Temp\meeting.mp3")

        monkeypatch.setattr(shutil, "copyfileobj", disk_full)
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("meeting.mp3", b"\x00" * 512, "audio/mpeg")},
            )
        assert response.status_code == 500
        assert "wang.xiaoming" not in response.text
        assert "No space left on device" not in response.text
        assert "No space left on device" in "\n".join(app_log)

    def test_missing_file_field_returns_422(self, client: TestClient):
        """未提供 file 欄位應回傳 422"""
        response = client.post("/api/v1/upload")
        assert response.status_code == 422

    def test_pdf_returns_400(self, client: TestClient, tmp_path):
        """PDF 應回傳 400"""
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
            )
        assert response.status_code == 400
