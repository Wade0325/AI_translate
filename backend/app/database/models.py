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
    """batch_jobs 資料表 — 持久化 Gemini 批次的資訊，供重啟後恢復"""
    __tablename__ = 'batch_jobs'

    batch_id = Column(String, primary_key=True)         # 前端的 batch ID
    session_id = Column(String, nullable=True, index=True)  # 同一次 Start 的任務群組
    gemini_job_name = Column(String, nullable=True)      # Gemini API 的 job name
    status = Column(String, default="UPLOADING", index=True)  # UPLOADING / POLLING / BATCH_SUBMITTED / COMPLETED / FAILED / RETRIEVED / RECOVERING
    task_params_json = Column(Text, nullable=True)       # 序列化的任務參數（不含 api_keys）
    file_mapping_json = Column(Text, nullable=True)      # {index: {file_uid, original_filename}}
    file_durations_json = Column(Text, nullable=True)    # {file_uid: duration}
    file_log_uuids_json = Column(Text, nullable=True)    # {file_uid: task_uuid}
    results_json = Column(Text, nullable=True)           # {file_uid: result_dict} — 完成後存入的結果
    celery_task_id = Column(String, nullable=True, index=True)  # Celery task ID
    file_count = Column(Integer, nullable=True)
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
    # 凍結的原始轉錄副本（ADR-0007），單檔任務完成時由輸出格式模組從轉錄結果產生。有片段的
    # 任務，輸出格式從片段產生、不讀這裡；沒有片段的任務（片段上線前的任務、#110 之前的 Gemini
    # 任務、批次裡的任務）才從這份 LRC 轉換（app.services.output_format）
    lrc_content = Column(Text, nullable=True)
    file_uid = Column(String, nullable=True, index=True)  # 前端檔案 uid
    session_id = Column(String, nullable=True, index=True)  # 同一次 Start 的任務群組
    # 實際推論層級：standard / flex / batch
    service_tier_used = Column(String, nullable=True)
    # 保留音檔的檔名（位於 audio_store 目錄內）。校正介面要能重播它，
    # 只存檔名不存完整路徑，資料目錄搬家後仍然有效
    audio_filename = Column(String, nullable=True)


class TranscriptSegment(Base):
    """轉錄片段 — 校正介面與逐段回傳的持久化單位。

    有片段的任務，四種輸出格式都從這裡產生（app.services.output_format），
    ``TranscriptionLog.lrc_content`` 只是凍結的原始轉錄副本；批次裡的任務目前還沒有片段
    （#115）。說話者分離給出的每一段各一列，可逐段更新、可標記、可回溯；Gemini 的片段是它
    LRC 的一行，只有開始時間。

    ``seg_key`` 是確定性的（切段序號 + 片段序號），所以任務被重派或重新轉錄時是
    覆寫同一列而不是產生重複資料。``text_alt`` 存另一個模型對同一段的轉錄
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
    source = Column(String, nullable=True)        # qwen / vibevoice / aligned / edited
    words_json = Column(Text, nullable=True)      # [{"text","start","end"}]，絕對時間
    confidence = Column(Float, nullable=True)
    review_state = Column(String, nullable=True)  # None / flagged / verified
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
