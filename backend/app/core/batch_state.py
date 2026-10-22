"""批次的狀態機：批次紀錄（``batch_jobs.status``）的狀態，以及每個狀態可以從哪些狀態來（#116）。

    上傳中 → 輪詢中        送出了
    上傳中 → 失敗          送出之前就失敗
    輪詢中 → 完成／失敗    批次結束；輪詢中斷也記成失敗
    輪詢中 → 復原中        復原入口接手
    失敗   → 復原中        復原入口接手（送出過的批次）
    復原中 → 完成／失敗    批次結束
    復原中 → 輪詢中        復原接手不了（例如金鑰無效），之後可以再復原
    復原中 → 復原中        接手的復原停了（例如應用程式重啟），再接手一次
    任何狀態 → 已取回      使用者取回結果或歸檔

已取回只管任務頁怎麼顯示：使用者在批次還在跑的時候歸檔，批次照樣往下走（送出、結束、復原），和
歸檔前一樣。

執行與復原是它的兩個入口（:mod:`app.tasks.batch_core`）：執行從上傳中走到輪詢中，復原從輪詢中、
失敗或沒有人看著的復原中接手；兩個入口都輪詢到批次結束，結束送出的檔案只有一份流程。

狀態只經由 :meth:`~app.repositories.batch_job_repository.BatchJobRepository.move` 改變：資料庫裡
現在的狀態是 :data:`SOURCES` 列的來源之一時才改。所以已經完成的批次不會被晚到的執行記成失敗或
退回輪詢中。字串存進資料庫並送到前端（任務頁的 ``frontend/src/components/task/TaskCard.jsx`` 與
``frontend/src/utils/taskSessions.js``），不要改既有的值。
"""

from enum import StrEnum


class BatchState(StrEnum):
    UPLOADING = "UPLOADING"
    """建立了批次紀錄，每個檔案開始、去靜音、上傳。"""
    POLLING = "POLLING"
    """送出給供應商了，等它結束。"""
    RECOVERING = "RECOVERING"
    """復原入口接手，接著輪詢到批次結束。"""
    COMPLETED = "COMPLETED"
    """供應商成功結束，送出的檔案都結束了（各自完成或失敗）。"""
    FAILED = "FAILED"
    """沒有成功結束：送出之前就失敗、輪詢中斷，或供應商回報批次失敗。送出過的還能復原。"""
    RETRIEVED = "RETRIEVED"
    """使用者取回了結果或歸檔了；完成超過 24 小時的批次也自動歸檔。"""


SOURCES: dict[BatchState, frozenset[BatchState]] = {
    BatchState.POLLING: frozenset({BatchState.UPLOADING, BatchState.RECOVERING,
                                   BatchState.RETRIEVED}),
    BatchState.RECOVERING: frozenset({BatchState.POLLING, BatchState.FAILED, BatchState.RECOVERING,
                                      BatchState.RETRIEVED}),
    BatchState.COMPLETED: frozenset({BatchState.POLLING, BatchState.RECOVERING,
                                     BatchState.RETRIEVED}),
    BatchState.FAILED: frozenset({BatchState.UPLOADING, BatchState.POLLING, BatchState.RECOVERING,
                                  BatchState.RETRIEVED}),
    BatchState.RETRIEVED: frozenset(BatchState),
}
"""每個狀態可以從哪些狀態來；已取回在每一個裡面（見模組說明）。上傳中是建立批次紀錄時的狀態，
沒有來源。"""

IN_PROGRESS = frozenset({BatchState.UPLOADING, BatchState.POLLING, BatchState.RECOVERING})
"""還在進行、應該有任務看著的狀態；任務頁會查看著它的任務還在不在。"""
