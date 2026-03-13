"""
整合測試：檔案上傳 API
測試範圍：POST /api/v1/upload
"""
import io
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


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
        assert data["message"] == "檔案上傳成功"

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

    def test_upload_returns_saved_filename(self, client: TestClient, tmp_path):
        """回傳的 filename 應與上傳的相同（無衝突時）"""
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            response = client.post(
                "/api/v1/upload",
                files={"file": ("unique_audio.mp3", b"\x00" * 512, "audio/mpeg")},
            )
        assert response.status_code == 200
        assert response.json()["filename"] == "unique_audio.mp3"

    def test_upload_duplicate_filename_gets_counter(self, client: TestClient, tmp_path):
        """同名檔案重複上傳，第二次應得到 (1) 後綴"""
        with patch("app.api.upload.TEMP_UPLOADS_DIR", tmp_path):
            client.post(
                "/api/v1/upload",
                files={"file": ("dup.mp3", b"\x00" * 512, "audio/mpeg")},
            )
            response2 = client.post(
                "/api/v1/upload",
                files={"file": ("dup.mp3", b"\x00" * 512, "audio/mpeg")},
            )
        assert response2.status_code == 200
        assert response2.json()["filename"] == "dup(1).mp3"


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
        assert "Unsupported file format" in response.json()["detail"]

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
        assert "empty" in response.json()["detail"].lower()

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
