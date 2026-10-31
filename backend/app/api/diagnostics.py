"""設定頁「複製診斷資訊」（#24）：回報問題時貼進 GitHub Issue 的一段文字。

內容與去識別的做法見 :mod:`app.services.diagnostics`；app 不會自己送出這段文字（ADR-0005）。
"""

from fastapi import APIRouter

from app.services import diagnostics

router = APIRouter()


@router.get("")
def diagnostics_report():
    """``{"text": 診斷資訊}``：版本、執行模式、作業系統、顯卡與本機模型權重等，不含檔名、金鑰、
    路徑與轉錄內容。會問顯卡、nvidia-smi 與 ffmpeg，只在使用者按下按鈕時呼叫。"""
    return {"text": diagnostics.report()}
