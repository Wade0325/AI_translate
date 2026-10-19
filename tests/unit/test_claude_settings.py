"""進版控的 .claude/settings.json：只放權限規則，不登記 hook。

為什麼不用 hook 保護檔案，見 .out-of-scope/protected-paths-hook.md。
"""
import json
from pathlib import Path

import pytest

SETTINGS = Path(__file__).resolve().parents[2] / ".claude" / "settings.json"


@pytest.fixture(scope="module")
def settings():
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def test_settings_hold_only_permissions(settings):
    assert set(settings) == {"permissions"}


def test_deny_blocks_only_builtin_code_review(settings):
    # #74 無頭實測：Skill(review) 擋內建的 code-review，Matt 版 mattpocock-skills:code-review 照常載入；
    # Skill(skill:code-review)、Skill(code-review) 會連 Matt 版一起擋
    assert settings["permissions"] == {"deny": ["Skill(review)"]}
