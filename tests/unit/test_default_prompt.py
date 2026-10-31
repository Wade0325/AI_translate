"""
單元測試：送給模型的提示詞怎麼組（提示詞範本代入變數，接上補充說明）
測試範圍：core/default_prompt.py
"""
import re
from pathlib import Path

import pytest

from app.core.default_prompt import (
    build_prompt,
    DEFAULT_PROMPT_TEMPLATE,
    LANG_MAP,
)

FRONTEND_LANGUAGES = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "constants" / "languages.js"
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


# ─── 提示詞寫語言名稱，Auto Detect 時不寫語言（#261） ─────────────────────────

def _menu_languages(source: str) -> set[str]:
    """轉錄頁語言選單上的語言代碼，不含 Auto Detect（它不是一種語言）。

    每個寫了 ``value:`` 的地方都要讀得出代碼：改了寫法（引號、換行）讀不出來時測試失敗，
    不會少比對幾種語言還是綠燈。
    """
    codes = re.findall(r"""\bvalue:\s*(['"])([^'"]+)\1""", source)
    assert codes, "languages.js 找不到語言選項"
    assert len(codes) == len(re.findall(r"\bvalue:", source)), "languages.js 有讀不出代碼的語言選項"
    return {code for _, code in codes} - {"auto"}


class TestSourceLanguageInPrompt:
    """提示詞寫語言名稱，不寫語言代碼；選 Auto Detect 時不寫語言，由模型自己判斷（#261）。"""

    @pytest.mark.parametrize("source_lang", ["auto", "AUTO", " auto ", ""],
                             ids=["auto", "upper-case", "spaces", "empty"])
    def test_auto_detect_writes_no_language(self, source_lang):
        prompt = build_prompt(source_lang=source_lang)

        assert prompt.startswith("你是一位專業的逐字稿專家。請將以下音檔精確轉錄為 LRC 格式。\n")
        assert "auto" not in prompt.lower()

    @pytest.mark.parametrize("source_lang, name", [
        pytest.param("ja", "日文", id="japanese"),
        pytest.param("zh-TW", "繁體中文", id="chinese"),
        # 舊紀錄與直接呼叫 API 帶的代碼；重新轉錄沿用任務當初的語言
        pytest.param("ja-JP", "日文", id="japanese-with-region"),
        pytest.param("zh-CN", "中文", id="simplified-chinese-on-old-records"),
    ])
    def test_language_is_written_by_name(self, source_lang, name):
        prompt = build_prompt(source_lang=source_lang)

        assert prompt.startswith(f"你是一位專業的逐字稿專家。請將以下{name}音檔精確轉錄為 LRC 格式。\n")
        assert source_lang not in prompt

    def test_every_language_on_the_menu_has_a_name(self):
        # 後端映像的 build context 只有 backend/，兩邊各自宣告一份，由這個測試對齊
        menu = _menu_languages(FRONTEND_LANGUAGES.read_text(encoding="utf-8"))

        assert menu - LANG_MAP.keys() == set()

    def test_auto_detect_writes_no_language_in_the_template_saved_in_settings(self):
        template = "請把{source_lang}音檔轉成 LRC。\n{speaker_instruction}"

        assert build_prompt(source_lang="auto", template=template) == "請把音檔轉成 LRC。"
        assert build_prompt(source_lang="ja", template=template) == "請把日文音檔轉成 LRC。"

    def test_auto_detect_keeps_the_translation_instruction(self):
        prompt = build_prompt(source_lang="auto", target_lang="zh-TW")

        assert prompt.endswith("6. 請將所有轉錄內容翻譯為繁體中文輸出。")


# ─── 提示詞範本裡的大括號（#143） ────────────────────────────────────────────

# 以前能用的提示詞範本與送出的字串。期望值寫死，是 #143 修正前的 build_prompt 算出來的；
# 系統內建範本的措辭改了，default-template 這一項要跟著改
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


class TestBracesInTemplate:
    """設定頁存的提示詞範本：三個變數照樣代入，其他大括號照寫的送出，任務不會因此失敗。"""

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


# ─── 補充說明接在提示詞範本後面（#144） ──────────────────────────────────────

