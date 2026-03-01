"""
系統預設 Prompt 模板 — 唯一真實來源 (Single Source of Truth)

模板變數：
  {source_lang}           — 音訊語言名稱（如 "日文"）
  {speaker_instruction}   — 多人模式指令（可為空）
  {translate_instruction} — 翻譯指令（可為空）

修改此檔案即可同步影響前後端所有行為。
"""

# 語言代碼 → 顯示名稱對照表
LANG_MAP = {
    "zh-TW": "繁體中文",
    "en-US": "英文",
    "ja-JP": "日文",
}

DEFAULT_PROMPT_TEMPLATE = (
    "你是一位專業的逐字稿專家。請將以下{source_lang}音檔精確轉錄為 LRC 格式。\n"
    "注意：\n"
    "1. 這是 ASMR 音檔，可能包含耳語、口腔音、環境音效等非語音聲音。\n"
    "2. 非語音的聲音請適當標注為描述（如：[耳語]、[水聲]）。\n"
    "3. 時間戳格式為 [mm:ss.xxx]（毫秒精確到三位），必須精確對應聲音的起始位置。\n"
    "4. 純靜默段落不要產生任何行。\n"
    "5. 每行文字請盡量簡短。\n"
    "{speaker_instruction}"
    "{translate_instruction}"
)

SPEAKER_INSTRUCTION = (
    "6. 音檔中有多位說話者，請用 Speaker 1:、Speaker 2: 等標籤區分不同說話者。\n"
)

TRANSLATE_INSTRUCTION = "{n}. 請將所有轉錄內容翻譯為{target_lang}輸出。\n"


def build_prompt(
    source_lang: str = "ja-JP",
    target_lang: str = None,
    multi_speaker: bool = False,
    template: str = None,
) -> str:
    """
    根據前端參數動態組裝最終 Prompt。

    Args:
        source_lang:   音訊語言代碼 (如 "ja-JP")
        target_lang:   翻譯目標語言代碼 (如 "zh-TW")，None 表示不翻譯
        multi_speaker: 是否為多人對話模式
        template:      自訂 Prompt 模板（來自 DB），None 時使用 DEFAULT_PROMPT_TEMPLATE
    """
    base_template = template if template is not None else DEFAULT_PROMPT_TEMPLATE

    source_name = LANG_MAP.get(source_lang, source_lang)

    speaker_instruction = SPEAKER_INSTRUCTION if multi_speaker else ""

    # 計算翻譯指令的編號（第 6 或第 7 條，取決於是否有多人指令）
    if target_lang and target_lang != source_lang:
        target_name = LANG_MAP.get(target_lang, target_lang)
        n = 7 if multi_speaker else 6
        translate_instruction = TRANSLATE_INSTRUCTION.format(
            n=n, target_lang=target_name
        )
    else:
        translate_instruction = ""

    return base_template.format(
        source_lang=source_name,
        speaker_instruction=speaker_instruction,
        translate_instruction=translate_instruction,
    ).rstrip("\n")
