這是準備公開發布給一般使用者的正式產品：程式要可維護、要有測試；使用者的音檔與隱私優先於便利。

- 碰到領域用語時先讀 `GLOSSARY.md`；中文的文件、issue 與 commit 用它的中文詞，程式識別名稱與英文文字用括號裡的英文名稱。動手前讀 `docs/adr/` 裡和這次要動的範圍有關的決策，輸出和它衝突時要明講。
- 從開工到合併照 `docs/agents/merging.md` 自己走完：開工前與合併前各讀一次。
- 把關交給 CI 與合併流程（`docs/agents/merging.md`）：不要跑 `/code-review`，skill 裡呼叫它的步驟也略過。
- 實驗、研究筆記與報告寫在主 checkout 的 `lab/`（路徑是 `git rev-parse --path-format=absolute --git-common-dir` 的上一層）。

## Agent skills

### Issue tracker

issue 放在 GitHub 的 `Wade0325/AI_translate`，用 `gh` 操作。見 `docs/agents/issue-tracker.md`。

### Triage labels

沿用預設的五個流程標籤，名稱不變。見 `docs/agents/triage-labels.md`。

### Domain docs

單一上下文：根目錄的 `GLOSSARY.md` 加 `docs/adr/`。見 `docs/agents/domain.md`。
