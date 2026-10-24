"""任務狀態清單：後端的 TaskStatus 與前端的 TASK_STATUS 必須一致（#105）。

後端映像的 build context 只有 backend/，所以兩邊各自宣告一份，由這個測試對齊。
"""
import re
from pathlib import Path

from app.core.task_status import TaskStatus

FRONTEND_CONSTANTS = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "constants" / "taskStatus.js"
)


def _frontend_task_status(source: str) -> dict[str, str]:
    block = re.search(r"export const TASK_STATUS = Object\.freeze\(\{(.*?)\}\)", source, re.S)
    assert block, "taskStatus.js 找不到 TASK_STATUS 常數"
    return dict(re.findall(r"(\w+):\s*['\"](\w+)['\"]", block.group(1)))


def test_status_strings_are_unchanged():
    # 存在資料庫裡、送到前端的字串，改了就會讓舊紀錄或前端判斷失效
    assert {s.value for s in TaskStatus} == {
        "PROCESSING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "BATCH_SUBMITTED",
        "BATCH_COMPLETED",
    }
    assert all(s.name == s.value for s in TaskStatus)


def test_frontend_constants_match_backend_enum():
    frontend = _frontend_task_status(FRONTEND_CONSTANTS.read_text(encoding="utf-8"))
    assert frontend == {s.name: s.value for s in TaskStatus}

