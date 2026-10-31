# 評測工具（tools/eval）

拿轉錄結果（LRC）和評測集的標準答案比對，算錯字率（MER）、說話者歸屬與錯誤分類。改轉錄流程的 PR 用它附上評測數字；工具本身在版控裡，PR 可以指出用的是哪個 commit 的工具。

`eval`、`summary`、`selftest` 與 `three-way` 離線執行：不呼叫任何 API、不讀音檔、不碰資料庫。要計分的轉錄結果用 `transcribe` 產生：它跑正式的轉錄路徑，會讀音檔、用顯卡，見[產生轉錄結果](#產生轉錄結果transcribe)。

## 資料放在哪裡

標準答案、音檔與術語表都不進版控，留在研究區：主 checkout 旁邊的 `AI_translate-lab/`（主 checkout 是 `git rev-parse --path-format=absolute --git-common-dir` 的上一層，所以從 worktree 執行也找到同一個研究區）。

| 資料 | 預設位置 | 換位置 |
|---|---|---|
| 研究區 | 主 checkout 旁邊的 `<主 checkout 名稱>-lab/` | 環境變數 `AIT_LAB_DIR` |
| 標準答案 | 研究區的 `data/eval/` | `--reference-dir`，或直接給 `--reference` 一個路徑 |
| 術語表 | 研究區的 `glossaries/` | `--vocabulary-dir`，或直接給 `--vocabulary` 一個路徑 |
| 音檔 | 研究區的 `data/audio/` | `transcribe` 用 `--audio` 指定；`eval` 不讀音檔，轉錄結果用 `--transcript` 指定 |

工具只讀取標準答案，不寫入；`--json` 或 `--out` 指到標準答案的資料夾時會拒絕。

## 安裝

依賴列在 `backend/requirements-dev.txt`（`opencc-python-reimplemented`、`rapidfuzz`、`pypinyin`，版本和研究區 `vendor/` 裡的相同）：

```powershell
backend\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
```

不要換成 PyPI 上叫 `opencc` 的官方原生綁定，理由見 `requirements-dev.txt` 的註解。

## 執行

一律在 repo 根目錄執行：

```powershell
# 自我驗證：正規化、錯誤分類與同音判斷的已知案例（pytest 也跑同一組，見 tests/unit/test_eval_*.py）
backend\.venv\Scripts\python.exe -m tools.eval selftest

# 對標準答案計分；--reference 給檔名去掉 .txt 的部分，可以一次給好幾段
backend\.venv\Scripts\python.exe -m tools.eval eval --reference rec17_A.draft --allow-draft `
    --transcript <轉錄結果>.lrc --vocabulary <術語表名稱>

# 兩份轉錄結果做成對比較（同一組重抽樣），另外把數字寫成 JSON
backend\.venv\Scripts\python.exe -m tools.eval eval --reference rec17_A.draft --allow-draft `
    --transcript <基準>.lrc --vs <實驗>.lrc --vocabulary <術語表名稱> `
    --json <研究區>\runs\<名稱>.json
```

- 標準答案的檔名就是 `--reference` 要給的名稱加上 `.txt`。研究區舊 README 的 `--gold rec17_A` 跑不起來，因為檔案叫 `rec17_A.draft.txt`；這裡要寫 `--reference rec17_A.draft`。名稱找不到時，錯誤訊息會列出資料夾裡有哪些。
- 標準答案還有草稿標記時，沒加 `--allow-draft` 會拒絕；加了以後數字只能當工具驗證，不能當結論。
- Windows 主控台不必另外設 `PYTHONIOENCODING`，工具會把輸出切成 UTF-8。

## 產生轉錄結果（transcribe）

直接呼叫轉錄任務用的 `transcribe_audio`（`backend/app/tasks/transcribe_core.py`）：去靜音、分段轉錄與所選的模型都和應用程式相同，設定的讀法也一樣（見 `backend/app/core/config.py`）。不經 API、任務佇列與資料庫，不必啟動 Docker 或前端。

只跑不需要 API 金鑰的供應商（目前是 `local`），音檔不離開這台電腦。

照順序做：

1. 停掉其他使用顯卡的工作：`local_worker.bat` 的視窗、Docker 裡的 GPU 任務、正在轉錄的應用程式。指令開始前會提醒，等你按 Enter 才開始（加 `--yes` 不等）。
2. 轉錄：

   ```powershell
   backend\.venv\Scripts\python.exe -m tools.eval transcribe --audio <研究區>\data\audio\<音檔> `
       --language zh-TW --out <研究區>\runs\<名稱>
   ```

3. 計分：把產生的 LRC 交給 `eval`。

   ```powershell
   backend\.venv\Scripts\python.exe -m tools.eval eval --reference rec17_A.draft --allow-draft `
       --transcript <研究區>\runs\<名稱>\<音檔名稱>.lrc
   ```

- `transcribe` 只要應用程式的依賴；拿它的結果計分的 `eval` 要先裝 `requirements-dev.txt`（見[安裝](#安裝)）。
- `--provider` 預設 `local`；`--model` 預設是供應商的預設模型（`local` 是 `moss-align`）。
- 一次只用一張顯卡：沒設 `CUDA_VISIBLE_DEVICES` 時設成 `0`，設了不只一張時拒絕。本機的 ASR 模型用 `device_map="auto"`，看得到幾張顯卡就攤到幾張。
- 輸出資料夾寫 `<音檔名稱>.lrc` 與 `<音檔名稱>.manifest.json`；LRC 的格式和應用程式下載的相同（只用 LF）。已經有同名的檔案時拒絕，不覆寫上一次的結果；也不能寫進標準答案的資料夾。
- 不做簡轉繁與台灣用詞替換（#242）：錯字率量的是轉換前的結果，本機的中文照模型寫的簡體與講者說的詞。應用程式下載的中文是繁體輸出（`backend/app/services/traditional_output.py`），由單元測試與 `regression/` 的輸出比對把關，不靠錯字率。
- 轉錄失敗時只寫 manifest（`run.success` 是 `false`，`run.error` 是原因），結束代碼是 1。
- 要轉整個音檔：`eval` 依原音檔的時間軸裁切轉錄結果，cpMER 的全域對應也要整個音檔才量得到。

### manifest 的內容

只記數字與環境，不記任何轉錄文字，可以貼進 PR：

| 欄位 | 內容 |
|---|---|
| `request` | 供應商、模型、語言 |
| `audio` | 檔名、SHA-256、長度（秒） |
| `code` | commit，以及工作區有沒有沒 commit 的改動（`dirty`） |
| `environment.packages` | torch、transformers、moss-transcribe-diarize 的版本；從網址安裝的另記網址 |
| `environment.gpu` | 顯卡名稱、顯存（GB）與 `CUDA_VISIBLE_DEVICES`；沒有顯卡時是 `null` |
| `environment.model_revisions` | 本機模型權重釘住的 revision |
| `environment.settings` | 去靜音與切段的設定 |
| `run` | 成功與否、片段數、耗時（秒）、RTF、峰值顯存（GB）、各階段耗時 |

- 峰值顯存是 PyTorch 向顯卡要過的最大量（`torch.cuda.max_memory_reserved`），不含 CUDA 本身佔用的部分，所以比工作管理員看到的少。
- 耗時與 RTF（耗時 ÷ 音檔長度）是從建立供應商轉接器到轉錄結束的整段，含載入模型與去靜音，和使用者在應用程式裡等的時間相當。
- 各階段照轉錄時的進度訊息切開：階段的名稱就是畫面上的進度訊息，涵蓋從這則訊息到下一則之間做的事，不一定和名稱相符，例如載入 MOSS 模型算在「本機模型：MOSS 轉錄與說話者分離中...」，之後的「本機模型：MOSS 轉錄中 #/# 分鐘...」才是生成。第一則訊息之前算「建立供應商轉接器」；訊息裡的數字換成 `#`，同一個階段併成一筆。改了進度訊息的文字，階段的名稱也跟著變。
- `settings.single_pass_seconds` 是模型能力列出的上限，本機轉接器實際轉錄時可能依顯卡容量切得更短。
- 產生 manifest 的函式在 `backend/app/services/environment_manifest.py`，之後要記錄轉錄環境的地方共用它。

## 標準答案的格式

一個檔案是評測集裡的一段連續音訊，格式見 `reference_set.py` 開頭的說明：表頭寫名稱與時間範圍，每行一句「代號: 文字」，`~` 開頭是附和，`[聽不清]` 的位置不計分，`A?:` 與 `(?)` 是草稿標記。

轉錄結果讀 LRC 的「`[mm:ss.xx][S0] 文字`」，只算落在標準答案時間範圍內的行。沒有說話者標記的行（例如 Gemini 的轉錄結果）也讀，全部算同一位說話者 `S?`，報告開頭會提醒；沒有時間戳的行不計分，同樣會提醒。

## 起草標準答案（three-way）

標準答案由代理起草、使用者只聽有疑問的地方（ADR 0009、#15 Q5）：拿底稿（資料集附的逐字稿、原著、台本）和兩個本機模型的轉錄結果逐句做三方對照，三方一致的直接採用，不一致的列成清單，由使用者聽了決定。

照順序做：

1. 底稿寫成[標準答案的格式](#標準答案的格式)，放研究區的 `data/eval/sources/<名稱>/`。不要直接放進 `data/eval`：那裡沒有草稿標記的檔案會被當成已確認的標準答案。
2. 用 `transcribe` 把同一個音檔轉兩次，`--model moss-align` 與 `--model moss-qwen3-asr`，輸出到不同的資料夾。
3. 比對：

   ```powershell
   backend\.venv\Scripts\python.exe -m tools.eval three-way compare `
       --source <研究區>\data\eval\sources\<名稱>\底稿.txt `
       --transcript <研究區>\runs\<moss-align>\<音檔名稱>.lrc `
       --second-hypothesis <研究區>\runs\<moss-qwen3-asr>\<音檔名稱>.lrc `
       --audio <研究區>\data\audio\<音檔> --out <研究區>\runs\<名稱>\three-way
   ```

   終端機只印數量。`--out` 寫兩個檔案：清單 `<名稱>.three-way.json` 與試聽頁 `<名稱>.three-way.html`。
4. 使用者用瀏覽器打開試聽頁：每一處有「播放」（前後各多放 1.5 秒）、底稿與兩個模型的寫法，選正確的一個；都不對時自己輸入，聽不出來時選「聽不清」（那裡不計分）。決定存在瀏覽器裡，做完按「下載決定」，得到 `<名稱>.decisions.json`。
5. 套用：

   ```powershell
   backend\.venv\Scripts\python.exe -m tools.eval three-way apply `
       --spots <研究區>\runs\<名稱>\three-way\<名稱>.three-way.json `
       --decisions <下載的決定檔> --out <研究區>\runs\<名稱>\three-way\final `
       --confirmed-by <確認者>
   ```

   寫出 `<名稱>.txt`：決定過的地方換成選的寫法，沒決定的地方保留底稿的寫法、後面加草稿標記 `(?)`。每一處都決定了才能加 `--confirmed-by`，標準答案會記下確認者與日期，以及底稿與兩份轉錄結果的 SHA-256 和各種決定的數量。確認後自己複製到研究區的 `data/eval/`。

比對的規則：

- 用計分的正規化（`mer.tokenize`）比，所以標點、繁簡、全半形、語助詞與括號標註的非語言聲不同不會被列出來，只列會影響錯字率的差異。底稿的 `[聽不清]` 對什麼都算一致。日文漢字與假名的寫法不同（良い／よい）照樣列出，和計分一致。
- 相鄰的不一致併成一處，隔著一個一致的 token 就分開，也不跨到底稿的下一句。底稿沒有、模型多出來的字落在兩句之間時，看那些字在轉錄結果裡和哪一句同一行。
- 每一處分成三類，試聽頁可以照類別篩選，也可以把某一類沒決定的全部採用底稿：
  - **兩個模型一致、底稿不同**：底稿可能錯（朗讀者讀錯或跳行、紀錄整理過），也可能兩個模型錯在同一處；最需要聽。
  - **三方都不同**。
  - **底稿和其中一個模型一致**：另一個模型不同。
- 時間點：LRC 只有每行的開始時間，行內的位置照字數在這一行和下一行的開始時間之間內插（每字最多算 0.4 秒），只拿來定位播放。兩個模型在那一處都沒有字（一起漏掉）時改用底稿那一句的時間戳；底稿沒有時間戳才用模型前一個字的時間，模型漏掉一長段時會不準。
- 決定以每一處的編號記錄，下載的決定帶著清單的指紋（`digest`）；重跑 `compare` 後編號會對到別處，`apply` 會拒絕舊的決定。`compare` 之後改過底稿，`apply` 也會拒絕。
- 只比文字，不比說話者代號。選了模型的寫法時，連同中間的標點一起換進去；標點不計分，不影響錯字率。

清單與試聽頁裡有底稿與轉錄結果的全文，和標準答案一樣只留在研究區，不貼進 issue 或 PR；工具不寫進 `data/eval`。

## 報告裡的數字

- **MER**：漢字、平假名、片假名每字 1 個 token（含長音「ー」與「々」），英文詞 1 個 token；日文和中文的算法相同（ADR 0009）。不用 CER，因為主要錯誤是英文術語，以字元算會低估。漢字與假名的寫法不同（ありがとう／有難う）照算錯。
- **95% CI**：對行重抽樣（bootstrap）。改善要大於區間才算真的；`--vs` 用同一組重抽樣索引做成對比較。
- **排除附和後**：扣掉 `~` 開頭的行再算一次。
- **cpMER 局部／全域對應**：局部是每段音檔各自取最佳的說話者對應；全域是評測集的所有音檔共用一組對應。兩者的差距就是說話者標記在音檔之間不一致的代價。
- **術語召回與誤插入**：用 `--vocabulary` 的術語表算。上下文偏置一定會讓兩者同時上升，要並排看。
- **錯誤預算**：每段差異分成跨語言術語、術語拼寫、中文術語、口音同音、漏字、插入、其他。

正規化兩邊同時做（全半形、[聽不清]、草稿標記、括號標註的非語言聲、繁簡、大小寫、標點、語助詞、逐字母縮寫、個位數字）。非語言聲不計分（#15 Q2c）：標準答案不寫；轉錄結果裡用 `()`、`[]`、`【】`（全形、半形都算）括起來的，例如「（笑）」「[拍手]」，連同括號整段刪掉，只看括號、不看裡面寫什麼。繁簡用 `t2s` 而不是 `tw2sp`：後者會做詞彙替換，把真正的辨識錯誤洗掉。`t2s` 之後再把「着」併成「著」（#243）：「著」在簡體裡也合法（著作、显著），`t2s` 不會換，不併的話標準答案用繁體時，轉錄結果的每個「着」都算一個錯。細節見 `mer.py` 開頭的說明。

## PR 的評測摘要（summary）

PR 範本（`.github/pull_request_template.md`）的「評測摘要」用這個指令產生：

```powershell
# 評測集的每個音檔各做一次：main 與 PR 的轉錄結果做成對比較，寫成 JSON
backend\.venv\Scripts\python.exe -m tools.eval eval --reference <名稱> `
    --transcript <研究區>\runs\<main>\<音檔名稱>.lrc --vs <研究區>\runs\<PR>\<音檔名稱>.lrc `
    --json <研究區>\runs\<PR>\<音檔名稱>.json

# 所有音檔的 JSON 一次給，整理成 Markdown，整段貼進 PR
backend\.venv\Scripts\python.exe -m tools.eval summary <研究區>\runs\<PR>\<音檔一>.json `
    <研究區>\runs\<PR>\<音檔二>.json
```

- 讀 `eval --json` 的檔案，以及每份轉錄結果旁邊的 manifest（`transcribe` 寫的 `<音檔名稱>.manifest.json`）。轉錄結果的路徑是相對路徑時，先照目前的資料夾找，再照 JSON 所在的資料夾找。
- 每個音檔印一張表：commit、模型與語言、錯字率與 cpMER（全域對應）、RTF 與峰值顯存、結尾核對，兩份轉錄結果時再加上 ΔMER 與 95% CI；另外列出音檔的 SHA-256、標準答案的名稱與草稿標記、用的指令。最後是回歸判定。
- **結尾核對**：LRC 最後一行開始的時間和音檔長度比，看結尾有沒有掉尾。只讀時間戳。
- 所有音檔的 JSON 要一次給，判定才涵蓋整個語言；分開執行時，每次只判定給了的那幾個音檔。PowerShell 不會替 `python` 展開 `*.json`，要一個一個列出來。
- **回歸判定**：照 `docs/adr/0009`，以語言為單位。
  - 同一種語言的片段合起來算（錯誤數總和 ÷ token 總和），錯字率或 cpMER 比基準高就印「回歸」，否則印「通過」。兩邊對的是同一組標準答案、分母相同，所以實際比的是錯誤數，多一個錯就是回歸。表裡列出每種語言用了哪幾段標準答案。
  - 語言看 manifest 的 `request.language`，只看主要的語言代碼：`zh-TW` 與 `zh-CN` 都是中文。
  - 這幾種 JSON 不算進判定，摘要會列出來與原因：只有一份轉錄結果（沒有 `--vs`）、標準答案還有草稿標記、兩邊轉錄的音檔不同（SHA-256 不一樣）、找不到 manifest 或兩邊的語言不同。一份都沒得算時，印「無法判定：沒有已確認的標準答案可以和基準比」。
  - cpMER 在 JSON 裡只有比率、取到小數第四位，判定時乘回 token 數還原錯誤數：一段少於 10000 個 token 時是確切的；更長的段只還原得出一個範圍，範圍重疊、分不出 PR 有沒有比基準多錯時，印「無法判定」，代理不合併。
  - 95% CI、RTF、峰值顯存與結尾核對只列出，不參與判定。
- 只輸出數字、雜湊與檔名，不輸出錯誤範例或任何轉錄文字，可以直接貼進 PR。找不到 manifest 的欄位寫「—」，摘要最後會列出找不到的是哪一份。
- `eval --json` 為此多寫了兩項：每份轉錄結果的 `cp_mer_global`（全域對應的 cpMER）與 `global_mapping`，以及兩份轉錄結果時的 `paired`（`delta_mer`、`ci`、`significant`）。

## 和研究區的關係

研究區 `src/` 的原檔保留不動，研究區的指令照舊可用。這裡只搬了 eval 與 selftest 需要的部分：

| 研究區 | 這裡 |
|---|---|
| `goldset.py` | `reference_set.py`（`read_gold` → `read_reference`） |
| `mer.py`、`phon.py`、`lrc.py` | 同名；`lrc.py` 只留讀取 |
| `refine.py` 的 `load_glossary` | `custom_vocabulary.py` 的 `load_custom_vocabulary`；`Refiner` 不搬 |
| `run.py` 的 `eval`、`selftest` | `cli.py`；`--gold` → `--reference`、`--hyp` → `--transcript`、`--glossary` → `--vocabulary` |

沒有搬的：`run.py` 的其他子指令（vad-sweep、prompt、refine、make-eval、detect、score）與它們用到的模組；`moss.py`，包括 `moss.py pipeline`，它已經不走正式的轉錄路徑，要產生轉錄結果改用 `transcribe`。

計分規則和研究區的版本相同。差別在讀轉錄結果：研究區只讀有 `[Sn]` 的行，沒有說話者標記的行會被默默丟掉；這裡讀進來。另外研究區每次 eval 都在 `runs/` 留一份 manifest，這裡只在給了 `--json` 時才寫，內容多了工具的 commit（`tool_version`）。

自我驗證的案例全是自造的例句，不取自任何真實錄音；新增案例時也一樣。
