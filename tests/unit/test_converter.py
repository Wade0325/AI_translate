"""
單元測試：LRC 字幕格式轉換服務
測試範圍：converter/service.py 中的所有公開與私有函式
"""
import pytest
from app.services.converter.service import (
    convert_from_lrc,
    _seconds_to_timestamp,
    _parse_lrc,
    _to_srt,
    _to_vtt,
    _to_txt,
    _ParsedLine,
)


# ─── _seconds_to_timestamp ───────────────────────────────────────────────────

class TestSecondsToTimestamp:
    def test_zero_seconds(self):
        assert _seconds_to_timestamp(0) == "00:00:00,000"

    def test_one_second(self):
        assert _seconds_to_timestamp(1.0) == "00:00:01,000"

    def test_one_minute(self):
        assert _seconds_to_timestamp(60.0) == "00:01:00,000"

    def test_one_hour(self):
        assert _seconds_to_timestamp(3600.0) == "01:00:00,000"

    def test_with_milliseconds(self):
        assert _seconds_to_timestamp(1.5) == "00:00:01,500"

    def test_complex_timestamp(self):
        # 1h 23m 45s 整秒部分驗證
        total = 3600 + 23 * 60 + 45.0
        result = _seconds_to_timestamp(total)
        assert result == "01:23:45,000"

    def test_complex_timestamp_with_ms(self):
        # 浮點數精度：使用允許 ±1ms 誤差的方式驗證
        total = 3600 + 23 * 60 + 45 + 0.5
        result = _seconds_to_timestamp(total)
        assert result == "01:23:45,500"

    def test_dot_separator(self):
        """VTT 格式使用 '.' 分隔毫秒"""
        result = _seconds_to_timestamp(1.5, separator='.')
        assert result == "00:00:01.500"

    def test_negative_seconds_clamp_to_zero(self):
        """負數應被 clamp 為 0"""
        assert _seconds_to_timestamp(-5.0) == "00:00:00,000"


# ─── _parse_lrc ──────────────────────────────────────────────────────────────

class TestParseLrc:
    SAMPLE_LRC = (
        "[00:01.000]Hello world\n"
        "[00:05.500]This is a test\n"
        "[01:30.123]Final line\n"
    )

    def test_parse_basic_lrc(self):
        lines = _parse_lrc(self.SAMPLE_LRC)
        assert len(lines) == 3

    def test_parse_timestamps(self):
        lines = _parse_lrc(self.SAMPLE_LRC)
        assert abs(lines[0].time - 1.0) < 0.01
        assert abs(lines[1].time - 5.5) < 0.01
        assert abs(lines[2].time - 90.123) < 0.01

    def test_parse_text_content(self):
        lines = _parse_lrc(self.SAMPLE_LRC)
        assert lines[0].text == "Hello world"
        assert lines[1].text == "This is a test"

    def test_empty_input_returns_empty_list(self):
        assert _parse_lrc("") == []

    def test_none_like_empty_returns_empty_list(self):
        assert _parse_lrc(None) == []

    def test_no_valid_lines_returns_empty_list(self):
        assert _parse_lrc("This is not LRC format\n# comment") == []

    def test_speaker_label_is_removed(self):
        """'Speaker A: ' 標籤應被移除"""
        lrc = "[00:01.000]Speaker A: Hello there\n"
        lines = _parse_lrc(lrc)
        assert len(lines) == 1
        assert lines[0].text == "Hello there"

    def test_speaker_b_label_is_removed(self):
        lrc = "[00:02.000]Speaker B: Nice to meet you\n"
        lines = _parse_lrc(lrc)
        assert lines[0].text == "Nice to meet you"

    def test_three_digit_milliseconds(self):
        """支援 [mm:ss.xxx] 三位毫秒格式"""
        lrc = "[00:01.500]Text\n"
        lines = _parse_lrc(lrc)
        assert len(lines) == 1
        assert abs(lines[0].time - 1.5) < 0.001

    def test_two_digit_milliseconds(self):
        """支援 [mm:ss.xx] 兩位毫秒格式"""
        lrc = "[00:01.50]Text\n"
        lines = _parse_lrc(lrc)
        assert len(lines) == 1


# ─── _to_srt ─────────────────────────────────────────────────────────────────

