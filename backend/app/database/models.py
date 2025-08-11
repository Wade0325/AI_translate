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
