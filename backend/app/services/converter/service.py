"""相容層：輸出格式已收進 :mod:`app.services.output_format`。

批次（tasks/batch_core.py）與它用的 LRC 時間還原（transcription/flows.py 的
remap_lrc_timestamps）還從這個舊路徑匯入；批次改成只處理轉錄結果之後（#115），連同整個
converter 套件一起刪掉。
"""

from app.services.output_format import convert_from_lrc
from app.services.output_format import parse_lrc as _parse_lrc

__all__ = ["convert_from_lrc", "_parse_lrc"]
