# 從開工到合併

開始改動前讀一次，合併前再讀一次。

1. **開工**：從 `origin/master` 開新分支。在 worktree 裡不連使用者的資料庫。
2. **push 前**：本機檢查全綠。不用 `--no-verify` 之類的參數跳過檢查；檢查因為 master 上的問題失敗時，合併 master 或等修正的 PR，不繞過。
3. **改到畫面時**：開 PR 前在瀏覽器實際操作一次。在 worktree 用免安裝模式起一個獨立的 app：`frontend/` 先 `npm run build`，再在 `backend/` 帶環境變數 `APP_MODE=standalone` 與 `AIT_DATA_DIR=<暫存資料夾>` 執行 `python -m uvicorn main:app --port <沒用到的埠>`，用瀏覽器開那個埠；資料只寫進暫存資料夾。不要在 worktree 啟動第二套 Docker stack：容器名稱與埠號是固定的，會和使用者正在跑的那套衝突。
4. **PR 內文**：
   - 寫「使用者看得到的變更」（沒有就寫「無」）；改到使用者看得到的行為時，檢查 `README.md` 要不要跟著改。
   - 改到畫面時，寫出在瀏覽器點了什麼、看到什麼，附截圖；沒有就寫「無畫面變更」。
   - 動到下列路徑的 PR 是單向門，內文要標明：`CLAUDE.md`、`docs/agents/`、`tools/hooks/`、`.github/`、`.gitignore`、進版控的 `.claude/` 檔案；閘門的設定 `tools/check.py`、`ruff.toml`、`pytest.ini`、`frontend/eslint.config.js`、`pyrightconfig.json`、`frontend/tsconfig.json`；依賴 `backend/requirements*.txt`、`frontend/package.json`、`frontend/package-lock.json`；`migrations/`、`build_release.ps1`。
5. **合併**：ruleset 是唯一的關卡，對代理沒有例外。
   1. 等 `gh pr checks <PR> --watch` 全綠（#29 之前沒有任何檢查，跳過這步）。等很久時放到背景執行並設逾時；結束前停掉自己啟動的背景指令。
   2. 狀態是 `BEHIND` 時執行 `gh pr update-branch`，回到 1。
   3. `gh pr merge --merge`，不加 `--admin` 或 `--delete-branch`。#29 與 #30 上線前沒有伺服器端的關卡，合併前先等使用者同意。
   4. 遠端分支沒有自動刪除時，手動刪掉。要移除 worktree 時，先跑 `git -C <worktree> status --ignored --porcelain`，把 `lab/` 之類被忽略的產出複製出來；`git worktree remove` 會不經警告就刪掉它們。

例外：

- **要使用者在本機驗證的 PR**：CI 不安裝 ML 依賴，所以動到 ML 依賴或 `backend/Dockerfile` 的 ML 那一段時，要使用者在本機重建 Docker 確認；issue 寫明合併前要使用者手動驗證的也一樣。等使用者回報通過再合併。
- **資料表結構**：改到 `models.py` 的欄位或 `migrations/` 時，自動遷移補不了的變更，Postgres 要附 `migrations/` 的 SQL，免安裝版（SQLite）要把升級步驟做進程式，讓升級測試（#48）保持綠燈；不要為了讓測試變綠而改寫既有的凍結 schema。PR 內文寫明使用者要執行的步驟；需要使用者執行 SQL 的，等使用者執行並回報後再合併。不要對使用者的資料庫（Docker 的 Postgres、免安裝版的 `data/app.db`）執行遷移或改結構的 SQL。
- **tag**：只推分支，不建立、不推送任何 tag。`v*` tag 一推就會公開發布 Release，由使用者自己推。