class TestToSrt:
    def _make_lines(self):
        return [
            _ParsedLine(time=1.0, text="Hello"),
            _ParsedLine(time=5.0, text="World"),
        ]

    def test_srt_has_sequence_numbers(self):
        srt = _to_srt(self._make_lines())
        assert "1\n" in srt
        assert "2\n" in srt

    def test_srt_uses_comma_separator(self):
        srt = _to_srt(self._make_lines())
        assert "00:00:01,000 --> 00:00:05,000" in srt

    def test_last_line_has_five_second_duration(self):
        srt = _to_srt(self._make_lines())
        assert "00:00:05,000 --> 00:00:10,000" in srt

    def test_srt_contains_text(self):
        srt = _to_srt(self._make_lines())
        assert "Hello" in srt
        assert "World" in srt

    def test_empty_lines_returns_empty_string(self):
        assert _to_srt([]) == ""

    def test_single_line_gets_five_second_duration(self):
        lines = [_ParsedLine(time=2.0, text="Only line")]
        srt = _to_srt(lines)
        assert "00:00:02,000 --> 00:00:07,000" in srt


# ─── _to_vtt ─────────────────────────────────────────────────────────────────

class TestToVtt:
    def _make_lines(self):
        return [
            _ParsedLine(time=1.0, text="Hello"),
            _ParsedLine(time=5.0, text="World"),
        ]

    def test_vtt_starts_with_webvtt(self):
        vtt = _to_vtt(self._make_lines())
        assert vtt.startswith("WEBVTT")

    def test_vtt_uses_dot_separator(self):
        vtt = _to_vtt(self._make_lines())
        assert "00:00:01.000 --> 00:00:05.000" in vtt

    def test_vtt_contains_text(self):
        vtt = _to_vtt(self._make_lines())
        assert "Hello" in vtt
        assert "World" in vtt

    def test_empty_lines_returns_webvtt_header(self):
        vtt = _to_vtt([])
        assert "WEBVTT" in vtt


# ─── _to_txt ─────────────────────────────────────────────────────────────────

class TestToTxt:
    def test_txt_joins_lines(self):
        lines = [
            _ParsedLine(time=1.0, text="Hello"),
            _ParsedLine(time=5.0, text="World"),
        ]
        txt = _to_txt(lines)
        assert txt == "Hello\nWorld"

    def test_empty_lines_returns_empty_string(self):
        assert _to_txt([]) == ""


# ─── convert_from_lrc（整合） ────────────────────────────────────────────────

class TestConvertFromLrc:
    VALID_LRC = (
        "[00:01.000]Hello world\n"
        "[00:05.500]This is a test\n"
        "[01:30.123]Final line\n"
    )

    def test_returns_subtitle_formats_object(self):
        from app.services.converter.models import SubtitleFormats
        result = convert_from_lrc(self.VALID_LRC)
        assert isinstance(result, SubtitleFormats)

    def test_lrc_field_preserved(self):
        result = convert_from_lrc(self.VALID_LRC)
        assert result.lrc == self.VALID_LRC

    def test_srt_has_arrow(self):
        result = convert_from_lrc(self.VALID_LRC)
        assert "-->" in result.srt

    def test_vtt_starts_with_webvtt(self):
        result = convert_from_lrc(self.VALID_LRC)
        assert result.vtt.startswith("WEBVTT")

    def test_txt_has_text_content(self):
        result = convert_from_lrc(self.VALID_LRC)
        assert "Hello world" in result.txt

    def test_empty_input_returns_empty_formats(self):
        result = convert_from_lrc("")
        assert result.lrc == ""
        assert result.srt == ""
        assert result.vtt == ""
        assert result.txt == ""

    def test_whitespace_only_input_returns_empty_formats(self):
        result = convert_from_lrc("   \n  ")
        assert result.lrc == ""
        assert result.srt == ""

    def test_invalid_lrc_returns_original_lrc_empty_others(self):
        """無效 LRC 內容（無法解析行）應回傳原始 LRC，其他格式為空"""
        invalid = "This is not LRC\nJust plain text"
        result = convert_from_lrc(invalid)
        assert result.lrc == invalid
        assert result.srt == ""
        assert result.vtt == ""
        assert result.txt == ""

    def test_srt_sequence_numbers_correct(self):
        result = convert_from_lrc(self.VALID_LRC)
        lines = result.srt.split("\n")
        assert lines[0] == "1"

    def test_three_lines_produce_three_srt_blocks(self):
        result = convert_from_lrc(self.VALID_LRC)
        sequence_numbers = [
            line for line in result.srt.split("\n")
            if line.strip().isdigit()
        ]
        assert len(sequence_numbers) == 3

    def test_speaker_labels_stripped_in_txt(self):
        lrc = "[00:01.000]Speaker A: Hello\n[00:03.000]Speaker B: World\n"
        result = convert_from_lrc(lrc)
        assert "Speaker A:" not in result.txt
        assert "Speaker B:" not in result.txt
        assert "Hello" in result.txt
        assert "World" in result.txt
