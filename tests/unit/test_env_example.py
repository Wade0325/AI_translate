"""範本 .env.example 要涵蓋 Settings 讀的每個設定（#45）。

使用者照範本寫 .env，範本沒列的設定等於沒有說明，例如保留音檔要留幾天。後端讀的環境
變數都經過 Settings：config.py 在 Settings 之外只讀 APP_MODE 與 AIT_DATA_DIR，兩者也是
Settings 的欄位；provider/local 的 os.environ.setdefault 是替 Hugging Face 套件設預設值，
不是讀設定。所以拿 Settings 的欄位和範本比對，新增設定卻忘了寫進範本時就會紅燈。
"""
import re
from pathlib import Path

from pydantic import AliasChoices

from app.core.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

# 範本裡的一行：必填的 `KEY=值`，或註解掉的選填項目 `# KEY=預設值`
TEMPLATE_LINE = re.compile(r"^#?\s*([A-Z_0-9]+)=")

# 由 docker-compose 注入，不必寫進範本（範本檔頭已說明）
RUNTIME_KEYS = {"DATABASE_URL", "REDIS_HOST"}

# 還沒寫進範本的舊缺口，只減不增：補進範本後從這裡拿掉。新設定直接寫進範本，不要加到這裡。
# 補之前先想好該不該讓使用者改：APP_MODE 與 AIT_* 由免安裝版的 launcher 注入；三個執行期資料夾
# 一改名，.dockerignore 與 build_release.ps1 就排除不到（見 test_runtime_dirs_excluded.py）
KNOWN_GAPS = {
    "APP_MODE", "AIT_DATA_DIR", "AIT_FFMPEG_DIR", "AIT_STATIC_DIR",
    "STANDALONE_WORKER_CONCURRENCY",
    "POSTGRES_SERVER", "POSTGRES_PORT", "REDIS_PORT",
    "CELERY_TIMEZONE", "CELERY_RESULT_EXPIRES",
    "TEMP_UPLOADS_DIR", "VAD_ARTIFACTS_DIR", "AUDIO_STORE_DIR",
}


def _setting_keys() -> set[str]:
    """Settings 每個欄位讀的環境變數名稱。有別名的欄位用別名；別名有好幾個時（免安裝模式
    的路徑），用 launcher 注入的 AIT_* 那個。"""
    keys = set()
    for name, field in Settings.model_fields.items():
        alias = field.validation_alias
        choices = alias.choices if isinstance(alias, AliasChoices) else [alias or name]
        names = [choice.upper() for choice in choices if isinstance(choice, str)]
        keys.add(next((n for n in names if n.startswith("AIT_")), names[0]))
    return keys


def _template_keys() -> set[str]:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    return {m.group(1) for line in lines if (m := TEMPLATE_LINE.match(line))}


def _gaps() -> set[str]:
    """Settings 讀、範本卻沒有一行的鍵。"""
    return _setting_keys() - _template_keys()


def test_every_setting_has_a_line_in_env_example():
    missing = _gaps() - RUNTIME_KEYS - KNOWN_GAPS
    assert not missing, (
        f".env.example 少了這些設定：{', '.join(sorted(missing))}。"
        "選填的設定照範本的寫法補兩行：上一行說明用途，下一行寫 `# KEY=預設值`")


def test_known_gaps_are_still_gaps():
    closed = KNOWN_GAPS - _gaps()
    assert not closed, (
        f"KNOWN_GAPS 裡這些鍵已經不是缺口（範本有了這一行，或 Settings 不再讀）："
        f"{', '.join(sorted(closed))}。把它們從 KNOWN_GAPS 拿掉")
