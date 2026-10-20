"""圈圈叉叉的命令列介面：兩位玩家輪流在同一個終端機輸入格號。

    python -m games.tictactoe              # 稱呼是「玩家一」「玩家二」
    python -m games.tictactoe 小美 小華    # 自訂稱呼（玩家一用 X 並先手）
    python -m games.tictactoe --rounds 3   # 打三局；不給就一直玩到輸入 n

規則都在 engine.py；這裡只負責讀輸入、印棋盤與結果，以及計分。
main() 的 stdin／stdout 可以換掉，所以測試不用真的開終端機。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from games.tictactoe.engine import (
    CELLS,
    EMPTY,
    MARK_O,
    MARK_X,
    SIZE,
    Game,
    InvalidMoveError,
    Result,
    parse_move,
)

DEFAULT_NAMES = ("玩家一", "玩家二")

USAGE = "指令：1-9 下在該格｜u 悔一手｜h 顯示指令說明｜q 結束遊戲"

# 棋盤的分隔線；只用 ASCII 的 |、-、+：Windows 終端機常用 Big5 碼頁（cp950），
# 方框線的 │ 在某些碼頁印不出來，ASCII 不會有這個問題
SEPARATOR = "---+---+---"

# 讀一行的函式：印出提示後讀使用者輸入的一行（不含換行）；
# 輸入結束（管線讀完、Ctrl+Z／Ctrl+D）時回傳 None
ReadLine = Callable[[str], str | None]

Writer = Callable[[str], None]


def render(game: Game) -> str:
    """把棋盤變成一個字串：空格顯示格號（1-9），下過的格子顯示 X 或 O。"""
    rows = []
    for row in range(SIZE):
        cells = []
        for col in range(SIZE):
            index = row * SIZE + col
            mark = game.board[index]
            cells.append(mark if mark != EMPTY else str(index + 1))
        rows.append("|".join(f" {cell} " for cell in cells))
    return f"\n{SEPARATOR}\n".join(rows)


def score_line(scores: dict[str, int], draws: int, names: dict[str, str]) -> str:
    """計分板的一行：誰幾勝、誰幾勝、幾次平手。"""
    return (
        f"計分板：{names[MARK_X]}（X）{scores[MARK_X]} 勝｜"
        f"{names[MARK_O]}（O）{scores[MARK_O]} 勝｜平手 {draws}"
    )


def describe_result(result: Result, game: Game, names: dict[str, str]) -> str:
    """一句話說明這局怎麼結束（直接給使用者看）。"""
    if result.is_draw:
        return f"平手！{CELLS} 格都滿了，誰都沒有連成三子。"
    mark = result.mark or MARK_X
    return f"{names[mark]}（{mark}）獲勝！三連珠：{game.line_labels(result.line or ())}"


def run_round(game: Game, names: dict[str, str], write: Writer,
              readline: ReadLine) -> Result | None:
    """打完一局。

    回傳這局的結果；使用者中途輸入 q 或輸入結束（EOF）時回傳 None，
    這一局不算成績。輸入不合法就講明原因並重問同一個人，換人不算。
    """
    write(render(game))
    write(USAGE)
    while True:
        player = names[game.turn]
        line = readline(f"{player}（{game.turn}）請輸入格號：")
        if line is None:
            write("輸入結束，這一局不算。")
            return None
        command = line.strip().lower()
        if command in ("q", "quit", "exit"):
            write("好，不玩了。")
            return None
        if command in ("h", "help", "?"):
            write(USAGE)
            continue
        if command in ("u", "undo"):
            if game.undo():
                write(f"已悔手，換 {names[game.turn]}（{game.turn}）想一想。")
            else:
                write("這一局還沒有下過子，不能悔手。")
            continue
        if not command:
            continue
        try:
            result = game.play(parse_move(command))
        except InvalidMoveError as error:
            write(str(error))
            continue
        write(render(game))
        if result is not None:
            write(describe_result(result, game, names))
            return result


def ask_play_again(write: Writer, readline: ReadLine) -> bool:
    """問要不要再來一局：y 繼續，n（或 EOF、q）結束，其他輸入再問一次。"""
    while True:
        answer = readline("要再來一局嗎？(y/n)：")
        if answer is None:
            return False
        command = answer.strip().lower()
        if command in ("y", "yes"):
            return True
        if command in ("n", "no", "q", "quit", "exit"):
            return False
        write("請輸入 y 或 n。")


def play_session(names: dict[str, str], rounds: int | None, write: Writer,
                 readline: ReadLine) -> int:
    """整個遊戲 session：一局接一局，直到使用者不玩了或打滿 rounds 局。

    回傳打完並算成績的局數。每一局換對方先手，但玩家和記號（X／O）固定不變，
    這樣計分板上的「誰幾勝」才不會錯亂。
    """
    scores = {MARK_X: 0, MARK_O: 0}
    draws = 0
    first = MARK_X
    played = 0
    while True:
        game = Game(first=first)
        write(f"\n=== 第 {played + 1} 局：{names[first]}（{first}）先手 ===")
        result = run_round(game, names, write, readline)
        if result is None:
            break
        played += 1
        if result.is_draw:
            draws += 1
        else:
            scores[result.mark or MARK_X] += 1
        write(score_line(scores, draws, names))
        if rounds is not None:
            # 指定局數時不用問，直接下一局（除非已經打滿）
            if played >= rounds:
                break
        elif not ask_play_again(write, readline):
            break
        first = MARK_O if first == MARK_X else MARK_X
    write(f"\n遊戲結束，共玩了 {played} 局。{score_line(scores, draws, names)}")
    return played


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m games.tictactoe",
        description="雙人對戰的圈圈叉叉：同一個終端機輪流輸入格號 1-9。",
    )
    parser.add_argument("names", nargs="*", metavar="玩家名稱",
                        help=f"兩位玩家的稱呼，最多兩個（預設：{'、'.join(DEFAULT_NAMES)}）")
    parser.add_argument("--rounds", type=int, metavar="N", default=None,
                        help="打滿 N 局就結束；不給就一直玩到輸入 n")
    args = parser.parse_args(argv)
    if len(args.names) > 2:
        parser.error(f"玩家只能有兩位，多出來的是：{'、'.join(args.names[2:])}")
    if args.rounds is not None and args.rounds < 1:
        parser.error(f"--rounds 至少要 1 局，給的是 {args.rounds}")
    return args


def main(argv: Sequence[str] | None = None, stdin: TextIO | None = None,
         stdout: TextIO | None = None) -> int:
    """遊戲入口。stdin／stdout 可換成測試給的 StringIO，不用真的開終端機。"""
    args = _parse_args(argv)
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout

    given = list(args.names) + list(DEFAULT_NAMES)
    name_x, name_o = given[0], given[1]
    names = {MARK_X: name_x, MARK_O: name_o}

    def write(text: str) -> None:
        print(text, file=stdout)

    def readline(prompt: str) -> str | None:
        """印提示、讀一行；讀到 EOF 回傳 None（管線結束、Ctrl+Z）。"""
        print(prompt, end="", file=stdout, flush=True)
        line = stdin.readline()
        if line == "":
            return None
        # 互動輸入時終端機自己會換行；管線或 StringIO 輸入時不會，補一個換行讓輸出整齊
        if not line.endswith("\n"):
            print(file=stdout)
        return line.rstrip("\r\n")

    write("圈圈叉叉：在橫、直、斜任一方向先連成三子的人獲勝。")
    write(f"{name_x} 用 X，{name_o} 用 O。第一局 {name_x} 先手。")
    play_session(names, args.rounds, write, readline)
    return 0
