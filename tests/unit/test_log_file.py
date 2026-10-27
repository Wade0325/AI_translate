"""單元測試：免安裝模式的日誌檔（#231 Q5、ADR-0005）

測試範圍：app/utils/logger.py 的 DailyLogFile
  - 開始寫之前什麼都不寫
  - 每天一個檔 app-YYYY-MM-DD.log（UTF-8），保留最近 7 天
  - 使用者家目錄寫成 ~
"""
import logging
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.utils.logger import DailyLogFile

DAY = date(2026, 10, 27)


class Clock:
    def __init__(self, day: date):
        self.day = day

    def __call__(self) -> date:
        return self.day


@pytest.fixture
def clock() -> Clock:
    return Clock(DAY)


@pytest.fixture
def log_file(clock):
    handler = DailyLogFile(today=clock, home="/home/wang.xiaoming")
    logger = logging.getLogger("tests.unit.test_log_file")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    yield handler, logger
    logger.removeHandler(handler)
    handler.stop()


def name(day: date) -> str:
    return f"app-{day.isoformat()}.log"


def lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_writes_nothing_before_it_starts(log_file, tmp_path):
    handler, logger = log_file

    logger.info("還沒開始")

    assert not (tmp_path / "logs").exists()


def test_writes_to_the_file_of_the_day_in_utf8(log_file, tmp_path):
    handler, logger = log_file
    handler.start(tmp_path / "logs")

    logger.warning("轉錄完成")

    [line] = lines(tmp_path / "logs" / name(DAY))
    assert line.endswith("轉錄完成")
    assert " - WARNING - " in line


def test_appends_when_the_app_starts_again_on_the_same_day(log_file, tmp_path):
    handler, logger = log_file
    handler.start(tmp_path / "logs")
    logger.info("第一次啟動")
    handler.stop()

    handler.start(tmp_path / "logs")
    logger.info("第二次啟動")

    assert [line[-5:] for line in lines(tmp_path / "logs" / name(DAY))] == ["第一次啟動", "第二次啟動"]


def test_moves_to_a_new_file_after_midnight(log_file, tmp_path, clock):
    handler, logger = log_file
    handler.start(tmp_path / "logs")
    logger.info("前一天")

    clock.day = DAY + timedelta(days=1)
    logger.info("第二天")

    assert lines(tmp_path / "logs" / name(DAY))[-1].endswith("前一天")
    assert lines(tmp_path / "logs" / name(DAY + timedelta(days=1)))[-1].endswith("第二天")


def test_keeps_the_last_seven_days(log_file, tmp_path):
    handler, _ = log_file
    folder = tmp_path / "logs"
    folder.mkdir()
    for days_ago in range(1, 10):
        (folder / name(DAY - timedelta(days=days_ago))).write_text("舊的", encoding="utf-8")
    # 名稱不是日誌檔的不動
    (folder / "app-notes.log").write_text("", encoding="utf-8")
    (folder / "附給 issue 的.txt").write_text("", encoding="utf-8")

    handler.start(folder)

    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [name(DAY - timedelta(days=days_ago)) for days_ago in range(0, 7)]
        + ["app-notes.log", "附給 issue 的.txt"])


def test_removes_the_expired_file_when_the_day_changes(log_file, tmp_path, clock):
    # app 一直開著過了午夜：換到新的一天時，照樣只留 7 天
    handler, logger = log_file
    folder = tmp_path / "logs"
    handler.start(folder)
    (folder / name(DAY - timedelta(days=6))).write_text("", encoding="utf-8")

    clock.day = DAY + timedelta(days=1)
    logger.info("第二天")

    assert not (folder / name(DAY - timedelta(days=6))).exists()
    assert (folder / name(DAY)).exists()


def test_stops_writing_and_releases_the_file(log_file, tmp_path):
    handler, logger = log_file
    handler.start(tmp_path / "logs")
    logger.info("寫進去")

    handler.stop()
    logger.info("不寫")

    path = tmp_path / "logs" / name(DAY)
    assert lines(path)[-1].endswith("寫進去")
    path.unlink()  # 檔案已經關掉（Windows 上開著的檔案刪不掉）


@pytest.mark.parametrize("home, written, expected", [
    ("/home/wang.xiaoming", "/home/wang.xiaoming/音樂/x.m4a", "~/音樂/x.m4a"),
    (r"C:\Users\王小明", r"C:\Users\王小明\Downloads\AI_Translate\data", r"~\Downloads\AI_Translate\data"),
    # Windows 的路徑不分大小寫，也可能用 / 寫
    (r"C:\Users\王小明", "sqlite:///c:/users/王小明/data/app.db", "sqlite:///~/data/app.db"),
    # OSError 的訊息用 repr 寫檔名，Windows 的 \ 變成兩個
    (r"C:\Users\王小明", repr(r"C:\Users\王小明\Desktop\x.wav"), repr(r"~\Desktop\x.wav")),
], ids=["posix", "windows", "windows-forward-slashes", "windows-repr"])
def test_writes_the_home_folder_as_tilde(tmp_path, home, written, expected):
    handler = DailyLogFile(today=lambda: DAY, home=home)
    logger = logging.getLogger("tests.unit.test_log_file.home")
    logger.propagate = False
    logger.addHandler(handler)
    try:
        handler.start(tmp_path / "logs")
        logger.warning(f"路徑: {written}")
    finally:
        logger.removeHandler(handler)
        handler.stop()

    [line] = lines(tmp_path / "logs" / name(DAY))
    assert line.endswith(f"路徑: {expected}")


def test_writes_the_home_folder_as_tilde_in_tracebacks(log_file, tmp_path):
    handler, logger = log_file
    handler.start(tmp_path / "logs")

    try:
        raise FileNotFoundError(2, "No such file", "/home/wang.xiaoming/AI_Translate/data/x.wav")
    except FileNotFoundError:
        logger.exception("讀不到檔案")

    text = (tmp_path / "logs" / name(DAY)).read_text(encoding="utf-8")
    assert "wang.xiaoming" not in text
    assert "'~/AI_Translate/data/x.wav'" in text


def test_a_home_at_the_root_is_left_as_it_is(tmp_path):
    # 家目錄是根目錄時不換：否則每個路徑都會被換掉
    handler = DailyLogFile(today=lambda: DAY, home="/")
    logger = logging.getLogger("tests.unit.test_log_file.root")
    logger.propagate = False
    logger.addHandler(handler)
    try:
        handler.start(tmp_path / "logs")
        logger.warning("路徑: /opt/app/data")
    finally:
        logger.removeHandler(handler)
        handler.stop()

    [line] = lines(tmp_path / "logs" / name(DAY))
    assert line.endswith("路徑: /opt/app/data")
