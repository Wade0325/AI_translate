"""
單元測試：上傳工具函數
測試範圍：api/upload.py 中的 _get_unique_filepath 與 SUPPORTED_MIME_TYPES
"""
import pytest
from pathlib import Path
from app.api.upload import _get_unique_filepath, SUPPORTED_MIME_TYPES


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


# ─── _get_unique_filepath ────────────────────────────────────────────────────

class TestGetUniqueFilepath:
    def test_returns_original_path_when_no_conflict(self, tmp_path):
        """目錄中沒有同名檔案時，應直接回傳原始路徑"""
        result = _get_unique_filepath(tmp_path, "audio.mp3")
        assert result == tmp_path / "audio.mp3"

    def test_adds_counter_when_file_exists(self, tmp_path):
        """同名檔案存在時，應加上 (1) 編號"""
        (tmp_path / "audio.mp3").touch()
        result = _get_unique_filepath(tmp_path, "audio.mp3")
        assert result == tmp_path / "audio(1).mp3"

    def test_increments_counter_when_multiple_conflicts(self, tmp_path):
        """多個同名檔案時，應持續遞增編號"""
        (tmp_path / "audio.mp3").touch()
        (tmp_path / "audio(1).mp3").touch()
        result = _get_unique_filepath(tmp_path, "audio.mp3")
        assert result == tmp_path / "audio(2).mp3"

    def test_counter_keeps_incrementing(self, tmp_path):
        """連續 5 個衝突時應給出 (5) 的編號"""
        (tmp_path / "audio.mp3").touch()
        for i in range(1, 5):
            (tmp_path / f"audio({i}).mp3").touch()
        result = _get_unique_filepath(tmp_path, "audio.mp3")
        assert result == tmp_path / "audio(5).mp3"

    def test_preserves_file_extension(self, tmp_path):
        """生成的檔名應保留副檔名"""
        (tmp_path / "video.mp4").touch()
        result = _get_unique_filepath(tmp_path, "video.mp4")
        assert result.suffix == ".mp4"

    def test_preserves_stem(self, tmp_path):
        """生成的檔名 stem 應包含原始名稱"""
        (tmp_path / "my_audio.wav").touch()
        result = _get_unique_filepath(tmp_path, "my_audio.wav")
        assert result.stem.startswith("my_audio")

    def test_filename_without_extension(self, tmp_path):
        """無副檔名的檔案也應正確處理"""
        (tmp_path / "myfile").touch()
        result = _get_unique_filepath(tmp_path, "myfile")
        assert result == tmp_path / "myfile(1)"

    def test_returns_path_object(self, tmp_path):
        """回傳值應為 Path 物件"""
        result = _get_unique_filepath(tmp_path, "test.mp3")
        assert isinstance(result, Path)

    def test_result_parent_is_given_directory(self, tmp_path):
        """回傳的路徑父目錄應為指定目錄"""
        result = _get_unique_filepath(tmp_path, "test.mp3")
        assert result.parent == tmp_path
