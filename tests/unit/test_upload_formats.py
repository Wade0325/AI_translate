"""上傳驗證（#258）：輸入檔名與大小，輸出收（連同格式），或不收的原因。

瀏覽器給的 MIME 類型不參與判斷（見 app/core/upload_formats.py）；經上傳端點、帶各種 MIME 的情況在
tests/integration/test_upload_api.py。
"""

import pytest

from app.core.upload_formats import (
    MAX_UPLOAD_BYTES,
    UPLOAD_FORMATS,
    Rejected,
    UploadFormat,
    check_upload,
    listed,
)

MB = 1024 ** 2

TWO_HOUR_WAV_BYTES = {
    # 2 小時 × 取樣率 × 聲道 × 每個樣本的位元組，加上 44 位元組的檔頭
    "44.1 kHz 立體聲 16-bit": 7200 * 44100 * 2 * 2 + 44,
    "48 kHz 立體聲 16-bit": 7200 * 48000 * 2 * 2 + 44,
    "48 kHz 立體聲 24-bit": 7200 * 48000 * 2 * 3 + 44,
}


def accepted(filename: str, size: int = 10 * MB) -> UploadFormat:
    checked = check_upload(filename, size)
    assert isinstance(checked, UploadFormat), checked
    return checked


def rejection(filename: str, size: int = 10 * MB) -> str:
    checked = check_upload(filename, size)
    assert isinstance(checked, Rejected), checked
    return checked.reason


class TestFormats:
    @pytest.mark.parametrize("filename, kind", [
        ("meeting.mp3", "audio"),
        ("meeting.wav", "audio"),
        ("meeting.m4a", "audio"),
        ("meeting.flac", "audio"),
        ("meeting.mp4", "video"),
        ("IMG_0001.MOV", "video"),
        ("stream.mkv", "video"),
        ("recording.webm", "video"),
    ])
    def test_common_audio_and_video_are_accepted(self, filename, kind):
        assert accepted(filename).kind == kind

    @pytest.mark.parametrize("upload_format", UPLOAD_FORMATS, ids=lambda f: f.label)
    def test_every_listed_format_is_accepted_in_any_case(self, upload_format):
        for name in (f"a{upload_format.extension}", f"a{upload_format.extension.upper()}"):
            assert accepted(name) == upload_format

    def test_only_the_last_extension_counts(self):
        assert accepted("王小明的會議.2026.10.31.wav").label == "WAV"
        assert rejection("song.mp3.exe").startswith("不支援這種檔案格式（.exe）")

    @pytest.mark.parametrize("filename, shown", [
        ("photo.jpg", ".jpg"),
        ("voice.ogg", ".ogg"),
        ("notes.TXT", ".txt"),
        ("recording", "沒有副檔名"),
    ])
    def test_other_files_are_rejected_with_what_can_be_uploaded(self, filename, shown):
        assert rejection(filename) == (
            f"不支援這種檔案格式（{shown}）。可以上傳的音檔：MP3、WAV、M4A、FLAC；"
            "影片：MP4、MOV、MKV、WebM、AVI、WMV、M4V、MPG、MPEG")

    def test_extensions_are_listed_once_lowercase_with_a_dot(self):
        extensions = [f.extension for f in UPLOAD_FORMATS]
        assert len(extensions) == len(set(extensions))
        assert all(e.startswith(".") and e == e.lower() for e in extensions)


class TestSize:
    @pytest.mark.parametrize("size", TWO_HOUR_WAV_BYTES.values(), ids=TWO_HOUR_WAV_BYTES.keys())
    def test_a_two_hour_wav_fits(self, size):
        assert accepted("long_meeting.wav", size).label == "WAV"

    def test_the_limit_itself_is_accepted(self):
        assert MAX_UPLOAD_BYTES == 2 * 1024 ** 3
        assert accepted("big.mp4", MAX_UPLOAD_BYTES).label == "MP4"

    @pytest.mark.parametrize("size, shown", [
        (MAX_UPLOAD_BYTES + 1, "2.1 GB"),
        (int(2.5 * 1024 ** 3), "2.5 GB"),
        (5 * 1024 ** 3, "5 GB"),
    ])
    def test_larger_files_are_rejected_with_their_size_and_the_limit(self, size, shown):
        assert rejection("long_meeting.wav", size) == (
            f"檔案太大（{shown}），上限是 2 GB。音檔可以先轉成 FLAC 或 MP3，影片可以先剪成幾段再上傳")

    def test_empty_file_is_rejected(self):
        assert rejection("meeting.mp3", 0) == "檔案是空的（0 位元組），請確認檔案沒有損壞"

    def test_format_is_checked_before_size(self):
        assert rejection("photo.jpg", 0).startswith("不支援這種檔案格式")


def test_listed_for_the_screen_in_order_with_the_limit():
    assert listed() == {
        "formats": [{"extension": f.extension, "label": f.label, "kind": f.kind}
                    for f in UPLOAD_FORMATS],
        "max_bytes": MAX_UPLOAD_BYTES,
    }
    assert [f["label"] for f in listed()["formats"]][:5] == ["MP3", "WAV", "M4A", "FLAC", "MP4"]
