import uuid
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, func, Float, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class ModelConfiguration(Base):
    """資料模型：表示 model_configurations 資料表的 ORM 模型"""
    __tablename__ = 'model_configurations'

    interface_name = Column(String, primary_key=True)
    api_keys_json = Column(Text)
    model_name = Column(String)
    prompt = Column(Text)
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now())


class TranscriptionLog(Base):
    """資料模型：表示 transcription_logs 資料表的 ORM 模型"""
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


# 資料表 Schema 定義
MODEL_CONFIGURATIONS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS model_configurations (
        interface_name TEXT PRIMARY KEY,
        api_keys_json TEXT,
        model_name TEXT,
        prompt TEXT,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""

# 預設資料
DEFAULT_RECORDS = [
    {
        'interface_name': 'Google',
        'api_keys_json': None,
        'model_name': None,
        'prompt': None
    }
]
