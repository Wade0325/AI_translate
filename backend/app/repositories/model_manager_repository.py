from typing import Optional, List
from sqlalchemy.orm import Session
from app.database.session import SessionLocal
from app.database.models import ModelConfiguration
from app.schemas.schemas import ModelConfigurationSchema


class ModelSettingsRepository:
    def _get_db_session(self) -> Session:
        """建立並返回一個資料庫 session。"""
        return SessionLocal()

    def get_by_name(self, interface_name: str) -> Optional[ModelConfigurationSchema]:
        """
        根據 interface_name 從資料庫獲取模型配置。
        返回 ModelConfigurationSchema 對象或 None。
        """
        db = self._get_db_session()
        try:
            config = db.query(ModelConfiguration).filter(
                ModelConfiguration.interface_name == interface_name).first()
            if config:
                return ModelConfigurationSchema.from_orm(config)
            return None
        finally:
            db.close()

    def get_by_model_name(self, model_name: str) -> Optional[ModelConfigurationSchema]:
        """
        根據 model_name 從資料庫獲取模型配置。
        返回 ModelConfigurationSchema 對象或 None。
        """
        db = self._get_db_session()
        try:
            config = db.query(ModelConfiguration).filter(
                ModelConfiguration.model_name == model_name).first()
            if config:
                return ModelConfigurationSchema.from_orm(config)
            return None
        finally:
            db.close()

    def save(self, config_schema: ModelConfigurationSchema) -> ModelConfigurationSchema:
        """
        保存或更新模型配置到資料庫。
        接收 ModelConfigurationSchema，因為它更接近資料庫結構。
        成功時返回保存的 ModelConfigurationSchema。
        失敗時拋出異常。
        """
        db = self._get_db_session()
        try:
            db_config = db.query(ModelConfiguration).filter(
                ModelConfiguration.interface_name == config_schema.interface_name).first()

            if db_config:
                # 更新現有記錄
                db_config.api_keys_json = config_schema.api_keys_json
                db_config.model_name = config_schema.model_name
                db_config.prompt = config_schema.prompt
            else:
                # 建立新記錄
                db_config = ModelConfiguration(**config_schema.dict())
                db.add(db_config)

            db.commit()
            db.refresh(db_config)
            return ModelConfigurationSchema.from_orm(db_config)
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()

    def get_all_configs(self) -> List[ModelConfigurationSchema]:
        """
        獲取所有模型配置。
        返回 ModelConfigurationSchema 對象的列表。
        """
        db = self._get_db_session()
        try:
            configs = db.query(ModelConfiguration).all()
            return [ModelConfigurationSchema.from_orm(config) for config in configs]
        finally:
            db.close()
