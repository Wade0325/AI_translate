"""
單元測試：Prompt 模板組裝邏輯
測試範圍：core/default_prompt.py
"""
import pytest
from app.core.default_prompt import (
    build_prompt,
    DEFAULT_PROMPT_TEMPLATE,
    SPEAKER_INSTRUCTION,
    TRANSLATE_INSTRUCTION,
    LANG_MAP,
)


# ─── LANG_MAP ────────────────────────────────────────────────────────────────

class TestLangMap:
    def test_lang_map_is_dict(self):
        assert isinstance(LANG_MAP, dict)

    def test_lang_map_has_common_languages(self):
        assert "ja-JP" in LANG_MAP
        assert "zh-TW" in LANG_MAP
        assert "en-US" in LANG_MAP

    def test_lang_map_values_are_nonempty_strings(self):
        for code, name in LANG_MAP.items():
            assert isinstance(name, str) and len(name) > 0


# ─── DEFAULT_PROMPT_TEMPLATE ─────────────────────────────────────────────────

class TestDefaultPromptTemplate:
    def test_template_contains_source_lang_placeholder(self):
        assert "{source_lang}" in DEFAULT_PROMPT_TEMPLATE

    def test_template_contains_speaker_instruction_placeholder(self):
        assert "{speaker_instruction}" in DEFAULT_PROMPT_TEMPLATE

    def test_template_contains_translate_instruction_placeholder(self):
        assert "{translate_instruction}" in DEFAULT_PROMPT_TEMPLATE

    def test_template_mentions_lrc_format(self):
        assert "LRC" in DEFAULT_PROMPT_TEMPLATE


# ─── build_prompt ────────────────────────────────────────────────────────────

class TestBuildPrompt:
    def test_source_lang_code_replaced_with_display_name(self):
        prompt = build_prompt(source_lang="ja-JP")
        assert "日文" in prompt
        assert "ja-JP" not in prompt

    def test_unknown_source_lang_code_used_as_is(self):
        prompt = build_prompt(source_lang="xx-XX")
        assert "xx-XX" in prompt

    def test_no_target_lang_no_translate_instruction(self):
        prompt = build_prompt(source_lang="ja-JP", target_lang=None)
        assert "翻譯" not in prompt

    def test_same_source_and_target_lang_no_translate_instruction(self):
        prompt = build_prompt(source_lang="ja-JP", target_lang="ja-JP")
        assert "翻譯" not in prompt

    def test_different_target_lang_has_translate_instruction(self):
        prompt = build_prompt(source_lang="ja-JP", target_lang="zh-TW")
        assert "翻譯" in prompt

    def test_translate_instruction_contains_target_language_name(self):
        prompt = build_prompt(source_lang="ja-JP", target_lang="zh-TW")
        assert "繁體中文" in prompt

    def test_translate_instruction_contains_english_target(self):
        prompt = build_prompt(source_lang="ja-JP", target_lang="en-US")
        assert "英文" in prompt

    def test_no_multi_speaker_no_speaker_instruction(self):
        prompt = build_prompt(source_lang="ja-JP", multi_speaker=False)
        assert "Speaker" not in prompt

    def test_multi_speaker_has_speaker_instruction(self):
        prompt = build_prompt(source_lang="ja-JP", multi_speaker=True)
        assert "Speaker" in prompt

    def test_translate_instruction_number_is_6_without_multi_speaker(self):
        """無多人模式時翻譯指令編號應為 6"""
        prompt = build_prompt(source_lang="ja-JP", target_lang="zh-TW", multi_speaker=False)
        assert "6." in prompt

    def test_translate_instruction_number_is_7_with_multi_speaker(self):
        """有多人模式時翻譯指令編號應為 7（因為多人模式佔了第 6 條）"""
        prompt = build_prompt(source_lang="ja-JP", target_lang="zh-TW", multi_speaker=True)
        assert "7." in prompt

    def test_custom_template_overrides_default(self):
        custom = "Custom: {source_lang}{speaker_instruction}{translate_instruction}"
        prompt = build_prompt(source_lang="ja-JP", template=custom)
        assert prompt.startswith("Custom: 日文")

    def test_result_is_string(self):
        result = build_prompt()
        assert isinstance(result, str)

    def test_result_not_empty(self):
        result = build_prompt()
        assert len(result) > 0

    def test_trailing_newline_stripped(self):
        """build_prompt 結果不應以換行結尾（rstrip 邏輯）"""
        result = build_prompt(source_lang="ja-JP")
        assert not result.endswith("\n")

    def test_full_combination(self):
        """完整組合：有翻譯 + 多人模式"""
        prompt = build_prompt(
            source_lang="ja-JP",
            target_lang="zh-TW",
            multi_speaker=True,
        )
        assert "日文" in prompt
        assert "繁體中文" in prompt
        assert "Speaker" in prompt
        assert "7." in prompt
