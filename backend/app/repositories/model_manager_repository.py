from typing import Optional, List
from sqlalchemy.orm import Session
from app.database.models import ModelConfiguration
from app.schemas.schemas import ModelConfigurationSchema


class ModelSettingsRepository:
    def get_by_name(self, db: Session, provider: str) -> Optional[ModelConfigurationSchema]:
        """
        根據 interface_name 從資料庫獲取模型配置。
        返回 ModelConfigurationSchema 對象或 None。
        """
        config = db.query(ModelConfiguration).filter(
            ModelConfiguration.provider == provider).first()
        if config:
            return ModelConfigurationSchema.model_validate(config)
        return None

    def get_by_model(self, db: Session, model: str) -> Optional[ModelConfigurationSchema]:
        """
        根據 model 從資料庫獲取模型配置。
        返回 ModelConfigurationSchema 對象或 None。
        """
        config = db.query(ModelConfiguration).filter(
            ModelConfiguration.model == model).first()
        if config:
            return ModelConfigurationSchema.model_validate(config)
        return None

    def save(self, db: Session, config_schema: ModelConfigurationSchema) -> ModelConfigurationSchema:
        """
        保存或更新模型配置到資料庫。
        接收 ModelConfigurationSchema，因為它更接近資料庫結構。
        成功時返回保存的 ModelConfigurationSchema。
        失敗時拋出異常。
        """
        db_config = db.query(ModelConfiguration).filter(
            ModelConfiguration.provider == config_schema.provider).first()

        if db_config:
            # 更新現有記錄
            db_config.api_keys = config_schema.api_keys
            db_config.model = config_schema.model
            db_config.prompt = config_schema.prompt
        else:
            # 建立新記錄
            db_config = ModelConfiguration(**config_schema.model_dump())
            db.add(db_config)

        db.commit()
        db.refresh(db_config)
        return ModelConfigurationSchema.model_validate(db_config)

    def get_all_configs(self, db: Session) -> List[ModelConfigurationSchema]:
        """
        獲取所有模型配置。
        返回 ModelConfigurationSchema 對象的列表。
        """
        configs = db.query(ModelConfiguration).all()
        return [ModelConfigurationSchema.model_validate(config) for config in configs]
