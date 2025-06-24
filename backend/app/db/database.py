import sqlite3
from pathlib import Path

DATABASE_URL = Path(__file__).resolve(
).parent.parent.parent / "model_settings.db"


def init_db():
    """初始化資料庫，如果 'model_configurations' 資料表不存在則建立它。
       同時檢查並添加 prompt 欄位（如果不存在）。"""
    conn = None
    try:
        DATABASE_URL.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_configurations (
                interface_name TEXT PRIMARY KEY,
                api_keys_json TEXT,
                model_name TEXT,
                prompt TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 檢查表格是否為空，如果為空則插入一筆預設紀錄
        cursor.execute("SELECT COUNT(*) FROM model_configurations")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO model_configurations (interface_name) VALUES (?)",
                ('Google',)
            )
            print("Inserted default 'Google' record into 'model_configurations' table.")

        cursor.execute("PRAGMA table_info(model_configurations)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'prompt' not in columns:
            cursor.execute(
                "ALTER TABLE model_configurations ADD COLUMN prompt TEXT")
            print("Added 'prompt' column to 'model_configurations' table.")

        cursor.execute("PRAGMA table_info(model_configurations)")
        columns_info = {row[1]: row for row in cursor.fetchall()}
        if 'last_updated' in columns_info:
            last_updated_column_info = columns_info['last_updated']
            is_default_current_timestamp = \
                isinstance(last_updated_column_info[4], str) and "CURRENT_TIMESTAMP" in last_updated_column_info[4].upper() and \
                last_updated_column_info[2].upper() == "TIMESTAMP"

            if not is_default_current_timestamp:
                print(
                    f"Warning: 'last_updated' column in 'model_configurations' might not have 'DEFAULT CURRENT_TIMESTAMP' or correct type. Current default: {last_updated_column_info[4]}, type: {last_updated_column_info[2]}")
                pass

        conn.commit()
        print(f"Database initialized successfully at {DATABASE_URL}")
    except sqlite3.Error as e:
        print(f"Database initialization error: {e}")
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    print(f"Attempting to initialize database at: {DATABASE_URL}")
    init_db()
