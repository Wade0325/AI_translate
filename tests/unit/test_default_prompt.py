"""
單元測試：Prompt 模板組裝邏輯
測試範圍：core/default_prompt.py
"""
import pytest

from app.core.default_prompt import (
    build_prompt,
    DEFAULT_PROMPT_TEMPLATE,
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
        for name in LANG_MAP.values():
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


# ─── 使用者的提示詞裡的大括號（#143） ────────────────────────────────────────

# 以前能用的提示詞與送出的字串。期望值寫死，是 #143 修正前的 build_prompt 算出來的；
# 預設模板的措辭改了，default-template 這一項要跟著改
PROMPTS_THAT_WORKED_BEFORE = [
    pytest.param(
        {"source_lang": "ja-JP", "target_lang": "zh-TW", "multi_speaker": True},
        "你是一位專業的逐字稿專家。請將以下日文音檔精確轉錄為 LRC 格式。\n"
        "注意：\n"
        "1. 這是 ASMR 音檔，可能包含耳語、口腔音、環境音效等非語音聲音。\n"
        "2. 非語音的聲音請適當標注為描述（如：[耳語]、[水聲]）。\n"
        "3. 時間戳格式為 [mm:ss.xxx]（毫秒精確到三位），必須精確對應聲音的起始位置。\n"
        "4. 純靜默段落不要產生任何行。\n"
        "5. 每行文字請盡量簡短。\n"
        "6. 音檔中有多位說話者，請用 Speaker 1:、Speaker 2: 等標籤區分不同說話者。\n"
        "7. 請將所有轉錄內容翻譯為繁體中文輸出。",
        id="default-template"),
    pytest.param(
        {"source_lang": "ja-JP", "target_lang": "zh-TW", "multi_speaker": True,
         "template": "請把{source_lang}音檔轉成 LRC。\n{speaker_instruction}{translate_instruction}"},
        "請把日文音檔轉成 LRC。\n"
        "6. 音檔中有多位說話者，請用 Speaker 1:、Speaker 2: 等標籤區分不同說話者。\n"
        "7. 請將所有轉錄內容翻譯為繁體中文輸出。",
        id="custom-template-three-variables"),
    pytest.param(
        {"source_lang": "ja-JP",
         "template": "請把{source_lang}音檔轉成 LRC。\n{speaker_instruction}{translate_instruction}"},
        "請把日文音檔轉成 LRC。",
        id="custom-template-empty-instructions"),
    pytest.param(
        {"source_lang": "ja-JP", "multi_speaker": True,
         "template": '每一行輸出成 {{"speaker": "S0", "text": "…"}}，音檔是{source_lang}。\n'
                     "{speaker_instruction}"},
        '每一行輸出成 {"speaker": "S0", "text": "…"}，音檔是日文。\n'
        "6. 音檔中有多位說話者，請用 Speaker 1:、Speaker 2: 等標籤區分不同說話者。",
        id="escaped-braces"),
    pytest.param(
        {"source_lang": "ja-JP", "template": "{{source_lang}} 會換成{source_lang}"},
        "{source_lang} 會換成日文",
        id="escaped-variable-name"),
    pytest.param(
        {"template": "只要逐字稿，不要時間戳。\n\n"},
        "只要逐字稿，不要時間戳。",
        id="no-braces"),
]


class TestBracesInUserPrompt:
    """使用者的提示詞是模板：三個變數照樣代入，其他大括號照寫的送出，任務不會因此失敗。"""

    @pytest.mark.parametrize("kwargs, expected", PROMPTS_THAT_WORKED_BEFORE)
    def test_prompt_that_worked_before_is_sent_unchanged(self, kwargs, expected):
        assert build_prompt(**kwargs) == expected

    def test_variables_are_filled_in_next_to_other_braces(self):
        template = '請轉錄{source_lang}音檔，每一行寫成 {"text": "…"}\n{speaker_instruction}{translate_instruction}'

        prompt = build_prompt(
            source_lang="ja-JP", target_lang="zh-TW", multi_speaker=True, template=template)

        assert prompt == (
            '請轉錄日文音檔，每一行寫成 {"text": "…"}\n'
            "6. 音檔中有多位說話者，請用 Speaker 1:、Speaker 2: 等標籤區分不同說話者。\n"
            "7. 請將所有轉錄內容翻譯為繁體中文輸出。")

    @pytest.mark.parametrize("template", [
        pytest.param('每一行寫成 {"speaker": "S0", "text": "…"}', id="json"),
        pytest.param('輸出 {"segment": {"start": 0, "text": "…"}}', id="nested-json"),
        pytest.param("用 { 開頭的行是註解", id="lone-open-brace"),
        pytest.param("表情符號 :} 照寫", id="lone-close-brace"),
        pytest.param("把 {name} 換成說話者的名字", id="unknown-name"),
        pytest.param("空的 {} 照寫", id="empty-braces"),
        pytest.param("{source_lang.code}", id="attribute-of-a-variable"),
        pytest.param("{source_lang[x]}", id="index-of-a-variable"),
    ])
    def test_other_braces_are_sent_as_written(self, template):
        assert build_prompt(source_lang="ja-JP", template=template) == template

    def test_escapes_next_to_other_braces_are_sent_as_written(self):
        # 只有 {{ }} 時照舊收成單一大括號（見 escaped-variable-name）；旁邊有 str.format
        # 代入不了的大括號時照寫的送出，巢狀 JSON 結尾的 }} 才不會被改掉，跳脫的名稱也不代入
        template = '{{source_lang}} 會換成{source_lang}，例如 {"lang": "日文"}'

        prompt = build_prompt(source_lang="ja-JP", template=template)

        assert prompt == '{{source_lang}} 會換成日文，例如 {"lang": "日文"}'
