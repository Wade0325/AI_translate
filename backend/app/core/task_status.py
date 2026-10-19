"""任務狀態清單：任務紀錄的狀態與狀態廣播的狀態碼都從這裡來。

前端的 ``frontend/src/constants/taskStatus.js`` 有同一份清單，``tests/unit/test_task_status.py``
確認兩邊一致；改這裡就要一起改那裡。字串會存進資料庫並送到前端，不要改既有的值。
"""

from enum import StrEnum


class TaskStatus(StrEnum):
    # 任務紀錄與狀態廣播共用
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    # 只用在批次的狀態廣播
    BATCH_SUBMITTED = "BATCH_SUBMITTED"
    BATCH_COMPLETED = "BATCH_COMPLETED"
