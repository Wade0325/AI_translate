"""
單元測試：圈圈叉叉的規則
測試範圍：games/tictactoe/engine.py
"""
from dataclasses import FrozenInstanceError

import pytest

from games.tictactoe.engine import (
    EMPTY,
    MARK_O,
    MARK_X,
    Game,
    InvalidMoveError,
    Result,
    other,
    parse_move,
)


# ─── parse_move：格號（1-9）→ 索引（0-8）────────────────────────────────────

class TestParseMove:
    def test_returns_zero_based_index(self):
        assert parse_move("1") == 0
        assert parse_move("9") == 8

    def test_strips_surrounding_space(self):
        assert parse_move("  5 ") == 4

    def test_accepts_fullwidth_digits(self):
        """中文輸入法下常誤輸入全形數字，要接受而不是擋掉。"""
        assert parse_move("５") == 4

    def test_rejects_non_numeric(self):
        with pytest.raises(InvalidMoveError, match="不是格號"):
            parse_move("x")

    def test_rejects_empty_input(self):
        with pytest.raises(InvalidMoveError, match="不是格號"):
            parse_move("   ")

    @pytest.mark.parametrize("label", ["0", "10", "-1"])
    def test_rejects_out_of_range(self, label):
        with pytest.raises(InvalidMoveError, match="請輸入 1-9"):
            parse_move(label)


# ─── 記號與先手 ─────────────────────────────────────────────────────────────

class TestMarks:
    def test_other_swaps_marks(self):
        assert other(MARK_X) == MARK_O
        assert other(MARK_O) == MARK_X

    def test_other_rejects_unknown_mark(self):
        with pytest.raises(ValueError):
            other("Z")

    def test_default_first_player_is_x(self):
        assert Game().turn == MARK_X

    def test_first_player_can_be_o(self):
        assert Game(first=MARK_O).turn == MARK_O

    def test_rejects_unknown_first_mark(self):
        with pytest.raises(ValueError):
            Game(first="Z")


# ─── Game.play ───────────────────────────────────────────────────────────────

class TestPlay:
    def test_board_starts_empty(self):
        assert Game().board == [EMPTY] * 9

    def test_move_marks_the_cell(self):
        game = Game()
        game.play(4)
        assert game.board[4] == MARK_X

    def test_turn_alternates(self):
        game = Game()
        game.play(0)
        assert game.turn == MARK_O
        game.play(1)
        assert game.turn == MARK_X

    def test_play_returns_none_while_ongoing(self):
        assert Game().play(4) is None

    def test_occupied_cell_rejected(self):
        game = Game()
        game.play(0)
        with pytest.raises(InvalidMoveError, match="已經有 X"):
            game.play(0)

    def test_occupied_cell_message_names_the_position(self):
        game = Game()
        game.play(4)
        with pytest.raises(InvalidMoveError, match="正中央"):
            game.play(4)

    def test_index_out_of_range_rejected(self):
        with pytest.raises(InvalidMoveError):
            Game().play(9)

    def test_negative_index_rejected(self):
        """不用 Python 的負索引繞到棋盤最後一格。"""
        with pytest.raises(InvalidMoveError):
            Game().play(-1)

    def test_cannot_play_after_game_over(self):
        game = Game()
        for cell in (0, 3, 1, 4, 2):
            game.play(cell)
        with pytest.raises(InvalidMoveError, match="已經結束"):
            game.play(5)


# ─── 勝負與平手 ─────────────────────────────────────────────────────────────

class TestResult:
    @pytest.mark.parametrize("cells", [
        (0, 1, 2), (3, 4, 5), (6, 7, 8),  # 橫
        (0, 3, 6), (1, 4, 7), (2, 5, 8),  # 直
        (0, 4, 8), (2, 4, 6),             # 斜
    ])
    def test_x_wins_on_every_line(self, cells):
        """X 在前 5 手內沿任意一條線連成三子（O 都下別格）。"""
        game = Game()
        blockers = [i for i in range(9) if i not in cells]
        result = None
        for step, cell in enumerate(cells):
            result = game.play(cell)
            if step < len(cells) - 1:
                game.play(blockers[step])
        assert result is not None
        assert result.mark == MARK_X
        assert result.line == cells

    def test_o_can_win(self):
        game = Game()
        # X 下 0、1、5 都不成三子，O 沿第三行連成三子
        for cell in (0, 6, 1, 7, 5, 8):
            result = game.play(cell)
        assert result is not None
        assert result.mark == MARK_O
        assert result.line == (6, 7, 8)

    def test_winning_line_reported_by_play(self):
        game = Game()
        for cell in (0, 3, 1, 4):
            game.play(cell)
        result = game.play(2)
        assert result is not None
        assert result.line == (0, 1, 2)

    def test_no_result_while_ongoing(self):
        game = Game()
        game.play(0)
        game.play(1)
        assert game.result() is None
        assert not game.is_over()

    def test_draw_when_board_is_full(self):
        game = Game()
        for cell in (0, 1, 2, 3, 5, 4, 6, 8, 7):
            result = game.play(cell)
        assert result is not None
        assert result.is_draw
        assert result.mark is None
        assert result.line is None
        assert game.is_full()

    def test_result_after_draw_blocks_play(self):
        game = Game()
        for cell in (0, 1, 2, 3, 5, 4, 6, 8, 7):
            game.play(cell)
        assert game.is_over()

    def test_result_is_frozen(self):
        """結果建立之後不會被後面的動作改到（frozen dataclass）。"""
        result = Result(mark=MARK_X, line=(0, 1, 2))
        with pytest.raises(FrozenInstanceError):
            result.mark = MARK_O  # type: ignore[misc]


# ─── Game.undo ───────────────────────────────────────────────────────────────

class TestUndo:
    def test_undo_without_moves_returns_false(self):
        assert Game().undo() is False

    def test_undo_clears_the_cell(self):
        game = Game()
        game.play(4)
        assert game.undo() is True
        assert game.board[4] == EMPTY

    def test_undo_gives_turn_back_to_the_player(self):
        game = Game()
        game.play(4)          # X
        assert game.turn == MARK_O
        game.undo()
        assert game.turn == MARK_X

    def test_undo_undoes_only_one_move(self):
        game = Game()
        game.play(0)
        game.play(4)
        game.undo()
        assert game.board[0] == MARK_X
        assert game.board[4] == EMPTY
        assert game.turn == MARK_O

    def test_can_undo_back_to_empty_board(self):
        game = Game()
        for cell in (0, 3, 1):
            game.play(cell)
        while game.undo():
            pass
        assert game.board == [EMPTY] * 9
        assert game.turn == MARK_X

    def test_undo_after_win_lets_the_loser_try_again(self):
        """輸的一方悔手重下：規則上已結束的狀態會隨著棋盤一起還原。"""
        game = Game()
        for cell in (0, 3, 1, 4, 2):
            result = game.play(cell)
        assert result is not None
        game.undo()
        assert game.result() is None
        assert game.turn == MARK_X
