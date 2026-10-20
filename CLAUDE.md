這是準備公開發布給一般使用者的正式產品：程式要可維護、要有測試；使用者的音檔與隱私優先於便利。

- 碰到領域用語時先讀 `GLOSSARY.md`；中文的文件、issue 與 commit 用它的中文詞，程式識別名稱與英文文字用括號裡的英文名稱。動手前讀 `docs/adr/` 裡和這次要動的範圍有關的決策，輸出和它衝突時要明講。
- 從開工到合併照 `docs/agents/merging.md` 自己走完：開工前與合併前各讀一次。
- 實驗、研究筆記與報告寫在研究區：主 checkout 旁邊的 `AI_translate-lab/`（主 checkout 是 `git rev-parse --path-format=absolute --git-common-dir` 的上一層，研究區和它放在同一層），不在 git 裡。標準答案在研究區的 `data/eval/`。舊文件與 issue 寫的 `lab/…` 指的是研究區裡的同一個路徑。wayfinder 的 research 票照 skill 寫在 `research/<名稱>` 分支，push 但不開 PR。

## Agent skills

### Issue tracker

issue 放在 GitHub 的 `Wade0325/AI_translate`，用 `gh` 操作。見 `docs/agents/issue-tracker.md`。

### Triage labels

沿用預設的五個流程標籤，名稱不變。見 `docs/agents/triage-labels.md`。

### Domain docs

單一上下文：根目錄的 `GLOSSARY.md` 加 `docs/adr/`。見 `docs/agents/domain.md`。
