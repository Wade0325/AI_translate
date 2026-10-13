# 開 PR 到合併

- 改到使用者看得到的行為時，檢查 `README.md` 要不要跟著改，並在 PR 內文寫一段「使用者看得到的變更」（沒有就寫「無」）。
- 動到下列路徑的 PR 是單向門：內文要標明，等使用者看過 diff 才合併。`CLAUDE.md`、`docs/agents/`、`tools/hooks/`、`.github/`、`.gitignore`、進版控的 `.claude/` 檔案；閘門的設定 `ruff.toml`、`pytest.ini`、`frontend/eslint.config.js`、`pyrightconfig.json`、`frontend/tsconfig.json`；依賴 `backend/requirements*.txt`、`frontend/package.json`、`frontend/package-lock.json`；`migrations/`、`build_release.ps1`。
- CI 不安裝 ML 依賴：動到 ML 依賴或 `backend/Dockerfile` 的 ML 那一段時，請使用者在本機重建 Docker 確認。
- 使用者同意後才合併。
- 只推分支，不建立、不推送任何 tag：`v*` tag 一推就會公開發布 Release，由使用者自己推。
- 移除 worktree 之前，先跑 `git -C <worktree> status --ignored --porcelain`，把 `lab/` 之類被忽略的產出複製出來；`git worktree remove` 會不經警告就刪掉它們。