class TestSupplementAfterTemplate:
    """轉錄頁填的提示詞（每個檔案的，沒有就是全域的）是補充說明：空一行接在提示詞範本後面，照寫的送出。

    「範本單獨送出時的樣子」由上面寫死的期望值鎖住，這裡拿它當前半段比對。
    """

    def test_supplement_follows_the_built_in_template(self):
        prompt = build_prompt(source_lang="ja-JP", supplement="說話者是兩位主持人")

        assert prompt == build_prompt(source_lang="ja-JP") + "\n\n說話者是兩位主持人"

    def test_supplement_follows_the_template_saved_in_settings(self):
        prompt = build_prompt(
            source_lang="ja-JP", multi_speaker=True,
            template="請把{source_lang}音檔轉成 LRC。\n{speaker_instruction}",
            supplement="人名照寫：佐藤、鈴木")

        assert prompt == (
            "請把日文音檔轉成 LRC。\n"
            "6. 音檔中有多位說話者，請用 Speaker 1:、Speaker 2: 等標籤區分不同說話者。\n"
            "\n"
            "人名照寫：佐藤、鈴木")

    @pytest.mark.parametrize("supplement", [
        pytest.param("說話者是兩位主持人", id="note"),
        pytest.param("只要逐字稿，不要時間戳。", id="contradicts-the-template"),
        pytest.param("{speaker_instruction}{translate_instruction}", id="template-variables"),
    ])
    @pytest.mark.parametrize("settings", [
        pytest.param({}, id="single-speaker"),
        pytest.param({"multi_speaker": True, "target_lang": "zh-TW"}, id="speakers-and-translation"),
    ])
    def test_template_instructions_are_always_kept(self, supplement, settings):
        # 範本整份留在前面：要求 LRC 與時間戳的指示，以及說話者、翻譯的指示，一個字都不少
        template_alone = build_prompt(source_lang="ja-JP", **settings)

        prompt = build_prompt(source_lang="ja-JP", supplement=supplement, **settings)

        assert prompt.startswith(template_alone + "\n\n")
        assert "LRC 格式" in prompt
        assert "時間戳格式為 [mm:ss.xxx]" in prompt

    @pytest.mark.parametrize("supplement", [
        pytest.param('每一行寫成 {"speaker": "S0", "text": "…"}', id="json"),
        pytest.param('輸出 {"segment": {"start": 0, "text": "…"}}', id="nested-json"),
        pytest.param("用 { 開頭的行是註解", id="lone-open-brace"),
        pytest.param("表情符號 :} 照寫", id="lone-close-brace"),
        pytest.param("把 {name} 換成說話者的名字", id="unknown-name"),
        pytest.param("{{source_lang}} 照寫", id="escaped-variable-name"),
        pytest.param("音檔是{source_lang}", id="template-variable"),
    ])
    def test_braces_in_the_supplement_are_sent_as_written(self, supplement):
        # 補充說明不代入變數：範本已經代入過，再代入一次，說話者與翻譯的指示會重複
        prompt = build_prompt(source_lang="ja-JP", multi_speaker=True, supplement=supplement)

        assert prompt == build_prompt(source_lang="ja-JP", multi_speaker=True) + "\n\n" + supplement

    @pytest.mark.parametrize("supplement", [None, "", " \n\t", "　"],
                             ids=["none", "empty", "blank", "full-width-space"])
    def test_blank_supplement_sends_the_template_alone(self, supplement):
        assert build_prompt(source_lang="ja-JP", supplement=supplement) == build_prompt(
            source_lang="ja-JP")

    def test_blank_lines_around_the_supplement_are_not_sent(self):
        prompt = build_prompt(source_lang="ja-JP", supplement="\n\n人名照寫：佐藤\n \n")

        assert prompt == build_prompt(source_lang="ja-JP") + "\n\n人名照寫：佐藤"

    @pytest.mark.parametrize("template", ["", "  \n"], ids=["empty", "blank"])
    def test_blank_template_saved_in_settings_means_the_built_in_template(self, template):
        # 設定頁把範本清空再存，存下的是空字串：和沒存過一樣用系統內建的範本
        prompt = build_prompt(source_lang="ja-JP", template=template, supplement="人名照寫：佐藤")

        assert prompt == build_prompt(source_lang="ja-JP") + "\n\n人名照寫：佐藤"
