"""``python -m tools.export_corrections``（#344）：把校正過的任務匯出成原始轉錄與校正後版本的對照（JSONL）。

照 #25 的測試決策，對暫存的資料庫執行整支指令，驗輸出檔的內容，以及執行前後資料庫檔不變。資料庫用 app 的
引擎工廠建（WAL，和免安裝模式相同），校正與確認狀態用校正紀錄的 repository 寫，和校正頁送出的相同。
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Base, ModelConfiguration, TranscriptionLog, TranscriptSegment
from app.database.session import _create_engine
from app.repositories.correction_repository import (
    Correction,
    CorrectionField,
    CorrectionRepository,
    ReviewState,
)
from tools import export_corrections

ROOT = Path(__file__).resolve().parents[2]
FROZEN_V010 = ROOT / "tests" / "fixtures" / "sqlite_schema" / "0002_v0.1.0-557d38c.sql"

# 都帶英文字母：SQLite 的 UUID 欄是 NUMERIC 親和性，全是數字的 id 會被存成數字
CORRECTED = uuid.UUID("c0ec7ed0-0000-4000-8000-00000000000a")
UNTOUCHED = uuid.UUID("0a7c0bed-0000-4000-8000-00000000000b")
REVIEWED_ONLY = uuid.UUID("5ee2e71e-0000-4000-8000-00000000000c")

# 刻意放進資料庫、匯出裡不能出現的內容（#344「不含」）
ORIGINAL_FILENAME = "林美玲的求職面試.m4a"
SPEAKER_NAME = "林美玲"
SENT_PROMPT = "請轉錄這段面試錄音。術語：極光計畫、北辰科技"
PROMPT_TEMPLATE = "自訂的提示詞範本：輸出 LRC，保留語助詞"
API_KEY = "AIzaSyD-test-only-0123456789abcdefghijk"

ENVIRONMENT = {
    "app_version": "0.2.0",
    "provider": "google",
    "model": "gemini-2.5-flash",
    "packages": {"torch": {"version": None, "source": None}},
    "gpu": None,
    "model_revisions": {},
    "settings": {"remove_silence": True, "single_pass_seconds": 900},
    "model_versions": ["gemini-2.5-flash-001"],
}

SEGMENTS = [
    # (seg_key, 開始, 結束, 說話者, 文字)
    ("0-0", 0.0, 2.5, "S0", "大家好，今天先看進度。"),
    ("0-1", 2.5, 4.0, "S1", "好的，我先報告。"),
    ("0-2", 4.0, 4.6, "S1", "嗯嗯"),
]

EXPECTED_FIELDS = [
    "task_uuid", "seg_key", "start", "end", "language", "provider", "model",
    "transcription_environment", "original_text", "original_speaker", "corrected_text",
    "corrected_speaker", "corrected", "deleted", "review_state",
]


def _add_task(db: Session, task_uuid: uuid.UUID, *, minutes: int, segments=SEGMENTS, **log) -> None:
    db.add(TranscriptionLog(**{
        "task_uuid": task_uuid, "status": "COMPLETED",
        "request_timestamp": datetime(2026, 11, 15, 9) + timedelta(minutes=minutes),
        "original_filename": ORIGINAL_FILENAME, "audio_filename": f"{task_uuid}.m4a", "provider": "google",
        "model_used": "gemini-2.5-flash", "source_language": "zh-TW", "multi_speaker": True,
        "transcription_environment": json.dumps(ENVIRONMENT, ensure_ascii=False), "sent_prompt": SENT_PROMPT,
        "user_supplied_text_attached": False, "lrc_content": f"[ti:{ORIGINAL_FILENAME}]", **log}))
    for seq, (seg_key, start, end, speaker, text) in enumerate(segments):
        db.add(TranscriptSegment(task_uuid=task_uuid, seg_key=seg_key, seq=seq, start_sec=start, end_sec=end,
                                 speaker=speaker, text=text, source="gemini"))
    db.commit()


def corrected_task(db: Session) -> None:
    """改了文字、改了說話者、刪掉一個片段，替 S0 取了說話者名稱，並把第一個片段標成已確認。"""
    _add_task(db, CORRECTED, minutes=0)
    record = CorrectionRepository.record_operation
    record(db, CORRECTED, [Correction("0-0", CorrectionField.TEXT, "大家好，今天先看專案進度。")])
    record(db, CORRECTED, [Correction("0-1", CorrectionField.SPEAKER, "S0")])
    record(db, CORRECTED, [Correction("0-2", CorrectionField.TEXT, "")])
    record(db, CORRECTED, [Correction("S0", CorrectionField.SPEAKER_NAME, SPEAKER_NAME)])
    CorrectionRepository.record_operation(db, CORRECTED, [], review_states={"0-0": ReviewState.VERIFIED})


def untouched_task(db: Session) -> None:
    """完成了、沒有校正紀錄也沒有確認狀態。"""
    _add_task(db, UNTOUCHED, minutes=10)


def reviewed_only_task(db: Session) -> None:
    """沒有校正，只把一個片段標成待查。"""
    _add_task(db, REVIEWED_ONLY, minutes=20, segments=SEGMENTS[:2], source_language="ja", provider="local",
              model_used="moss-align", transcription_environment=None, sent_prompt=None)
    CorrectionRepository.record_operation(db, REVIEWED_ONLY, [], review_states={"0-1": ReviewState.FLAGGED})


def saved_api_key(db: Session) -> None:
    """Settings 存的 Gemini 金鑰與提示詞範本。"""
    db.add(ModelConfiguration(provider="google", api_keys=json.dumps([API_KEY]), model="gemini-2.5-flash",
                              prompt=PROMPT_TEMPLATE))
    db.commit()


def _write_database(path: Path, *builders: Callable[[Session], None]) -> Path:
    """用 app 的引擎工廠（WAL）建資料庫並寫入，寫完關掉所有連線：WAL 併回資料庫檔，和關掉 app 之後一樣。"""
    engine = _create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(bind=engine)
    with sessionmaker(bind=engine)() as db:
        for build in builders:
            build(db)
    engine.dispose()
    return path


@pytest.fixture
def db_file(tmp_path) -> Callable[..., Path]:
    return lambda *builders: _write_database(tmp_path / "data" / "app.db", *builders)


@pytest.fixture
def out(tmp_path) -> Path:
    return tmp_path / "export" / "corrections.jsonl"


@pytest.fixture(autouse=True)
def out_folder(out):
    out.parent.mkdir()


def _export(db: Path, out: Path) -> int:
    return export_corrections.main(["--db", str(db), "--out", str(out)])


def _lines(out: Path) -> list[dict]:
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line(task_uuid, seg_key, start, end, original_text, original_speaker, corrected_text, corrected_speaker, *,
          corrected, deleted, review_state, language="zh-TW", provider="google", model="gemini-2.5-flash",
          environment=ENVIRONMENT) -> dict:
    return {
        "task_uuid": str(task_uuid), "seg_key": seg_key, "start": start, "end": end,
        "language": language, "provider": provider, "model": model, "transcription_environment": environment,
        "original_text": original_text, "original_speaker": original_speaker,
        "corrected_text": corrected_text, "corrected_speaker": corrected_speaker,
        "corrected": corrected, "deleted": deleted, "review_state": review_state,
    }


def test_exports_only_the_corrected_task_one_line_per_segment(db_file, out, capsys):
    db = db_file(corrected_task, untouched_task)

    assert _export(db, out) == 0

    assert _lines(out) == [
        _line(CORRECTED, "0-0", 0.0, 2.5, "大家好，今天先看進度。", "S0", "大家好，今天先看專案進度。", "S0",
              corrected=True, deleted=False, review_state="verified"),
        _line(CORRECTED, "0-1", 2.5, 4.0, "好的，我先報告。", "S1", "好的，我先報告。", "S0",
              corrected=True, deleted=False, review_state=None),
        _line(CORRECTED, "0-2", 4.0, 4.6, "嗯嗯", "S1", "", "S1",
              corrected=True, deleted=True, review_state=None),
    ]
    assert list(_lines(out)[0]) == EXPECTED_FIELDS
    assert "1 個任務、3 個片段" in capsys.readouterr().out


def test_unchanged_segments_of_an_exported_task_are_listed_too(db_file, out):
    def one_change(db: Session) -> None:
        _add_task(db, CORRECTED, minutes=0)
        CorrectionRepository.record_operation(db, CORRECTED, [Correction("0-1", CorrectionField.TEXT, "好，我先報告。")])

    assert _export(db_file(one_change), out) == 0

    lines = _lines(out)
    assert [line["seg_key"] for line in lines] == ["0-0", "0-1", "0-2"]
    assert [line["corrected"] for line in lines] == [False, True, False]
    assert lines[0]["corrected_text"] == lines[0]["original_text"] == "大家好，今天先看進度。"


def test_output_leaves_out_filename_speaker_names_prompts_api_keys_and_retained_audio(db_file, out):
    db = db_file(corrected_task, reviewed_only_task, saved_api_key)

    assert _export(db, out) == 0

    exported = out.read_text(encoding="utf-8")
    for private in (ORIGINAL_FILENAME, SPEAKER_NAME, SENT_PROMPT, "極光計畫", PROMPT_TEMPLATE, API_KEY,
                    f"{CORRECTED}.m4a", f"{REVIEWED_ONLY}.m4a", "audio_store"):
        assert private not in exported, private
    assert all(set(line) == set(EXPECTED_FIELDS) for line in _lines(out))


def test_task_with_only_a_review_state_is_exported(db_file, out):
    db = db_file(untouched_task, reviewed_only_task)

    assert _export(db, out) == 0

    environment = None
    assert _lines(out) == [
        _line(REVIEWED_ONLY, "0-0", 0.0, 2.5, "大家好，今天先看進度。", "S0", "大家好，今天先看進度。", "S0",
              corrected=False, deleted=False, review_state=None, language="ja", provider="local",
              model="moss-align", environment=environment),
        _line(REVIEWED_ONLY, "0-1", 2.5, 4.0, "好的，我先報告。", "S1", "好的，我先報告。", "S1",
              corrected=False, deleted=False, review_state="flagged", language="ja", provider="local",
              model="moss-align", environment=environment),
    ]


def test_deleted_segment_is_listed_and_marked_deleted(db_file, out):
    assert _export(db_file(corrected_task), out) == 0

    deleted = [line for line in _lines(out) if line["seg_key"] == "0-2"]
    assert deleted == [_line(CORRECTED, "0-2", 4.0, 4.6, "嗯嗯", "S1", "", "S1",
                             corrected=True, deleted=True, review_state=None)]


def test_tasks_are_in_the_order_they_were_submitted(db_file, out):
    db = db_file(reviewed_only_task, corrected_task)

    assert _export(db, out) == 0

    tasks = [line["task_uuid"] for line in _lines(out)]
    assert tasks == [str(CORRECTED)] * 3 + [str(REVIEWED_ONLY)] * 2


def test_nothing_to_export_says_so_and_writes_no_file(db_file, out, capsys):
    assert _export(db_file(untouched_task), out) != 0

    assert "沒有校正過的任務" in capsys.readouterr().err
    assert not out.exists()


def test_database_from_before_corrections_existed_has_nothing_to_export(tmp_path, out, capsys):
    """v0.1.0 的資料庫（凍結 schema）還沒有校正紀錄的資料表。"""
    db = tmp_path / "app.db"
    with sqlite3.connect(db) as connection:
        connection.executescript(FROZEN_V010.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO transcription_logs (task_uuid, status, original_filename) VALUES (?, 'COMPLETED', ?)",
            (UNTOUCHED.hex, ORIGINAL_FILENAME))
    connection.close()
    before = _sha256(db)

    assert _export(db, out) != 0

    assert "沒有校正過的任務" in capsys.readouterr().err
    assert not out.exists()
    assert _sha256(db) == before


def test_database_file_is_the_same_before_and_after(db_file, out):
    db = db_file(corrected_task, untouched_task, reviewed_only_task, saved_api_key)
    before = _sha256(db)

    assert _export(db, out) == 0

    assert _sha256(db) == before


def test_reads_what_is_still_in_the_wal_without_merging_it_into_the_database_file(tmp_path, out):
    """app 被直接關掉（例如關掉啟動器的黑色視窗）時，最後的寫入還在 -wal 檔、沒有併回資料庫檔。匯出照樣讀得到，
    而且不替它併回去：資料庫檔不變。"""
    live = tmp_path / "live" / "app.db"
    engine = _create_engine(f"sqlite:///{live.as_posix()}")
    Base.metadata.create_all(bind=engine)
    with sessionmaker(bind=engine)() as db:
        corrected_task(db)
        crashed = tmp_path / "crashed"
        crashed.mkdir()
        for suffix in ("", "-wal", "-shm"):  # app 還開著時的檔案，就是它被直接關掉時留下的樣子
            (crashed / f"app.db{suffix}").write_bytes(live.with_name(f"app.db{suffix}").read_bytes())
    engine.dispose()
    db = crashed / "app.db"
    assert (crashed / "app.db-wal").stat().st_size > 0
    before = _sha256(db)

    assert _export(db, out) == 0

    assert [line["corrected_text"] for line in _lines(out)] == ["大家好，今天先看專案進度。", "好的，我先報告。", ""]
    assert _sha256(db) == before


def test_reminds_to_read_the_file_before_handing_it_over(db_file, out, capsys):
    assert _export(db_file(corrected_task), out) == 0

    assert "檔案裡有轉錄的文字，交給別人之前先自己看過" in capsys.readouterr().out


def test_help_explains_every_field_and_what_is_left_out(capsys):
    with pytest.raises(SystemExit) as exited:
        export_corrections.main(["--help"])

    assert exited.value.code == 0
    shown = capsys.readouterr().out
    for field in EXPECTED_FIELDS:
        assert f"{field}：" in shown, field
    for left_out in ("原檔名", "說話者名稱", "提示詞", "API 金鑰", "保留音檔"):
        assert left_out in shown, left_out


@pytest.mark.parametrize("args", [[], ["--db", "app.db"], ["--out", "corrections.jsonl"]])
def test_database_and_output_paths_are_both_required(args, capsys):
    with pytest.raises(SystemExit) as exited:
        export_corrections.main(args)

    assert exited.value.code == 2
    assert "required" in capsys.readouterr().err


def test_missing_database_file_is_a_usage_error(tmp_path, out, capsys):
    assert _export(tmp_path / "missing.db", out) == 2

    assert "找不到資料庫檔" in capsys.readouterr().err
    assert not out.exists()


def test_file_that_is_not_a_database_is_a_usage_error(tmp_path, out, capsys):
    not_a_db = tmp_path / "notes.txt"
    not_a_db.write_text("這不是資料庫" * 200, encoding="utf-8")

    assert _export(not_a_db, out) == 2

    assert "讀不了資料庫" in capsys.readouterr().err
    assert not out.exists()


def test_output_folder_must_exist(db_file, tmp_path, capsys):
    out = tmp_path / "no-such-folder" / "corrections.jsonl"

    assert _export(db_file(corrected_task), out) == 2

    assert "輸出的資料夾不存在" in capsys.readouterr().err
    assert not out.parent.exists()


def test_refuses_to_write_over_the_database(db_file, capsys):
    db = db_file(corrected_task)
    before = _sha256(db)

    assert _export(db, db) == 2

    assert "不能是資料庫檔本身" in capsys.readouterr().err
    assert _sha256(db) == before


def test_refuses_to_write_where_sqlite_keeps_the_wal(db_file, capsys):
    """關掉 app 之後 -wal 檔不在，但唯讀地開資料庫時 SQLite 可能建出來；寫進去的 JSONL 會被下次開 app 的
    SQLite 當成 WAL 來讀。"""
    db = db_file(corrected_task)
    wal = db.with_name("app.db-wal")
    assert not wal.exists()

    assert _export(db, wal) == 2

    assert "-wal" in capsys.readouterr().err
    assert not wal.exists()


def test_runs_as_a_module_without_starting_the_app(db_file, out, tmp_path):
    """從 repo 根目錄照說明執行：資料夾設定指到的免安裝模式資料夾不會被建立（沒有初始化資料庫、日誌或設定）。"""
    db = db_file(corrected_task)
    app_data = tmp_path / "app-data-should-stay-absent"
    env = {**os.environ, "APP_MODE": "standalone", "AIT_DATA_DIR": str(app_data), "PYTHONIOENCODING": "utf-8"}
    env.pop("PYTHONPATH", None)

    done = subprocess.run([sys.executable, "-m", "tools.export_corrections", "--db", str(db), "--out", str(out)],
                          cwd=ROOT, env=env, capture_output=True, encoding="utf-8", check=False)

    assert done.returncode == 0, done.stderr
    assert len(_lines(out)) == 3
    assert "交給別人之前先自己看過" in done.stdout
    assert not app_data.exists()
