# 程式碼規範

review 時對照這份檔檢查 diff。每條規範後面附理由，判斷邊界情況時以理由為準。

## 後端改動在兩種執行模式都要能動

改到任務派送、進度通知、取消或資料庫時，Docker 模式與免安裝模式（`APP_MODE=standalone`）都要能動。Docker 模式用 Redis、Celery、Postgres；免安裝模式用行程內的替代實作與 SQLite。在 `backend/` 搜尋 `is_standalone` 與 `sqlite` 找出兩邊的分歧點，兩邊一起改。

**理由**：使用者拿到的免安裝版以免安裝模式執行，Docker 模式則是開發環境與未來部署的基礎，要在 CI 裡保持可用（ADR-0004）。開發時多半只跑其中一種，另一種壞掉不會有人當場發現。

## 接收伺服器檔名的端點經 `resolve_upload_path()`

新增接收伺服器檔名的端點時，用 `backend/app/utils/paths.py` 的 `resolve_upload_path()` 把檔名轉成路徑。

**理由**：伺服器檔名由前端送來，直接和目錄拼接時，`..` 或絕對路徑會讓請求讀到、刪到暫存上傳資料夾以外的檔案，包括使用者的音檔。這個函式集中擋下這些檔名，並保留 Docker 模式的 GPU worker 共享上傳檔所需的相對路徑。
