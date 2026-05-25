import uuid

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
    func,
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
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now())


class BatchJob(Base):
    """batch_jobs 資料表 — 持久化 Gemini 批次任務資訊，供重啟後恢復"""
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
    completed_file_count = Column(Integer, default=0, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class TranscriptionLog(Base):
    """ transcription_logs 資料表"""
    __tablename__ = 'transcription_logs'

    task_uuid = Column(UUID(as_uuid=True),
                       primary_key=True, default=uuid.uuid4)
    request_timestamp = Column(DateTime, default=func.now(), index=True)
    status = Column(String, index=True)
    original_filename = Column(String)
    audio_duration_seconds = Column(Float, nullable=True)
    processing_time_seconds = Column(Float, nullable=True)
    model_used = Column(String)
    source_language = Column(String, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    cost = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    user_id = Column(String, nullable=True)
    is_batch = Column(Boolean, default=False, nullable=True)
    # batch_id 參照 batch_jobs.batch_id，但允許 NULL（非批次任務）
    batch_id = Column(
        String,
        ForeignKey("batch_jobs.batch_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider = Column(String, nullable=True)
    target_language = Column(String, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    # 僅儲存 LRC；SRT/VTT/TXT 於下載時由後端即時轉換
    lrc_content = Column(Text, nullable=True)
    file_uid = Column(String, nullable=True, index=True)  # 前端檔案 uid
    session_id = Column(String, nullable=True, index=True)  # 同一次 Start 的任務群組
