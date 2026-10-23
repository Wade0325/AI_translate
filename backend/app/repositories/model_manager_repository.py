from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database.models import ModelConfiguration
from app.schemas.schemas import ModelConfigurationSchema


def find_provider_settings(db: Session, provider: str) -> Optional[ModelConfiguration]:
    """這個供應商的設定列；名稱不分大小寫，完全相同的優先。

    設定存在「Google」「Local」底下（舊版前端與空資料庫的預設資料都這樣存），畫面與任務
    用的是模型能力端點的「google」「local」，要找到同一筆。
    """
    row = db.query(ModelConfiguration).filter(
        ModelConfiguration.provider == provider).first()
    if row is None:
        row = db.query(ModelConfiguration).filter(
            func.lower(ModelConfiguration.provider) == provider.lower()).first()
    return row


def stored_prompt_template(db: Session, provider: str) -> Optional[str]:
    """設定頁為這個供應商存的提示詞範本（名稱不分大小寫）；沒有設定列時是 None。

    存的是空字串（清空範本再存）也照樣回傳：由 :func:`app.core.default_prompt.build_prompt`
    當成沒存過，改用系統內建的範本。
    """
    row = find_provider_settings(db, provider)
    return row.prompt if row else None


class ModelSettingsRepository:
    def get_by_name(self, db: Session, provider: str) -> Optional[ModelConfigurationSchema]:
        """根據 provider 取得模型設定（名稱不分大小寫），無資料時回傳 None。"""
        config = find_provider_settings(db, provider)
        if config:
            return ModelConfigurationSchema.model_validate(config)
        return None

    def save(self, db: Session, config_schema: ModelConfigurationSchema) -> ModelConfigurationSchema:
        """保存或更新（upsert）模型設定；已有的設定（名稱不分大小寫）原地更新，名稱照舊。"""
        db_config = find_provider_settings(db, config_schema.provider)

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
