import uuid

from sqlalchemy import Column, String, Text, DateTime, func, Float, Integer, UUID
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


class TranscriptionLog(Base):
    """ transcription_logs 資料表"""
    __tablename__ = 'transcription_logs'

    task_uuid = Column(UUID(as_uuid=True),
                       primary_key=True, default=uuid.uuid4)
    request_timestamp = Column(DateTime, default=func.now())
    status = Column(String)
    original_filename = Column(String)
    audio_duration_seconds = Column(Float, nullable=True)
    processing_time_seconds = Column(Float, nullable=True)
    model_used = Column(String)
    source_language = Column(String, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    cost = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    user_id = Column(String, nullable=True)


class BatchJob(Base):
    """batch_jobs 資料表 — 持久化 Gemini 批次任務資訊，供重啟後恢復"""
    __tablename__ = 'batch_jobs'

    batch_id = Column(String, primary_key=True)         # 前端的 batch ID
    gemini_job_name = Column(String, nullable=True)      # Gemini API 的 job name
    status = Column(String, default="UPLOADING")         # UPLOADING / POLLING / COMPLETED / FAILED
    task_params_json = Column(Text, nullable=True)       # 序列化的任務參數（不含 api_keys）
    file_mapping_json = Column(Text, nullable=True)      # {index: {file_uid, original_filename}}
    file_durations_json = Column(Text, nullable=True)    # {file_uid: duration}
    file_log_uuids_json = Column(Text, nullable=True)    # {file_uid: task_uuid}
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
