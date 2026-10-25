# 從開工到合併

開始改動前讀一次，合併前再讀一次。push、開 PR 與合併都由代理自己做，不必先問。

1. **開工**：從 `origin/main` 開新分支。在 worktree 裡不連使用者的資料庫。
2. **commit 與 push 前**：git 的 pre-commit（`.githooks/pre-commit`）在每次 commit 前跑快的檢查（lint、型別檢查與棘輪）；clone 之後執行一次 `git config core.hooksPath .githooks` 啟用，worktree 共用這個設定。push 前在本機跑完整的 `tools/check.py`，全綠才 push。不准跳過 hook 或檢查：不用 `git commit --no-verify`（`-n`）、不改 `core.hooksPath`、不用 `-c core.hooksPath=…` 之類的方式；檢查因為 main 上的問題失敗時，合併 main 或等修正的 PR，不繞過。
3. **改到畫面時**：開 PR 前在瀏覽器實際操作一次。在 worktree 用免安裝模式起一個獨立的 app：`frontend/` 先 `npm run build`，再在 `backend/` 帶環境變數 `APP_MODE=standalone` 與 `AIT_DATA_DIR=<暫存資料夾>` 執行 `python -m uvicorn main:app --port <沒用到的埠>`，用瀏覽器開那個埠；資料只寫進暫存資料夾。不要在 worktree 啟動第二套 Docker stack：容器名稱與埠號是固定的，會和使用者正在跑的那套衝突。
4. **PR 內文**：照 `.github/pull_request_template.md` 的段落寫；用 `--body-file` 開 PR 時範本不會自動套用，用 `pr` skill 時照範本開頭寫的對應。CI 檢查「使用者看得到的變更」那一段有內容。
   - 改到畫面時，寫出在瀏覽器點了什麼、看到什麼，附截圖；沒有就寫「無畫面變更」。
   - 動到下列路徑的 PR 是單向門，內文要標明：`CLAUDE.md`、`docs/agents/`、`.githooks/`、`.gitattributes`、`.github/`、`.gitignore`、進版控的 `.claude/` 檔案；閘門的設定 `tools/check.py`、`tools/typecheck_py.py`、`tools/ratchet.py`、`ruff.toml`、`pytest.ini`、`frontend/eslint.config.js`、`pyrightconfig.json`、`.basedpyright/baseline.json`、`backend/typings/`、`frontend/tsconfig.json`；依賴 `backend/requirements*.txt`、`frontend/package.json`、`frontend/package-lock.json`；`migrations/`、`build_release.ps1`。CI 照這份清單在 PR 上留言列出動到的檔案（`tools/pr_checks.py`）。單向門一樣由代理自己驗證、自己合併：在「證據」寫明怎麼驗證，例如用全新的無頭 session 實測設定與 hook。
5. **合併**：ruleset 是唯一的關卡，對代理沒有例外。
   1. 等 `gh pr checks <PR> --watch` 全綠，綠燈之後才回報；紅燈就自己修，push 後回到 1。等很久時放到背景執行並設逾時；結束前停掉自己啟動的背景指令。
   2. 狀態是 `BEHIND` 時執行 `gh pr update-branch`，回到 1。
   3. `gh pr merge --merge`，不加 `--admin` 或 `--delete-branch`。auto 模式的分類器擋下合併時，不換別的方法繞過，請使用者明確說「合併 #<PR>」。
   4. 遠端分支沒有自動刪除時，手動刪掉。要移除 worktree 時，先跑 `git -C <worktree> status --ignored --porcelain`，把被忽略、但還要留的產出（例如誤寫在 worktree 裡的研究筆記）搬到研究區；`git worktree remove` 會不經警告就刪掉它們。

例外：

- **代理驗不了的 PR**：等使用者在本機驗證並回報通過再合併。包括：
  - 要在本機重建 Docker 的 ML 映像的改動（CI 不安裝 ML 依賴，動到 ML 依賴或 `backend/Dockerfile` 的 ML 那一段時就是這種）；
  - 要把音檔送到雲端供應商的改動（用使用者的 API 金鑰、會上傳音檔並產生費用）；
  - 要人工聽打才能驗證的改動。
- **需要本機 GPU 的 PR**（動到本機轉錄的路徑）：代理自己在使用者的電腦上驗證。
  - 用研究區的 `regression/`（研究區的位置見 `CLAUDE.md`，用法見它的 README）：main 與 PR 各起一次免安裝模式的 app，轉錄同一批音檔，比對輸出。
  - 音檔只用公開授權的真實錄音，下載前經使用者同意；不用使用者的私人錄音，也不用合成語音。
  - 輸出要相同，或只差在 PR 內文事先寫明的預期差異（例如時間的捨入），才自己合併。有非預期的差異就停下來，把差異貼在 PR 上，等使用者決定。
  - PR 留言附比對結果：commit、片段與 SHA-256、設定、每種輸出格式是否相同，以及錯字率。
- **資料表結構**：改到 `models.py` 的欄位或 `migrations/` 時，自動遷移補不了的變更，Postgres 要附 `migrations/` 的 SQL，免安裝版（SQLite）要把升級步驟做進程式，讓升級測試（#48）保持綠燈；不要為了讓測試變綠而改寫既有的凍結 schema。PR 內文寫明使用者要執行的步驟；需要使用者執行 SQL 的，等使用者執行並回報後再合併。不要對使用者的資料庫（Docker 的 Postgres、免安裝版的 `data/app.db`）執行遷移或改結構的 SQL。
- **tag**：只推分支，不建立、不推送任何 tag。`v*` tag 一推就會公開發布 Release，由使用者自己推。
