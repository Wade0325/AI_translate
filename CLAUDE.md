這是準備公開發布給一般使用者的正式產品：程式要可維護、要有測試；使用者的音檔與隱私優先於便利。

- 碰到領域用語時先讀 `GLOSSARY.md`；中文的文件、issue 與 commit 用它的中文詞，程式識別名稱與英文文字用括號裡的英文名稱，都不用列在「不要說成」底下的說法。動手前讀 `docs/adr/` 裡和這次要動的範圍有關的決策，輸出和它衝突時要明講。
- 改完自己 push、開 PR，不必先問；等 `check` 綠燈再回報，紅燈就自己修。
- 開始改動前與合併前，各讀一次 `docs/agents/merging.md`。
- 把關交給 CI 與合併流程（`docs/agents/merging.md`）：不要跑 `/code-review`，skill 裡呼叫它的步驟也略過。
- 實驗、研究筆記與報告寫在主 checkout 的 `lab/`（路徑是 `git rev-parse --path-format=absolute --git-common-dir` 的上一層），不寫在 worktree 裡。
- `lab/data/eval/` 的標準答案與各處的 `.env` 只由使用者修改：用編輯工具或 shell 都不要寫入，需要改時請使用者自己改。
- 改後端的任務派送、進度通知、取消或資料庫時：Docker 模式用到的 Redis、Celery、Postgres，在免安裝模式（`APP_MODE=standalone`）都有行程內的替代實作，兩邊都要能動；在 `backend/` 搜尋 `is_standalone` 與 `sqlite` 找出位置。
- 新增接收伺服器檔名的端點時，一律經 `utils/paths.py` 的 `resolve_upload_path()`。

## Agent skills

### Issue tracker

issue 放在 GitHub 的 `Wade0325/AI_translate`，用 `gh` 操作。見 `docs/agents/issue-tracker.md`。

### Triage labels

沿用預設的五個流程標籤，名稱不變。見 `docs/agents/triage-labels.md`。

### Domain docs

單一上下文：根目錄的 `GLOSSARY.md` 加 `docs/adr/`。見 `docs/agents/domain.md`。
