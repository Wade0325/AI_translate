"""
單元測試：上傳工具函數
測試範圍：api/upload.py 中的 stored_name 與 SUPPORTED_MIME_TYPES
"""
import re

import pytest

from app.api.upload import stored_name, SUPPORTED_MIME_TYPES


# ─── SUPPORTED_MIME_TYPES ────────────────────────────────────────────────────

class TestSupportedMimeTypes:
    def test_common_audio_types_supported(self):
        assert "audio/mpeg" in SUPPORTED_MIME_TYPES
        assert "audio/wav" in SUPPORTED_MIME_TYPES
        assert "audio/mp4" in SUPPORTED_MIME_TYPES
        assert "audio/flac" in SUPPORTED_MIME_TYPES

    def test_common_video_types_supported(self):
        assert "video/mp4" in SUPPORTED_MIME_TYPES
        assert "video/webm" in SUPPORTED_MIME_TYPES

    def test_unsupported_types_not_in_set(self):
        assert "image/jpeg" not in SUPPORTED_MIME_TYPES
        assert "application/pdf" not in SUPPORTED_MIME_TYPES
        assert "text/plain" not in SUPPORTED_MIME_TYPES


# ─── stored_name ─────────────────────────────────────────────────────────────

class TestStoredName:
    """上傳檔在磁碟上的名稱：隨機名稱加上原本的副檔名，不帶原檔名（#231 Q5）。"""

    @pytest.mark.parametrize("original, suffix", [
        ("王小明的會議.m4a", ".m4a"),
        ("Interview.MP3", ".MP3"),
        ("a.b.c.flac", ".flac"),
        ("video.webm", ".webm"),
    ])
    def test_random_name_with_the_original_extension(self, original, suffix):
        name = stored_name(original)

        assert re.fullmatch(r"[0-9a-f]{32}" + re.escape(suffix), name)

    def test_never_contains_the_original_name(self):
        assert "王小明" not in stored_name("王小明.wav")
        assert "meeting" not in stored_name("meeting")

    @pytest.mark.parametrize("original", ["錄音.音檔", "no-extension", "x.m4a ", "x.<script>", ".bashrc"])
    def test_extension_that_is_not_plain_ascii_is_dropped(self, original):
        # 副檔名也是使用者取的：只留英數字的（ffmpeg 與 MIME 類型要靠它），其他的不帶
        assert re.fullmatch(r"[0-9a-f]{32}", stored_name(original))

    def test_every_upload_gets_its_own_name(self):
        assert stored_name("a.wav") != stored_name("a.wav")
