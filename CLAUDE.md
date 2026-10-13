這是準備公開發布給一般使用者的正式產品：程式要可維護、要有測試；使用者的音檔與隱私優先於便利。

- 碰到領域用語時先讀 `GLOSSARY.md`；寫程式、文件、issue 與 commit 都用它定義的詞，不用它列為「避免」的說法。動手前讀 `docs/adr/` 裡和這次要動的範圍有關的決策，輸出和它衝突時要明講。
- 在新分支上改，改完自己 push、開 PR，不必先問；回報前跑 `ruff check .`、`pytest tests/` 與 `frontend/` 裡的 `npm run lint`，紅燈就自己修。
- 開 PR、合併、建立 tag 或移除 worktree 之前，先讀 `docs/agents/pr.md`。
- 審查交給使用者在 PR 上做：不要跑 `/code-review`，skill 裡呼叫它的步驟也略過。
- 實驗、研究筆記與報告寫在主 checkout 的 `lab/`（路徑是 `git rev-parse --path-format=absolute --git-common-dir` 的上一層），不寫在 worktree 裡。
- `lab/data/eval/` 的標準答案與各處的 `.env` 只由使用者修改：用編輯工具或 shell 都不要寫入，需要改時請使用者自己改。
- 改後端的任務派送、進度通知、取消或資料庫時：Docker 模式用到的 Redis、Celery、Postgres，在免安裝版（`APP_MODE=standalone`）都有行程內的替代實作，兩邊都要能動；在 `backend/` 搜尋 `is_standalone` 與 `sqlite` 找出位置。
- 新增接收伺服器檔名的端點時，一律經 `utils/paths.py` 的 `resolve_upload_path()`。
