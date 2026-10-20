"""圈圈叉叉的規則：3x3 棋盤、輪流下子、悔手、勝負與平手判斷。

只碰規則，不讀 stdin 也不印東西；輸入輸出都交給 cli.py。
錯誤訊息（InvalidMoveError）是直接給使用者看的，所以用詞和 cli.py 一致。

用詞（GLOSSARY.md 沒有遊戲領域，這裡定義並統一使用）：
  棋盤（board）：3x3 共 9 格。
  格（cell）：棋盤上的一格。使用者輸入的是格號 1-9（由左而右、由上而下），
             程式內部的索引是 0-8，差 1。
  下子（play）／悔手（undo）／先手（first）／三連珠（winning line）／平手（draw）。
"""

from __future__ import annotations

from dataclasses import dataclass

MARK_X = "X"
MARK_O = "O"
EMPTY = " "

SIZE = 3
CELLS = SIZE * SIZE

WINNING_LINES: tuple[tuple[int, ...], ...] = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),  # 橫
    (0, 3, 6), (1, 4, 7), (2, 5, 8),  # 直
    (0, 4, 8), (2, 4, 6),             # 斜
)

# 給使用者看的位置名稱（索引 0-8，和格號一樣是由左而右、由上而下）
POSITION_NAMES: tuple[str, ...] = (
    "左上", "上", "右上",
    "左", "正中央", "右",
    "左下", "下", "右下",
)


class InvalidMoveError(ValueError):
    """這一步下不進去；訊息可直接顯示給使用者。"""


@dataclass(frozen=True)
class Result:
    """一局結束的結果。

    line 是三連珠的三格索引（0-8）；平手時 mark 與 line 都是 None。
    """

    mark: str | None
    line: tuple[int, ...] | None

    @property
    def is_draw(self) -> bool:
        return self.mark is None


def other(mark: str) -> str:
    """回傳對方用的記號。"""
    if mark == MARK_X:
        return MARK_O
    if mark == MARK_O:
        return MARK_X
    raise ValueError(f"不認識的記號：{mark!r}")


def parse_move(text: str) -> int:
    """把使用者輸入的格號（1-9）轉成棋盤索引（0-8）。

    接受全形數字（１２３）與前後空白：中文輸入法下常常誤輸入全形，
    挡掉只會讓使用者重打一次。int() 也接受 "+5"、"５"，所以範圍檢查在這裡做。
    """
    raw = text.strip()
    try:
        label = int(raw)
    except ValueError:
        raise InvalidMoveError(f"「{raw}」不是格號：請輸入棋盤上的數字 1-9") from None
    if not 1 <= label <= CELLS:
        raise InvalidMoveError(f"盤面上沒有第 {label} 格：請輸入 1-9 的數字")
    return label - 1


class Game:
    """一局圈圈叉叉：棋盤、輪到誰、悔手與結果。

    first 決定誰先下（預設 X）。同一局中記號和玩家綁定，換先手時由呼叫端
    決定（見 cli.py：下一局換對方先手，但每個玩家繼續用自己那一個記號）。
    """

    def __init__(self, first: str = MARK_X) -> None:
        if first not in (MARK_X, MARK_O):
            raise ValueError(f"先手的記號只能是 {MARK_X} 或 {MARK_O}：{first!r}")
        self.board: list[str] = [EMPTY] * CELLS
        self.turn: str = first
        # 下過的格（索引），由舊到新；悔手由這裡還原
        self.moves: list[int] = []

    def opponent(self) -> str:
        """輪到的玩家的對方（悔手之後要換回去）。"""
        return other(self.turn)

    def cell_label(self, cell: int) -> str:
        """索引（0-8）轉回給使用者看的格號（1-9）。"""
        return str(cell + 1)

    def line_labels(self, line: tuple[int, ...]) -> str:
        """三連珠的索引轉成「1-2-3」這種給使用者看的字串。"""
        return "-".join(self.cell_label(i) for i in line)

    def is_full(self) -> bool:
        return EMPTY not in self.board

    def winning_line(self, mark: str) -> tuple[int, ...] | None:
        """mark 已經連成三子的話回傳那三格，否則 None。"""
        for line in WINNING_LINES:
            if all(self.board[i] == mark for i in line):
                return line
        return None

    def result(self) -> Result | None:
        """回傳目前狀態：結束了回傳 Result，還沒結束回傳 None。"""
        for mark in (MARK_X, MARK_O):
            line = self.winning_line(mark)
            if line is not None:
                return Result(mark=mark, line=line)
        if self.is_full():
            return Result(mark=None, line=None)
        return None

    def is_over(self) -> bool:
        return self.result() is not None

    def play(self, cell: int) -> Result | None:
        """輪到的玩家在 cell（0-8）下子，回傳下完之後的結果；還沒結束回傳 None。

        下不進去時丟 InvalidMoveError：這一局已結束、索引不在 0-8、
        或那一格已經有子了。
        """
        finished = self.result()
        if finished is not None:
            raise InvalidMoveError("這一局已經結束，請開始新的一局")
        if not 0 <= cell < CELLS:
            raise InvalidMoveError(f"盤面上沒有第 {cell + 1} 格：請輸入 1-9 的數字")
        if self.board[cell] != EMPTY:
            occupied = self.board[cell]
            raise InvalidMoveError(
                f"第 {self.cell_label(cell)} 格（{POSITION_NAMES[cell]}）"
                f"已經有 {occupied} 了，換一格"
            )
        self.board[cell] = self.turn
        self.moves.append(cell)
        self.turn = other(self.turn)
        return self.result()

    def undo(self) -> bool:
        """收回上一手，換回剛剛下那一手的玩家。沒有手可收時回傳 False。"""
        if not self.moves:
            return False
        cell = self.moves.pop()
        self.board[cell] = EMPTY
        self.turn = other(self.turn)
        return True
