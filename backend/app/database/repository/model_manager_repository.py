import sqlite3
from typing import Optional, List
from app.database.database import DATABASE_URL
from app.schemas.schemas import ModelConfigurationSchema


class ModelSettingsRepository:
    def __init__(self, db_url: str = str(DATABASE_URL)):
        """
        初始化 Repository。
        :param db_url: 資料庫連接字串，預設使用全域 DATABASE_URL。
        """
        self.db_url = db_url

    def _get_connection(self) -> sqlite3.Connection:
        """建立並返回一個資料庫連接。"""
        conn = sqlite3.connect(self.db_url)
        conn.row_factory = sqlite3.Row  # 使得可以透過欄位名訪問數據
        return conn

    def get_by_name(self, interface_name: str) -> Optional[ModelConfigurationSchema]:
        """
        根據 interface_name 從資料庫獲取模型配置。
        返回 ModelConfigurationSchema 對象或 None。
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT interface_name, api_keys_json, model_name, prompt FROM model_configurations WHERE interface_name = ?",
                (interface_name,)
            )
            row = cursor.fetchone()
            if row:
                return ModelConfigurationSchema(
                    interface_name=row["interface_name"],
                    api_keys_json=row["api_keys_json"],
                    model_name=row["model_name"],
                    prompt=row["prompt"]
                )
            return None
        except sqlite3.Error as e:
            print(f"Repository get_by_name error for '{interface_name}': {e}")
            raise e
        finally:
            if conn:
                conn.close()

    def get_by_model_name(self, model_name: str) -> Optional[ModelConfigurationSchema]:
        """
        根據 interface_name 從資料庫獲取模型配置。
        返回 ModelConfigurationSchema 對象或 None。
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT interface_name, api_keys_json, model_name, prompt FROM model_configurations WHERE model_name = ?",
                (model_name,)
            )
            row = cursor.fetchone()
            if row:
                return ModelConfigurationSchema(
                    interface_name=row["interface_name"],
                    api_keys_json=row["api_keys_json"],
                    model_name=row["model_name"],
                    prompt=row["prompt"]
                )
            return None
        except sqlite3.Error as e:
            print(f"Repository get_by_name error for '{model_name}': {e}")
            raise e
        finally:
            if conn:
                conn.close()

    def save(self, config_schema: ModelConfigurationSchema) -> ModelConfigurationSchema:
        """
        保存或更新模型配置到資料庫。
        接收 ModelConfigurationSchema，因為它更接近資料庫結構。
        成功時返回保存的 ModelConfigurationSchema (不包含DB生成的last_updated,除非重新查詢)。
        失敗時拋出異常。
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO model_configurations 
                (interface_name, api_keys_json, model_name, prompt, last_updated)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    config_schema.interface_name,
                    config_schema.api_keys_json,
                    config_schema.model_name,
                    config_schema.prompt
                )
            )
            conn.commit()
            return config_schema
        except sqlite3.Error as e:
            print(
                f"Repository save error for '{config_schema.interface_name}': {e}")
            raise e
        finally:
            if conn:
                conn.close()

    def get_all_configs(self) -> List[ModelConfigurationSchema]:
        """
        獲取所有模型配置。
        返回 ModelConfigurationSchema 對象的列表。
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT interface_name, api_keys_json, model_name, prompt FROM model_configurations")
            rows = cursor.fetchall()
            return [ModelConfigurationSchema(**dict(row)) for row in rows]
        except sqlite3.Error as e:
            print(f"Repository get_all_configs error: {e}")
            return []
        finally:
            if conn:
                conn.close()
