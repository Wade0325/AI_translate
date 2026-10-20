"""`python -m games.tictactoe` 的進入點。

只把輸出碼頁的錯誤處理改成 backslashreplace，避免 Windows 上遇到印不出的字元時
整個遊戲因為 UnicodeEncodeError 崩掉（和 tools/check.py 一樣的做法）。
"""

import sys

from games.tictactoe.cli import main

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass  # 輸出不是一般的 TextIOWrapper（例如被Redirect 掉）時就跳過
    sys.exit(main())
