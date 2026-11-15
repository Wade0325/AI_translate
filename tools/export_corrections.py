"""開發者指令：把校正過的任務匯出成原始轉錄與校正後版本的對照（JSONL，#344；規格 #25 的使用者故事 9）。

給維護者在自己的電腦上執行，留作日後自我優化的材料。在 repo 根目錄執行：

    backend\\.venv\\Scripts\\python.exe -m tools.export_corrections --db <資料庫檔> --out <輸出檔>

- 讀免安裝版的資料庫檔（SQLite，例如解壓資料夾的 ``data\\app.db``），以唯讀的方式開：不寫入、不改結構，
  也不啟動 app（只 import 讀資料庫要用的模組：不讀 app 的設定、不建資料夾、不寫日誌檔）。
- 校正後版本從校正紀錄的 repository 讀（``CorrectionRepository.corrected_version``），和下載、校正頁是同一處
  算出來的，這裡不另外算一份（ADR 0011）；哪些任務算「有校正紀錄或確認狀態」也照它的
  ``touched_by_user``。
- 不上傳任何東西（ADR 0005），檔案只寫到 ``--out``。
- 每個欄位的意思與不含哪些東西寫在 ``--help``（:data:`FIELDS`、:data:`LEFT_OUT`）。
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[1]

FIELDS = (
    ("task_uuid", "任務紀錄的 id。"),
    ("seg_key", "片段鍵，片段在這個任務裡的 id。"),
    ("start", "片段的開始時間，原音檔的秒數。"),
    ("end", "片段的結束時間，原音檔的秒數；模型沒有寫明結束的片段是 null。"),
    ("language", "轉錄時選的語言，例如 ja、zh-TW。"),
    ("provider", "供應商，local（本機）或 google（Gemini）。"),
    ("model", "模型，例如 moss-align、gemini-2.5-flash。"),
    ("transcription_environment",
     "轉錄環境，任務開始轉錄時記下的 JSON 物件（app 版本、主要套件的版本、本機的顯卡與驅動、模型權重的版本、"
     "去靜音與分段轉錄的設定）；這一項做出來之前的任務是 null。"),
    ("original_text", "原始轉錄的文字；沒有文字是空字串。"),
    ("original_speaker", "原始轉錄的說話者編號（S0、S1…）；沒有說話者是 null。"),
    ("corrected_text", "校正後版本的文字；刪掉的片段（不在校正後版本裡）是空字串。"),
    ("corrected_speaker", "校正後版本的說話者編號（S0、S1…）；沒有說話者是 null。"),
    ("corrected", "校正過沒有，校正後版本的文字或說話者和原始轉錄不同時是 true；改了又改回原樣的是 false。"),
    ("deleted", "刪掉了沒有，校正後版本的文字是空的（不在下載的校正後版本裡）時是 true。原始轉錄就沒有文字、"
                "沒有人刪的片段也是 true，用 original_text 是不是空的分辨。"),
    ("review_state", "確認狀態，verified（已確認）、flagged（待查），沒有標是 null。"),
)
"""每一行的欄位與意思，依輸出的順序。"""

LEFT_OUT = (
    "原檔名（和日誌的規則相同，當成個人資料）",
    "說話者名稱（使用者取的名字多半是真實人名），說話者一律寫編號",
    "提示詞，包括送出的提示詞與 Settings 的提示詞範本",
    "API 金鑰",
    "保留音檔與它的路徑",
    "中間的每一筆校正紀錄，只有原始轉錄與最後的校正後版本",
)
"""檔案裡不含的東西。"""

REMINDER = "檔案裡有轉錄的文字，交給別人之前先自己看過。"

SQLITE_SIDE_FILES = ("-wal", "-shm", "-journal")
"""SQLite 放在資料庫檔旁邊的檔案：WAL 與它的索引（app 用 WAL），以及其他日誌模式的 rollback journal。"""


class UsageError(Exception):
    """參數指到不存在或不能用的檔案，或讀不了資料庫；訊息直接給人看。"""


class NothingToExport(Exception):
    """沒有任何有校正紀錄或確認狀態的任務；訊息直接給人看。"""


@dataclass(frozen=True)
class _Task:
    """一個要匯出的任務，只帶匯出要的欄位：原檔名、提示詞、保留音檔的檔名一開始就不讀。"""

    task_uuid: str
    language: str | None
    provider: str | None
    model: str | None
    environment: dict[str, Any] | None


def _import_backend() -> None:
    """``app`` 在 backend/ 底下；從 repo 根目錄執行時它不在 import 路徑上。"""
    backend = str(REPO_ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)


def _parse_environment(recorded: str | None) -> dict[str, Any] | None:
    """任務紀錄裡的轉錄環境（JSON 物件）；沒有記、或讀不懂時是 None。

    和 ``app.services.environment_manifest.from_record`` 讀法相同；不 import 它，因為它會連帶 import
    供應商的轉接器。"""
    if not recorded:
        return None
    try:
        environment = json.loads(recorded)
    except ValueError:
        return None
    return environment if isinstance(environment, dict) else None


def _export_row(task: _Task, segment: Mapping[str, Any]) -> dict[str, Any]:
    """一個片段在輸出裡的一行。欄位一個一個挑，不整份照抄：校正後版本之後多了欄位（例如說話者名稱）也不會
    跟著出去。"""
    return {
        "task_uuid": task.task_uuid,
        "seg_key": segment["seg_key"],
        "start": segment["start"],
        "end": segment["end"],
        "language": task.language,
        "provider": task.provider,
        "model": task.model,
        "transcription_environment": task.environment,
        "original_text": segment["original_text"],
        "original_speaker": segment["original_speaker"],
        "corrected_text": segment["text"],
        "corrected_speaker": segment["speaker"],
        "corrected": segment["corrected"],
        "deleted": segment["deleted"],
        "review_state": segment["review_state"],
    }


def _side_files(db: Path) -> list[Path]:
    return [db.with_name(db.name + suffix) for suffix in SQLITE_SIDE_FILES]


def _read_only_engine(db: Path) -> Engine:
    """以唯讀的方式開 SQLite 資料庫檔（``mode=ro``）：SQLite 不寫資料庫檔，任何寫入都會失敗。

    唯讀地開 WAL 模式的資料庫時，SQLite 會在旁邊建 -wal 與 -shm，關掉之後還留著。所以資料庫旁邊沒有任何
    :data:`SQLITE_SIDE_FILES` 時（app 沒在執行，上次也正常關掉），內容全在資料庫檔裡，另外加 ``immutable=1``：
    SQLite 不鎖檔、不建任何檔案，使用者的資料夾裡不會多出東西。有任何一個在時（app 正在執行，或被直接關掉而
    留下還沒併回的 WAL）只用 ``mode=ro``，讀得到 WAL 裡最新的內容，用的是已經在的檔案。

    不用 app 的引擎工廠：它會設 WAL 這類會寫進檔案的 PRAGMA，也會建資料夾。"""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    immutable = not any(path.exists() for path in _side_files(db))
    uri = db.resolve().as_uri() + "?mode=ro" + ("&immutable=1" if immutable else "")
    return create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True),
                         poolclass=NullPool, hide_parameters=True)


def _tasks(db: Session) -> list[_Task]:
    """有校正紀錄或確認狀態的任務，依送出的先後排序。

    一個任務一個任務問 ``touched_by_user``（每個任務兩次查詢），「使用者動過」的判斷才只有一處；給開發者
    偶爾執行的指令，上千個任務也只要幾秒。"""
    from sqlalchemy import inspect

    from app.database.models import TranscriptionLog
    from app.repositories.correction_repository import CorrectionRepository

    if not inspect(db.get_bind()).has_table("correction_records"):
        return []  # 校正介面之前（v0.1）的 app 建的資料庫：沒有校正紀錄
    rows = (
        db.query(TranscriptionLog.task_uuid, TranscriptionLog.source_language, TranscriptionLog.provider,
                 TranscriptionLog.model_used, TranscriptionLog.transcription_environment)
        .order_by(TranscriptionLog.request_timestamp, TranscriptionLog.task_uuid)
        .all()
    )
    return [
        _Task(task_uuid=str(row.task_uuid), language=row.source_language, provider=row.provider,
              model=row.model_used, environment=_parse_environment(row.transcription_environment))
        for row in rows
        if CorrectionRepository.touched_by_user(db, row.task_uuid)
    ]


def _export_rows(db: Session, tasks: Sequence[_Task]) -> Iterator[dict[str, Any]]:
    from app.repositories.correction_repository import CorrectionRepository

    for task in tasks:
        for segment in CorrectionRepository.corrected_version(db, task.task_uuid):
            yield _export_row(task, segment)


def _overwrites_database(out: Path, db_path: Path) -> bool:
    """寫 ``out`` 會蓋掉資料庫檔，或 SQLite 放在它旁邊的檔案（還不在的也算：app 下次執行時會建出來並照它讀；
    符號連結、硬連結也算）。"""
    return any(out.resolve() == path.resolve() or (out.exists() and path.exists() and os.path.samefile(out, path))
               for path in (db_path, *_side_files(db_path)))


def export(db_path: Path, out: Path) -> tuple[int, int]:
    """把 ``db_path`` 裡有校正紀錄或確認狀態的任務寫成 ``out``（每個片段一行），回傳（任務數, 片段數）。

    Raises:
        UsageError: 資料庫檔不在、讀不了，``out`` 的資料夾不在，或寫 ``out`` 會蓋掉資料庫檔（:func:`_overwrites_database`）。
        NothingToExport: 沒有可以匯出的任務；這時不寫出任何檔案。
    """
    if not db_path.is_file():
        raise UsageError(f"找不到資料庫檔：{db_path}")
    if _overwrites_database(out, db_path):
        raise UsageError(f"--out 不能是資料庫檔本身，或它旁邊的 -wal、-shm、-journal 檔：{out}")
    if not out.parent.is_dir():
        raise UsageError(f"輸出的資料夾不存在：{out.parent}")

    _import_backend()
    from sqlalchemy.exc import DatabaseError
    from sqlalchemy.orm import Session

    engine = _read_only_engine(db_path)
    try:
        with Session(engine) as db:
            rows = list(_export_rows(db, _tasks(db)))
    except DatabaseError as error:
        raise UsageError(f"讀不了資料庫 {db_path}：{getattr(error, 'orig', error)}") from error
    finally:
        engine.dispose()

    if not rows:
        raise NothingToExport(f"沒有校正過的任務：{db_path} 裡沒有任何任務有校正紀錄或確認狀態，沒有寫出 {out}。")
    out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                   encoding="utf-8", newline="\n")
    return len({row["task_uuid"] for row in rows}), len(rows)


def _parser() -> argparse.ArgumentParser:
    fields = "\n".join(f"  {name}：{meaning}" for name, meaning in FIELDS)
    left_out = "\n".join(f"  - {item}" for item in LEFT_OUT)
    ap = argparse.ArgumentParser(
        prog="python -m tools.export_corrections",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "把有校正紀錄或確認狀態的任務匯出成原始轉錄與校正後版本的對照（JSONL）。\n"
            "以唯讀的方式開資料庫，不啟動 app，也不上傳任何東西。app 開著時也能執行。"
        ),
        epilog=(
            "輸出：UTF-8 的 JSONL，每個片段一行，沒改過的片段也列，讓之後用的人自己篩。\n"
            "任務依送出的先後排列，同一個任務裡的片段依時間順序。每一行的欄位：\n"
            f"{fields}\n\n"
            f"不含：\n{left_out}\n\n"
            "沒有可以匯出的任務時不寫出檔案，結束代碼是 1；參數或資料庫有問題時是 2。\n"
            f"{REMINDER}"
        ),
    )
    ap.add_argument("--db", required=True, type=Path, metavar="資料庫檔",
                    help="免安裝版的資料庫檔（SQLite），例如解壓資料夾的 data\\app.db")
    ap.add_argument("--out", required=True, type=Path, metavar="輸出檔",
                    help="要寫出的 JSONL；資料夾要已經存在，檔案已經在時會覆寫")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        tasks, segments = export(args.db, args.out)
    except UsageError as e:
        print(e, file=sys.stderr)
        return 2
    except NothingToExport as e:
        print(e, file=sys.stderr)
        return 1
    print(f"匯出了 {tasks} 個任務、{segments} 個片段：{args.out}")
    print(f"提醒：{REMINDER}")
    return 0


if __name__ == "__main__":
    # Windows 主控台預設 cp950，印不出的字元改用跳脫，不讓指令自己因為編碼而失敗
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")
    sys.exit(main())
