# 本機 git 護欄

這個 repo 不在本機擋危險的 git 指令，例如直推 main、強推、`git commit --no-verify`、`git stash drop`／`clear`。Claude Code 的 deny 規則與 PreToolUse hook 都不用在這件事上。

## 為什麼不做

關卡在伺服器端。main 的 ruleset 要求每個改動都走 PR、`check` 綠燈且分支是最新的、只准 merge commit，也禁止刪除與強推。bypass 名單是空的，對代理和維護者一樣有效。

代理用的是維護者本人的 GitHub 憑證，GitHub 分不出兩者，所以「只擋代理」的限制只能放在本機。但本機的限制擋不完整：

- deny 規則只比對寫出來的指令文字。`git -C <路徑> push`、`git -c …`、`git.exe` 這類寫法都對不上規則。2026-10-13 實測時，`git -C` 的寫法就漏擋過一次。
- 「目前分支就是 main 時，不帶 refspec 的 `git push`」只有讀 git 狀態的 hook 判斷得出來，等於多一支要測試、要維護的腳本（#41 的選項 (b)）。
- Matt 的 `git-guardrails-claude-code` 會擋 `git push`，和代理自己 push、開 PR、合併的流程（`docs/agents/merging.md`）衝突。它放在 skills 的 misc，已經凍結：缺 `jq` 時一律放行、被 `git -C` 繞過這兩個回報都沒有修。他自己的 course-video-manager 也沒有用它，靠的是 ruleset，並寫明 ruleset 是唯一的關卡，對代理沒有例外。

本機擋得到、伺服器擋不到的，是不會進到 main 的操作：

- 跳過 pre-commit（`--no-verify`）：`docs/agents/merging.md` 第 2 步明文禁止。跳過了，CI 的 `check` 照樣會跑同一份 `tools/check.py`，紅燈就不能合併。
- 丟掉 stash、強推 main 以外的分支：只影響本機，或還沒合併的分支。

## 先前的請求

- #41：本機 git 護欄：擋直推 main 與危險的 git 指令。2026-10-13 曾在使用者層登記 deny 規則（選項 (a)），2026-10-14 重設設定時一併清掉；2026-10-15 維護者決定照 Matt，只靠 ruleset。
