"""
整合測試：檔案上傳 API
測試範圍：POST /api/v1/upload
"""
import shutil
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.api import upload  # noqa: F401  app_log 只收得到已經建立的 logger


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

    def test_upload_valid_mp4(self, client: TestClient, tmp_path):
        """上傳有效的 MP4 影片應回傳 200"""
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("video.mp4", b"\x00" * 1024, "video/mp4")},
            )
        assert response.status_code == 200

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


# ─── 上傳失敗 ────────────────────────────────────────────────────────────────

class TestUploadFailure:
    def test_unsupported_mime_type_returns_400(self, client: TestClient, tmp_path):
        """不支援的 MIME 類型應回傳 400"""
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("image.jpg", b"\xff\xd8\xff" + b"\x00" * 512, "image/jpeg")},
            )
        assert response.status_code == 400
        assert response.json()["detail"].startswith("不支援這種檔案格式（image/jpeg）")

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
