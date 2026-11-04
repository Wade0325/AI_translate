"""
送給模型的提示詞：提示詞範本加上補充說明（#144）。

- 提示詞範本：設定頁為供應商存的範本；沒存過（或只有空白）時用 DEFAULT_PROMPT_TEMPLATE，裡面要求
  輸出 LRC 與時間戳。範本代入下面三個變數，其他大括號（例如 JSON）照寫的送出，見 _fill：
    {source_lang}           — 音訊語言名稱（如 "日文"）；選 Auto Detect 時是空字串，不寫語言（#261）
    {speaker_instruction}   — 多人模式指令（可為空）
    {translate_instruction} — 翻譯指令（可為空）
- 補充說明：轉錄頁填的提示詞（每個檔案自己的，沒有就是全域的），空一行接在範本後面，照寫的送出、
  不代入變數：範本已經代入過，再代入一次，說話者與翻譯的指示會重複。
- 附了使用者文稿時（#66）不用提示詞範本，改用 build_user_text_prompt：只替文稿補上時間戳，補充說明
  一樣接在後面。

DEFAULT_PROMPT_TEMPLATE 是系統內建範本的唯一真實來源：設定頁的「編輯參數」沒存過範本時從這裡帶出。
"""

import re
from typing import Optional

# 語言代碼 → 寫進提示詞的語言名稱。轉錄頁語言選單（frontend/src/constants/languages.js）上的
# 每一種都要有，由 tests/unit/test_default_prompt.py 對齊。ja-JP、en-US、zh-CN 是舊紀錄與直接呼叫
# API 會帶的代碼（重新轉錄沿用任務當初的語言）；zh-CN 照 ADR-0002 當成中文，一樣輸出繁體
LANG_MAP = {
    "ja": "日文",
    "zh-TW": "繁體中文",
    "en": "英文",
    "ko": "韓文",
    "fr": "法文",
    "de": "德文",
    "es": "西班牙文",
    "pt": "葡萄牙文",
    "it": "義大利文",
    "nl": "荷蘭文",
    "ru": "俄文",
    "ar": "阿拉伯文",
    "hi": "印地文",
    "th": "泰文",
    "vi": "越南文",
    "id": "印尼文",
    "ja-JP": "日文",
    "en-US": "英文",
    "zh-CN": "中文",
}

# 轉錄頁的 Auto Detect：不是一種語言，提示詞不寫語言，由模型自己判斷
AUTO_DETECT = "auto"

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

# 附了使用者文稿時改用這份（#66）：模型只替文稿補上時間戳，不重新轉錄。和提示詞範本一樣要求 LRC 與
# [mm:ss.xxx]，Gemini 轉接器照同一套規則解析。使用者文稿接在最後，不代入變數：文稿裡的大括號照寫的送出
USER_TEXT_PROMPT_TEMPLATE = (
    "你是一位專業的逐字稿專家。下面是使用者為這個{source_lang}音檔提供的完整逐字稿。"
    "請不要重新轉錄，只替這份逐字稿補上時間戳，輸出 LRC 格式。\n"
    "注意：\n"
    "1. 逐字稿的文字照原樣寫出，不要增刪、改寫或翻譯；一句太長時可以斷成幾行。\n"
    "2. 每一行開頭都要有時間戳，格式為 [mm:ss.xxx]（毫秒精確到三位），必須精確對應這一行開始說話的位置。\n"
    "3. 逐字稿裡沒有的聲音不要寫出來。\n"
    "{speaker_instruction}"
)

USER_TEXT_SPEAKER_INSTRUCTION = (
    "4. 音檔中有多位說話者，請用 Speaker 1:、Speaker 2: 等標籤區分不同說話者。\n"
)


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
        source_lang:   音訊語言代碼 (如 "ja")；"auto" 或空字串時提示詞不寫語言
        target_lang:   翻譯目標語言代碼 (如 "zh-TW")，None 表示不翻譯
        multi_speaker: 是否為多人對話模式
        template:      設定頁存的提示詞範本；None 或只有空白時用 DEFAULT_PROMPT_TEMPLATE
        supplement:    補充說明（每個檔案的，沒有就是全域的提示詞）；None 或只有空白時只送範本
    """
    base_template = template if template and template.strip() else DEFAULT_PROMPT_TEMPLATE

    source_name = _language_name(source_lang)

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
    return _with_supplement(prompt, supplement)


def build_user_text_prompt(
    user_text: str,
    source_lang: str = "ja-JP",
    multi_speaker: bool = False,
    supplement: Optional[str] = None,
) -> str:
    """附了使用者文稿時送給模型的提示詞：只替文稿補上時間戳（#66）。

    取代提示詞範本：範本要求的是重新轉錄。補充說明照樣空一行接在最後。不翻譯：使用者文稿照原樣寫出。

    Args:
        user_text:     使用者文稿；前後的空白去掉，其他照寫的送出
        source_lang:   音訊語言代碼，規則同 :func:`build_prompt`
        multi_speaker: 是否為多人對話模式：要求模型標出說話者代號
        supplement:    補充說明；None 或只有空白時不接
    """
    instructions = USER_TEXT_PROMPT_TEMPLATE.format(
        source_lang=_language_name(source_lang),
        speaker_instruction=USER_TEXT_SPEAKER_INSTRUCTION if multi_speaker else "",
    )
    prompt = f"{instructions}\n完整逐字稿：\n---\n{user_text.strip()}\n---"
    return _with_supplement(prompt, supplement)


def _with_supplement(prompt: str, supplement: Optional[str]) -> str:
    """空一行接上補充說明（照寫的送出、不代入變數）；None 或只有空白時照原樣。"""
    if supplement and supplement.strip():
        return f"{prompt}\n\n{supplement.strip()}"
    return prompt


def _language_name(source_lang: str) -> str:
    """寫進提示詞的語言名稱：Auto Detect（不分大小寫）或沒指定時是空字串，不認得的代碼照寫。

    提示詞範本寫成「請將以下{source_lang}音檔」，空字串代入後就是「請將以下音檔」（#261）。
    """
    code = (source_lang or "").strip()
    if code.lower() in ("", AUTO_DETECT):
        return ""
    return LANG_MAP.get(code, code)


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
