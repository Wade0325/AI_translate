"""舊版送出的批次（#117）：把舊版送出批次之後存下的樣子寫進測試資料庫，再像升級之後那樣啟動這一版。

#116 之前，批次的檔案清單、長度、任務紀錄 id 與去靜音保留下來的有聲段存在批次紀錄的四個 JSON 欄位
裡，沒有 batch_files 的列。這裡照當時的程式寫：上一個發布版本（#115 之前）與 #115 到 #116 之間的版本，
兩種格式各一個。每個檔案的任務紀錄在開始時建立，和當時一樣；檔案的 file_uid 是畫面產生的代號，檔名是
代號加上 ``.wav``。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Optional

from tests.support.fake_provider import FAKE_MODEL

SPANS = [{"start": 0.0, "end": 2.3}, {"start": 4.7, "end": 7.3}, {"start": 9.7, "end": 12.0}]
"""預設的合成音檔去靜音保留下來的有聲段（原音檔的時間軸，見 synthetic_audio 的 VOICED），舊版存的
就是這個形狀：送進模型的是這三段接成的 7.2 秒。"""

DURATION = 12.0
"""舊版開始時量到的長度：預設的合成音檔有 12 秒。"""


@dataclass(frozen=True)
class OlderFile:
    """舊版批次裡的一個檔案。"""

    file_uid: str
    spans: Optional[list] = None
    """去靜音保留下來的有聲段；None 是沒有去靜音。"""
    sent: bool = True
    """False 是上傳失敗、沒有送出，在舊版就記成失敗了。"""


def sent_by_previous_release(db, batch_id: str, name: str, files: list[OlderFile]) -> dict[str, str]:
    """寫進上一個發布版本（#115 之前）送出批次之後存下的樣子：批次在輪詢中。

    ``files`` 依在批次裡的順序。檔案清單以檔案在批次裡的位置為 key、只列送出的，沒有記下上傳檔；長度
    與任務紀錄 id 列出每個檔案。``name`` 是供應商那邊的批次名稱。回傳每個檔案的任務紀錄 id（以
    file_uid 為 key）。
    """
    sent = {str(position): {"file_uid": file.file_uid, "original_filename": f"{file.file_uid}.wav",
                            "vad_segments": file.spans}
            for position, file in enumerate(files) if file.sent}
    return _write(db, batch_id, name, sent, recorded=[file.file_uid for file in files],
                  not_sent={file.file_uid for file in files if not file.sent})


def sent_between_115_and_116(db, batch_id: str, name: str,
                             files: list[tuple[str, str]]) -> dict[str, str]:
    """寫進 #115 到 #116 之間的版本送出批次之後存下的樣子：檔案清單以第幾個請求為 key，另外記下了
    上傳檔，語音視圖存它的序列化形式；長度與任務紀錄 id 只列送出的檔案。

    ``files`` 是 (file_uid, 上傳檔)，依送出的順序，每個都去靜音過（SPANS）。回傳每個檔案的任務紀錄 id。
    """
    sent = {str(index): {"file_uid": file_uid, "original_filename": f"{file_uid}.wav",
                         "file_path": path, "vad_segments": SPANS}
            for index, (file_uid, path) in enumerate(files)}
    return _write(db, batch_id, name, sent, recorded=[file_uid for file_uid, _ in files],
                  not_sent=set())


def finished_by_previous_release(db, batch_id: str, task_uuids: dict[str, str],
                                 lrcs: dict[str, Optional[str]]) -> None:
    """上一個發布版本把批次結束了、還沒取回。``lrcs`` 是每個送出的檔案的結果（以 file_uid 為 key）：
    完成的任務紀錄只存 LRC（時間已經還原回原音檔，沒有片段），None 是供應商回報轉錄失敗。批次紀錄記成
    完成，並存下每個完成的檔案的結果。"""
    from app.database.models import BatchJob, TranscriptionLog

    results = {}
    for file_uid, lrc in lrcs.items():
        record = db.get(TranscriptionLog, uuid.UUID(task_uuids[file_uid]))
        if lrc is None:
            record.status = "FAILED"
            record.error_message = "[[音檔無法解碼]]"
            continue
        record.status = "COMPLETED"
        record.lrc_content = lrc
        record.audio_duration_seconds = DURATION
        record.total_tokens = 240_000
        record.cost = 0.15
        record.service_tier_used = "batch"
        results[file_uid] = {"task_uuid": task_uuids[file_uid], "transcripts": {"lrc": lrc}}
    job = db.get(BatchJob, batch_id)
    job.status = "COMPLETED"
    job.results_json = json.dumps(results, ensure_ascii=False)
    db.commit()


def unreadable_older_batch(db, batch_id: str, status: str = "POLLING",
                           file_list: Optional[str] = None) -> None:
    """一個這一版讀不懂的舊版批次：送出了，檔案清單卻沒有記下任務紀錄 id；``file_list`` 給了時，檔案
    清單改存這段文字（例如不是 JSON）。"""
    from app.database.models import BatchJob

    db.add(BatchJob(
        batch_id=batch_id, status=status, gemini_job_name=f"batches/{batch_id}", file_count=1,
        file_mapping_json=file_list or json.dumps(
            {"0": {"file_uid": "unreadable", "original_filename": "unreadable.wav"}}),
        results_json=json.dumps({}) if status == "COMPLETED" else None))
    db.commit()


def start_this_version(engine) -> None:
    """升級之後啟動這一版：app 啟動時（main.py 的 lifespan）替舊版送出的批次補上每個檔案的列。"""
    from sqlalchemy.orm import sessionmaker

    from app.tasks import older_batches

    with sessionmaker(bind=engine)() as db:
        older_batches.add_file_rows(db)


def _write(db, batch_id: str, name: str, sent: dict, *, recorded: list[str],
           not_sent: set[str]) -> dict[str, str]:
    """寫進輪詢中的批次紀錄，只有舊的 JSON 欄位；``recorded`` 是長度與任務紀錄 id 記下的檔案，每個都有
    開始時建立的任務紀錄，``not_sent`` 的記成失敗。"""
    from app.database.models import BatchJob, TranscriptionLog

    task_uuids = {file_uid: str(uuid.uuid4()) for file_uid in recorded}
    db.add(BatchJob(
        batch_id=batch_id, session_id=batch_id, status="POLLING", gemini_job_name=name,
        task_params_json=json.dumps({"model": FAKE_MODEL, "provider": "fake",
                                     "source_lang": "ja", "target_lang": None, "prompt": ""}),
        file_mapping_json=json.dumps(sent),
        file_durations_json=json.dumps({file_uid: DURATION for file_uid in recorded}),
        file_log_uuids_json=json.dumps(task_uuids),
        celery_task_id="older-run", file_count=len(recorded)))
    db.flush()
    for file_uid in recorded:
        failed = file_uid in not_sent
        db.add(TranscriptionLog(
            task_uuid=uuid.UUID(task_uuids[file_uid]), file_uid=file_uid,
            original_filename=f"{file_uid}.wav", status="FAILED" if failed else "PROCESSING",
            error_message="檔案上傳失敗: 讀不到檔案" if failed else None,
            model_used=FAKE_MODEL, provider="fake", source_language="ja", is_batch=True,
            batch_id=batch_id, session_id=batch_id))
    db.commit()
    return task_uuids
