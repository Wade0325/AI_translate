# 程式碼規範

review 時對照這份檔檢查 diff。每條規範後面附理由，判斷邊界情況時以理由為準。能機械檢查的規則改寫成檢查（後端在 `tests/unit/test_conventions.py`，前端在 `frontend/eslint.config.js`），不列在這裡。

## 後端改動在兩種執行模式都要能動

改到任務派送、進度通知、取消或資料庫時，Docker 模式與免安裝模式（`APP_MODE=standalone`）都要能動。Docker 模式用 Redis、Celery、Postgres；免安裝模式用行程內的替代實作與 SQLite。在 `backend/` 搜尋 `is_standalone` 與 `sqlite` 找出兩邊的分歧點，兩邊一起改。

**理由**：使用者拿到的免安裝版以免安裝模式執行，Docker 模式則是開發環境與未來部署的基礎，要在 CI 裡保持可用（ADR-0004）。開發時多半只跑其中一種，另一種壞掉不會有人當場發現。

**已由測試檢查**：`tests/unit/test_conventions.py` 檢查免安裝模式會載入的模組沒有 import Docker 模式專用的套件與模組（清單在該測試裡），以及每個 Celery 任務在兩種執行模式都有派送的方法。兩邊的行為是否一致，仍要 review 時判斷。
