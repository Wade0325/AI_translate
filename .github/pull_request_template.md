<!--
每一段都要寫，用不到的寫「無」。開 PR 時不經網頁（例如 gh pr create --body-file）就不會套用這份範本，
照同樣的段落寫。CI 檢查「使用者看得到的變更」這一段有沒有內容（tools/pr_checks.py）。

用 `pr` skill 寫內文時，不要在範本底下另外接它的三段：Summary 寫進「變更」，Evidence 寫進「證據」，
Merge Danger 的 Door 與 Blast Radius 寫進「門的類型」與「影響範圍」。
-->

## 變更

<!-- 改了什麼、為什麼；Closes #N 寫在這裡。用最小的圖說清楚：虛擬碼、呼叫樹、元件樹、檔案樹、Mermaid 或 diff。 -->

## 使用者看得到的變更

<!-- 必填，沒有就寫「無」。發版說明由這一段組成。改到使用者看得到的行為時，檢查 README.md 要不要跟著改。 -->

## 證據

<!--
Before／After：改動前後的輸出或截圖，或改動前失敗、改動後通過的測試。只寫「測試通過」不算證據。
改到畫面時，寫出在瀏覽器點了什麼、看到什麼並附截圖（docs/agents/merging.md 第 3 步）；沒有就寫「無畫面變更」。
-->

- **Before**：
- **After**：
- **畫面**：

## 測試變動

<!-- 新增、修改或刪除了哪些測試，各自守住什麼。刪掉或放寬斷言時寫明理由。 -->

## 門的類型

<!--
two-way：revert 就回到原樣。one-way：破壞性或難以回復。動到 docs/agents/merging.md 第 4 步列出的單向門路徑時
寫 one-way，並在「證據」寫明怎麼驗證；CI 會在 PR 上留言列出這些檔案。
-->

## 影響範圍

<!-- 這個 PR 改錯時會影響到什麼：哪些使用者、哪些功能、資料或相容性。 -->

## 評測摘要

<!--
動到下列任一路徑時必填，其他 PR 寫「不適用」。這些路徑會改變本機轉錄的輸出（判定規則見 docs/adr/0009）：
- backend/app/provider/local/**（含模型權重 revision 的釘版 weights.py）
- backend/app/services/transcription/**、backend/app/services/silence_removal/**、backend/app/services/vad/**、
  backend/app/services/chunked_transcription.py
- backend/app/utils/audio.py：convert_to_wav 產生去靜音用的 16 kHz 單聲道 wav，slice_audio 切出分段轉錄的各段
- backend/app/tasks/transcribe_core.py：任務本體，呼叫轉錄流程、寫入片段
- backend/app/core/config.py 的轉錄調校設定：vad_speech_ratio_skip_threshold（語音佔比低於它才去靜音）、
  long_audio_split_threshold_seconds、local_moss_single_pass_max_seconds（切段門檻）；同一段的費用折扣不算
- backend/requirements-standalone.txt、backend/requirements-ml.txt
Gemini 專屬的路徑（backend/app/provider/google/**、backend/app/core/default_prompt.py、config.py 的
transcription_max_duration_seconds）不列：Gemini 的改動不附評測，照 docs/agents/merging.md 由使用者實測。

怎麼產生（指令的細節見 tools/eval/README.md）：
1. 這個 PR 跑一次 python -m tools.eval transcribe，轉評測集的音檔。基準存在研究區；它的環境（顯卡、套件版本、
   模型權重的 revision、設定）和這次不完全相同時，main 也重跑一次，當作新的基準。
2. python -m tools.eval eval --reference <名稱> --transcript <基準的 LRC> --vs <這個 PR 的 LRC> --json <路徑>
3. python -m tools.eval summary <每個音檔的 JSON>：評測集有好幾個音檔時每個音檔一份 JSON，一次全部給。它每個音檔印一張表，
   最後照 docs/adr/0009 以語言為單位印出回歸判定；整段貼在下面。

- 只貼數字。不要貼 tools/eval 的完整報告、LRC 或任何逐字稿文字：報告裡的錯誤範例是評測集的原文片段，
  其中有只能留在本機的素材。
- 評測要在本機 GPU 上跑（GitHub 的 runner 沒有 GPU）。外部貢獻者的 PR 由維護者代跑：只留本機的片段不能交給
  外部的人。
- 標準答案分批啟用：summary 只用沒有草稿標記（經使用者確認）的標準答案判定，並列出用了哪幾段。還沒有任何日文
  標準答案時，日文附回歸比對（輸出是否相同）與長檔的結尾核對；日文輸出有變、又沒有標準答案能判斷時，停下來等使用者決定。
- summary 的判定是「回歸」，或某種語言「無法判定」（cpMER 的精度分不出高低）時，代理不合併，等使用者明確接受並在
  PR 上記下理由。
-->
