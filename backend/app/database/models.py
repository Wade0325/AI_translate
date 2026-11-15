"""SQLAlchemy ORM 模型。

改欄位前先看：session.py 的自動遷移只會補上缺少的欄位（ADD COLUMN，不帶 NOT NULL）
與索引。改型別、改約束或刪欄都不會自動套用：Postgres 要在 migrations/ 手寫 SQL；
免安裝版的 SQLite（data/app.db 會跨版本保留）沒有對應的遷移，要另外確認舊資料庫的升級路徑。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UUID,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ModelConfiguration(Base):
    """ AI模型資訊 """
    __tablename__ = 'model_configurations'

    provider = Column(String, primary_key=True)
    api_keys = Column(Text)
    model = Column(String)
    prompt = Column(Text)
    # 以 Python 端本地時間為準（而非 DB func.now()）：Postgres 容器與 SQLite 的
    # CURRENT_TIMESTAMP 時區行為不同，統一在應用層產生，查詢端才能一致用 datetime.now() 比較
    last_updated = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class BatchJob(Base):
    """batch_jobs 資料表 — 持久化 Gemini 批次的資訊，供重啟後恢復；每個檔案在 batch_files 各一列"""
    __tablename__ = 'batch_jobs'

    batch_id = Column(String, primary_key=True)         # 前端的 batch ID
    session_id = Column(String, nullable=True, index=True)  # 同一次 Start 的任務群組
    gemini_job_name = Column(String, nullable=True)      # 供應商的批次名稱，送出之後才有
    status = Column(String, default="UPLOADING", index=True)  # 批次的狀態機（app.core.batch_state）
    task_params_json = Column(Text, nullable=True)       # 序列化的任務參數（不含 api_keys）
    # 舊的檔案清單（#116 之前）：新批次不再寫。啟動時與復原入口從這裡替舊版送出的批次補上
    # batch_files 的列（app.tasks.older_batches），只讀不寫；保留一個版本，之後另開票刪掉
    file_mapping_json = Column(Text, nullable=True)      # {index: {file_uid, original_filename}}
    file_durations_json = Column(Text, nullable=True)    # {file_uid: duration}
    file_log_uuids_json = Column(Text, nullable=True)    # {file_uid: task_uuid}
    results_json = Column(Text, nullable=True)           # {file_uid: result_dict} — 完成後存入的結果
    celery_task_id = Column(String, nullable=True, index=True)  # 看著這個批次的任務：執行，或接手的復原
    file_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    # 還在進行的批次，看著它的任務每次查詢都會更新（心跳，app.tasks.batch_core.watched）
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class BatchFile(Base):
    """batch_files 資料表：批次裡的每個檔案一列（#116），從建立批次起就在；#116 之前送出的批次在
    應用程式啟動時或復原入口補上（app.tasks.older_batches）。

    每個檔案仍各是一個任務，以它的任務紀錄 id 為主鍵。不設外鍵到 transcription_logs：列在任務
    開始之前就建立；使用者刪掉任務紀錄之後，批次照樣列得出這個檔案。復原時從這裡讀回開始時量到的
    長度、上傳檔、語音視圖的序列化形式與去靜音找到的靜音（app.tasks.batch_core）。
    """
    __tablename__ = 'batch_files'
    __table_args__ = (
        UniqueConstraint('batch_id', 'seq', name='uq_batch_files_seq'),
    )

    task_uuid = Column(UUID(as_uuid=True), primary_key=True)  # 這個檔案的任務紀錄 id
    batch_id = Column(String, ForeignKey("batch_jobs.batch_id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)          # 在批次裡的順序（0 起算）
    file_uid = Column(String, nullable=False)      # 前端檔案 uid
    original_filename = Column(String, nullable=False)
    file_path = Column(String, nullable=True)      # 上傳檔，任務結束時保留或清理
    audio_duration_seconds = Column(Float, nullable=True)  # 開始時量到的長度
    speech_view_json = Column(Text, nullable=True)  # 語音視圖的序列化形式；送出之前是 NULL
    # 去靜音在原音檔裡找到的靜音（剪不剪都有），檢查掉尾時扣掉（#257）；送出之前、改版前送出的是 NULL
    silences_json = Column(Text, nullable=True)
    request_index = Column(Integer, nullable=True)  # 送出的批次裡第幾個請求；沒送出的是 NULL
    status = Column(String, nullable=False)        # 結果狀態：PROCESSING / COMPLETED / FAILED
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class TranscriptionLog(Base):
    """ transcription_logs 資料表"""
    __tablename__ = 'transcription_logs'

    task_uuid = Column(UUID(as_uuid=True),
                       primary_key=True, default=uuid.uuid4)
    request_timestamp = Column(DateTime, default=datetime.now, index=True)
    status = Column(String, index=True)
    original_filename = Column(String)
    audio_duration_seconds = Column(Float, nullable=True)
    processing_time_seconds = Column(Float, nullable=True)
    model_used = Column(String)
    source_language = Column(String, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    cost = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    # 失敗的錯誤碼（app.core.error_codes.ErrorCode），error_message 是它的細節；畫面照錯誤碼顯示原因
    # 與下一步。#24 門檻 4 之前的失敗與其他狀態是 NULL
    error_code = Column(String, nullable=True)
    is_batch = Column(Boolean, default=False, nullable=True)
    # batch_id 參照 batch_jobs.batch_id，但允許 NULL（不屬於批次的任務）
    batch_id = Column(
        String,
        ForeignKey("batch_jobs.batch_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider = Column(String, nullable=True)
    target_language = Column(String, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    # 凍結的原始轉錄副本（ADR-0007），任務完成時由輸出格式模組從轉錄結果產生，不論說話者人數
    # 都帶說話者標記。有片段的任務，輸出格式從片段產生、不讀這裡；沒有片段的任務（片段上線前的
    # 任務、#110 之前的 Gemini 任務、#115 之前批次裡的任務）才從這份 LRC 轉換
    # （app.services.output_format）
    lrc_content = Column(Text, nullable=True)
    file_uid = Column(String, nullable=True, index=True)  # 前端檔案 uid
    session_id = Column(String, nullable=True, index=True)  # 同一次 Start 的任務群組
    # 實際推論層級：standard / flex / batch
    service_tier_used = Column(String, nullable=True)
    # 保留音檔的檔名（位於 audio_store 目錄內）。校正介面要能重播它，
    # 只存檔名不存完整路徑，資料目錄搬家後仍然有效
    audio_filename = Column(String, nullable=True)
    # 舊的 Multi-Speaker 開關（#13 Q1），說話者人數（speaker_count）取代它之後新任務不再寫。只有
    # speaker_count 是 NULL 的舊任務讀它：關著（False）的輸出不帶說話者標記，開著與開關做出來之前（#259）
    # 的 NULL 一律帶，下載結果不變（app.services.output_format.speaker_labels_for）
    multi_speaker = Column(Boolean, nullable=True)
    # 說話者人數（#351、#352）：照模型判斷是 "auto"，1 到 8 人是 "1"～"8"（app.core.speaker_count）。
    # 決定 Gemini 的提示詞與輸出帶不帶說話者標記；片段與凍結的原始轉錄副本照樣有說話者編號。
    # 人數做出來之前的任務是 NULL，照 multi_speaker 的舊規則
    speaker_count = Column(String(8), nullable=True)
    # 可能掉尾的起點（原音檔的秒數，#257）：完成的任務從這裡起可能有內容沒有轉錄到，畫面照它提醒使用者
    # （app.services.tail_loss）。沒有掉尾、沒有完成，以及這一欄加上之前的任務是 NULL
    tail_loss_from_seconds = Column(Float, nullable=True)


class TranscriptSegment(Base):
    """轉錄片段 — 校正介面與逐段回傳的持久化單位。

    有片段的任務，四種輸出格式都從這裡產生（app.services.output_format），
    ``TranscriptionLog.lrc_content`` 只是凍結的原始轉錄副本；批次裡的任務和單檔任務一樣存片段
    （#115 之前的沒有）。說話者分離給出的每一段各一列，可逐段更新、可標記、可回溯；Gemini 的
    片段是它 LRC 的一行，Gemini 寫明結束的才有結束時間。

    片段存的是原始轉錄，校正不改它：校正另存成校正紀錄（``CorrectionRecord``，ADR 0011），以
    ``seg_key``（確定性的切段序號 + 片段序號）為對象；``source`` 只記原始轉錄的來源。同一個任務
    再完成一次時換不換片段，見 ``app.tasks.lifecycle``。``text_alt`` 存另一個模型對同一段的轉錄
    （local provider 的 VibeVoice 文字），兩者不一致處即是需要人工複查的候選。
    """

    __tablename__ = 'transcript_segments'
    __table_args__ = (
        UniqueConstraint('task_uuid', 'seg_key', name='uq_transcript_segments_key'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_uuid = Column(
        UUID(as_uuid=True),
        ForeignKey("transcription_logs.task_uuid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seg_key = Column(String, nullable=False)      # 確定性片段 id
    seq = Column(Integer, nullable=False)         # 時間順序（0 起算）
    start_sec = Column(Float, nullable=False)     # 去靜音前的時間軸
    end_sec = Column(Float, nullable=True)
    speaker = Column(String, nullable=True)       # "S0" / "S1"
    text = Column(Text, nullable=True)            # 主要轉錄結果
    text_alt = Column(Text, nullable=True)        # 另一模型的轉錄（分歧偵測用）
    source = Column(String, nullable=True)        # 原始轉錄的來源：qwen / vibevoice / aligned
    words_json = Column(Text, nullable=True)      # [{"text","start","end"}]，絕對時間
    confidence = Column(Float, nullable=True)
    review_state = Column(String, nullable=True)  # None / flagged / verified
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class CorrectionRecord(Base):
    """校正紀錄（ADR 0011）：一次校正留下的一筆，寫入後不改、不刪，只有刪掉整個任務時一起刪。

    片段（``TranscriptSegment``）存的是原始轉錄；校正後版本不另外存，由原始轉錄套上每個對象、
    每種內容最新的一筆校正紀錄算出來（``app.repositories.correction_repository``）。先後看
    ``id``，不看時間。

    ``target`` 是片段的 ``seg_key``；說話者名稱的紀錄是說話者編號（例如 ``S0``）。
    ``field`` 是改了什麼：``text``、``speaker`` 或 ``speaker_name``
    （``app.repositories.correction_repository.CorrectionField``）。刪掉片段是文字改成空字串。
    使用者的一個動作寫下的紀錄共用一個 ``operation_id``，復原一次操作就照它找。
    """

    __tablename__ = 'correction_records'

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 刪掉任務紀錄時明確刪除（app.api.history 的 delete_history）：SQLite 預設不強制外鍵
    task_uuid = Column(
        UUID(as_uuid=True),
        ForeignKey("transcription_logs.task_uuid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target = Column(String, nullable=False)       # seg_key，或說話者編號
    field = Column(String, nullable=False)        # text / speaker / speaker_name
    old_value = Column(Text, nullable=True)       # 改前
    new_value = Column(Text, nullable=True)       # 改後
    operation_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


@event.listens_for(CorrectionRecord, "before_update")
@event.listens_for(CorrectionRecord, "before_delete")
def _correction_records_are_append_only(_mapper, _connection, _target):
    """校正紀錄寫入後不改、不刪（ADR 0011）：經過 ORM 改或刪一筆時直接失敗。刪掉整個任務時用
    ``CorrectionRepository.delete_for_task``，它一次刪掉整個任務的紀錄，不經過這裡。"""
    raise RuntimeError("校正紀錄寫入後不改、不刪（ADR 0011）")
