"""
單元測試：圈圈叉叉的命令列介面
測試範圍：games/tictactoe/cli.py

把 stdin／stdout 換成 StringIO 跑整局遊戲，不用真的開終端機。
輸入字串最後都結尾一個換行，最後一個動作之後沒有輸入就是 EOF（等同 Ctrl+Z）。
"""
import io

import pytest

from games.tictactoe.cli import USAGE, main, render
from games.tictactoe.engine import Game

# X 沿第一行連成三子（O 下 4、5）
X_WINS = "1\n4\n2\n5\n3\n"


def run_cli(argv, text):
    """跑 main，回傳（結束碼, 輸出）。"""
    out = io.StringIO()
    code = main(argv, stdin=io.StringIO(text), stdout=out)
    return code, out.getvalue()


# ─── 棋盤顯示 ───────────────────────────────────────────────────────────────

class TestRender:
    def test_empty_board_shows_cell_numbers(self):
        """空棋盤顯示格號，使用者才知道要輸入什麼。"""
        board = render(Game())
        assert " 1 " in board and " 9 " in board
        assert "X" not in board and "O" not in board

    def test_played_cells_show_marks(self):
        game = Game()
        game.play(0)
        game.play(4)
        board = render(game)
        assert " X | 2 | 3" in board
        assert " O " in board
        assert " 5 " not in board


# ─── 一局：勝負 ─────────────────────────────────────────────────────────────

class TestOneRound:
    def test_x_win_is_announced_with_the_line(self):
        code, out = run_cli([], X_WINS + "n\n")
        assert code == 0
        assert "玩家一（X）獲勝" in out
        assert "三連珠：1-2-3" in out
        assert "計分板：玩家一（X）1 勝" in out
        assert "共玩了 1 局" in out

    def test_turn_prompts_both_players(self):
        _, out = run_cli([], X_WINS + "n\n")
        assert "玩家一（X）請輸入格號" in out
        assert "玩家二（O）請輸入格號" in out

    def test_draw_is_announced(self):
        # 下滿九格且誰都沒連成三子
        moves = "1\n2\n3\n4\n6\n5\n7\n9\n8\n"
        code, out = run_cli([], moves + "n\n")
        assert code == 0
        assert "平手！" in out
        assert "計分板：玩家一（X）0 勝" in out
        assert "平手 1" in out

    def test_names_from_arguments(self):
        _, out = run_cli(["小美", "小華"], X_WINS + "n\n")
        assert "小美 用 X" in out
        assert "小華 用 O" in out
        assert "小美（X）獲勝" in out

    def test_quitting_mid_round_is_not_scored(self):
        code, out = run_cli([], "1\n2\nq\n")
        assert code == 0
        assert "不玩了" in out
        assert "共玩了 0 局" in out

    def test_eof_ends_the_session(self):
        """管線輸入讀完（或 Ctrl+Z）也要正常結束，不卡在讀 input。"""
        code, out = run_cli([], "1\n")
        assert code == 0
        assert "輸入結束" in out
        assert "共玩了 0 局" in out


# ─── 輸入驗證與指令 ─────────────────────────────────────────────────────────

class TestCommands:
    def test_non_numeric_input_asks_the_same_player_again(self):
        _, out = run_cli([], "x\n" + X_WINS + "n\n")
        assert "不是格號" in out
        assert "玩家一（X）獲勝" in out

    def test_out_of_range_cell(self):
        _, out = run_cli([], "10\n" + X_WINS + "n\n")
        assert "盤面上沒有第 10 格" in out

    def test_taken_cell_keeps_the_turn(self):
        # X 下 1，O 也輸入 1 → 應該被擋掉，輪到 O 重輸入
        _, out = run_cli([], "1\n1\n4\n2\n5\n3\nn\n")
        assert "第 1 格（左上）已經有 X 了" in out
        assert "玩家一（X）獲勝" in out

    def test_help_command_shows_usage_twice(self):
        _, out = run_cli([], "h\nq\n")
        assert out.count(USAGE) >= 2

    def test_blank_input_is_ignored(self):
        _, out = run_cli([], "\n" + X_WINS + "n\n")
        assert "玩家一（X）獲勝" in out

    def test_undo_returns_turn_to_previous_player(self):
        # X 下 1，O 悔手 → 換回 X；X 再下 2 之後離開
        _, out = run_cli([], "1\nu\n2\nq\n")
        assert "已悔手" in out
        assert "共玩了 0 局" in out

    def test_undo_without_moves_is_refused(self):
        _, out = run_cli([], "u\nq\n")
        assert "還沒有下過子，不能悔手" in out


# ─── 多局 ───────────────────────────────────────────────────────────────────

class TestMultipleRounds:
    def test_play_again_continues_with_other_player_first(self):
        _, out = run_cli([], X_WINS + "y\n" + X_WINS + "n\n")
        assert "第 1 局：玩家一（X）先手" in out
        assert "第 2 局：玩家二（O）先手" in out
        # 第二局雖然一樣的下法，但輪到才先手的 O 沿 1-2-3 連成三子
        assert "玩家二（O）獲勝" in out
        assert "計分板：玩家一（X）1 勝｜玩家二（O）1 勝" in out
        assert "共玩了 2 局" in out

    def test_rounds_option_stops_without_asking(self):
        _, out = run_cli(["--rounds", "2"], X_WINS + X_WINS)
        assert "共玩了 2 局" in out
        assert "要再來一局嗎" not in out

    def test_invalid_answer_to_play_again_is_asked_again(self):
        _, out = run_cli([], X_WINS + "maybe\nn\n")
        assert "請輸入 y 或 n" in out
        assert "共玩了 1 局" in out

    def test_too_many_player_names_is_rejected(self):
        with pytest.raises(SystemExit):
            run_cli(["A", "B", "C"], "q\n")
