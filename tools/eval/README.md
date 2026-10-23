# 評測工具（tools/eval）

拿轉錄結果（LRC）和評測集的標準答案比對，算錯字率（MER）、說話者歸屬與錯誤分類。改轉錄流程的 PR 用它附上評測數字；工具本身在版控裡，PR 可以指出用的是哪個 commit 的工具。

離線計分：不呼叫任何 API、不讀音檔、不碰資料庫。

## 資料放在哪裡

標準答案、音檔與術語表都不進版控，留在研究區：主 checkout 旁邊的 `AI_translate-lab/`（主 checkout 是 `git rev-parse --path-format=absolute --git-common-dir` 的上一層，所以從 worktree 執行也找到同一個研究區）。

| 資料 | 預設位置 | 換位置 |
|---|---|---|
| 研究區 | 主 checkout 旁邊的 `<主 checkout 名稱>-lab/` | 環境變數 `AIT_LAB_DIR` |
| 標準答案 | 研究區的 `data/eval/` | `--reference-dir`，或直接給 `--reference` 一個路徑 |
| 術語表 | 研究區的 `glossaries/` | `--vocabulary-dir`，或直接給 `--vocabulary` 一個路徑 |
| 音檔 | 研究區的 `data/audio/` | 這個工具不讀音檔；轉錄結果另外產生，用 `--transcript` 指定 |

工具只讀取標準答案，不寫入；`--json` 指到標準答案的資料夾時會拒絕。

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

## 標準答案的格式

一個檔案是評測集裡的一段連續音訊，格式見 `reference_set.py` 開頭的說明：表頭寫名稱與時間範圍，每行一句「代號: 文字」，`~` 開頭是附和，`[聽不清]` 的位置不計分，`A?:` 與 `(?)` 是草稿標記。

轉錄結果讀 LRC 的「`[mm:ss.xx][S0] 文字`」，只算落在標準答案時間範圍內的行。沒有說話者標記的行（例如 Gemini 的轉錄結果）也讀，全部算同一位說話者 `S?`，報告開頭會提醒；沒有時間戳的行不計分，同樣會提醒。

## 報告裡的數字

- **MER**：中文字 1 個 token、英文詞 1 個 token。不用 CER，因為主要錯誤是英文術語，以字元算會低估。
- **95% CI**：對行重抽樣（bootstrap）。改善要大於區間才算真的；`--vs` 用同一組重抽樣索引做成對比較。
- **排除附和後**：扣掉 `~` 開頭的行再算一次。
- **cpMER 局部／全域對應**：局部是每段音檔各自取最佳的說話者對應；全域是評測集的所有音檔共用一組對應。兩者的差距就是說話者標記在音檔之間不一致的代價。
- **術語召回與誤插入**：用 `--vocabulary` 的術語表算。上下文偏置一定會讓兩者同時上升，要並排看。
- **錯誤預算**：每段差異分成跨語言術語、術語拼寫、中文術語、口音同音、漏字、插入、其他。

正規化兩邊同時做（全半形、[聽不清]、草稿標記、繁簡、大小寫、標點、語助詞、逐字母縮寫、個位數字）。繁簡用 `t2s` 而不是 `tw2sp`：後者會做詞彙替換，把真正的辨識錯誤洗掉。細節見 `mer.py` 開頭的說明。

## 和研究區的關係

研究區 `src/` 的原檔保留不動，研究區的指令照舊可用。這裡只搬了 eval 與 selftest 需要的部分：

| 研究區 | 這裡 |
|---|---|
| `goldset.py` | `reference_set.py`（`read_gold` → `read_reference`） |
| `mer.py`、`phon.py`、`lrc.py` | 同名；`lrc.py` 只留讀取 |
| `refine.py` 的 `load_glossary` | `custom_vocabulary.py` 的 `load_custom_vocabulary`；`Refiner` 不搬 |
| `run.py` 的 `eval`、`selftest` | `cli.py`；`--gold` → `--reference`、`--hyp` → `--transcript`、`--glossary` → `--vocabulary` |

沒有搬的：`run.py` 的其他子指令（vad-sweep、prompt、refine、make-eval、detect、score）與它們用到的模組；`moss.py`，包括 `moss.py pipeline`，它已經不走正式的轉錄路徑。

計分規則和研究區的版本相同。差別在讀轉錄結果：研究區只讀有 `[Sn]` 的行，沒有說話者標記的行會被默默丟掉；這裡讀進來。另外研究區每次 eval 都在 `runs/` 留一份 manifest，這裡只在給了 `--json` 時才寫，內容多了工具的 commit（`tool_version`）。

自我驗證的案例全是自造的例句，不取自任何真實錄音；新增案例時也一樣。
