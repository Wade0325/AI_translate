"""
送給模型的提示詞：提示詞範本加上補充說明（#144）。

- 提示詞範本：設定頁為供應商存的範本；沒存過（或只有空白）時用 DEFAULT_PROMPT_TEMPLATE，裡面要求
  輸出 LRC 與時間戳。範本代入下面三個變數，其他大括號（例如 JSON）照寫的送出，見 _fill：
    {source_lang}           — 音訊語言名稱（如 "日文"）
    {speaker_instruction}   — 多人模式指令（可為空）
    {translate_instruction} — 翻譯指令（可為空）
- 補充說明：轉錄頁填的提示詞（每個檔案自己的，沒有就是全域的），空一行接在範本後面，照寫的送出、
  不代入變數：範本已經代入過，再代入一次，說話者與翻譯的指示會重複。

DEFAULT_PROMPT_TEMPLATE 是系統內建範本的唯一真實來源：設定頁的「編輯參數」沒存過範本時從這裡帶出。
"""

import re
from typing import Optional

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
    target_lang: Optional[str] = None,
    multi_speaker: bool = False,
    template: Optional[str] = None,
    supplement: Optional[str] = None,
) -> str:
    """
    組出送給模型的提示詞：提示詞範本代入變數，再空一行接上補充說明（規則見檔頭）。

    Args:
        source_lang:   音訊語言代碼 (如 "ja-JP")
        target_lang:   翻譯目標語言代碼 (如 "zh-TW")，None 表示不翻譯
        multi_speaker: 是否為多人對話模式
        template:      設定頁存的提示詞範本；None 或只有空白時用 DEFAULT_PROMPT_TEMPLATE
        supplement:    補充說明（每個檔案的，沒有就是全域的提示詞）；None 或只有空白時只送範本
    """
    base_template = template if template and template.strip() else DEFAULT_PROMPT_TEMPLATE

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

    prompt = _fill(base_template, {
        "source_lang": source_name,
        "speaker_instruction": speaker_instruction,
        "translate_instruction": translate_instruction,
    }).rstrip("\n")
    if supplement and supplement.strip():
        prompt = f"{prompt}\n\n{supplement.strip()}"
    return prompt


def _fill(template: str, values: dict[str, str]) -> str:
    """把範本裡的變數換成值。

    str.format 代入得了的範本照舊由它代入（``{{``、``}}`` 收成單一大括號），以前能用的
    範本送出的字串逐字不變。

    代入不了的範本（使用者寫了 JSON、單獨的大括號或不認得的 ``{名稱}``，以前會讓任務
    失敗）只把寫成 ``{名稱}`` 的已知變數換成值，其他字元照寫的送出（#143）。這時
    ``{{``、``}}`` 不收成單一大括號，巢狀 JSON 結尾的 ``}}`` 才不會被改掉；但它們仍算
    跳脫，``{{source_lang}}`` 不會被代入。
    """
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError, AttributeError, TypeError):
        # {{、}} 先比對到就照寫的保留，裡面的名稱不會被當成變數；不認得的 {名稱} 也照寫的保留
        return re.sub(r"\{\{|\}\}|\{(\w+)\}",
                      lambda m: values.get(m.group(1), m.group(0)), template)
