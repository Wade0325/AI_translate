# 擋代理寫入特定檔案的 hook

這個 repo 不用 Claude Code 的 PreToolUse hook 擋代理寫入、刪除或搬移特定的檔案。#40（2026-10-15）曾把一支保護標準答案（`lab/data/eval/`）與 `.env` 的 hook 登記進版控，2026-10-19 拿掉。

## 為什麼不做

不能重建的資料不放在 repo 的資料夾裡。研究區（含標準答案）放在 git 頂層目錄外（位置見 `CLAUDE.md`），`git clean`、移除 worktree 與代理在 repo 裡下的指令都碰不到它，另外再備份。這樣不用猜代理會下什麼指令，也不依賴代理在哪個作業系統上執行。

用 hook 保護的問題：

- hook 自己起不來時只能二選一：放行，或擋下所有動作。#40 選了擋下，指令又用 Windows 才有的 `py -3`。2026-10-19 在沒有 `py` 的雲端（Linux）session 裡，連 `echo`、`git status` 都被擋，而雲端的 checkout 根本沒有 `lab/` 與 `.env`。
- 擋不完整：子程序自己寫檔、用變數組出來的路徑、沒列到的寫檔指令（例如 `sed -i`）都擋不到，原本那支 hook 的說明就列出了這些例外。
- Matt 的 course-video-manager 只用 hook 引導習慣（擋 `npx tsc`，改用 `pnpm run typecheck`），沒有用 hook 保護檔案。

## 仍然要注意

`git clean -fdx` 會刪掉 repo 裡所有被 git 忽略的檔，例如 `.env` 與 `/data/`（免安裝模式的資料目錄）。本機不擋 git 指令（見 `local-git-guardrails.md`），所以不能重建的資料一律放到 repo 外，或另外備份。

## 先前的請求

- #40：hook 設定進版控，受保護路徑的 hook 用 `py -3` 執行、起不來就擋（2026-10-15）。2026-10-19 使用者決定把研究區（含標準答案）整個搬到 repo 外，拿掉這支 hook。
