from typing import Optional
from sqlalchemy.orm import Session
from app.database.models import ModelConfiguration
from app.schemas.schemas import ModelConfigurationSchema


class ModelSettingsRepository:
    def get_by_name(self, db: Session, provider: str) -> Optional[ModelConfigurationSchema]:
        """根據 provider 取得模型設定，無資料時回傳 None。"""
        config = db.query(ModelConfiguration).filter(
            ModelConfiguration.provider == provider).first()
        if config:
            return ModelConfigurationSchema.model_validate(config)
        return None

    def save(self, db: Session, config_schema: ModelConfigurationSchema) -> ModelConfigurationSchema:
        """保存或更新（upsert）模型設定。"""
        db_config = db.query(ModelConfiguration).filter(
            ModelConfiguration.provider == config_schema.provider).first()

        if db_config:
            db_config.api_keys = config_schema.api_keys
            db_config.model = config_schema.model
            db_config.prompt = config_schema.prompt
        else:
            db_config = ModelConfiguration(**config_schema.model_dump())
            db.add(db_config)

        db.commit()
        db.refresh(db_config)
        return ModelConfigurationSchema.model_validate(db_config)
