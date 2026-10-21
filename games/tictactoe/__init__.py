"""雙人對戰的圈圈叉叉（tic-tac-toe）命令列遊戲。

規則（engine.py）和輸入輸出（cli.py）分開，兩邊都能單獨測：

    python -m games.tictactoe            # 玩家一 vs 玩家二
    python -m games.tictactoe 小美 小華  # 自訂稱呼
"""

from games.tictactoe.engine import Game, InvalidMoveError, Result

__all__ = ["Game", "InvalidMoveError", "Result"]
