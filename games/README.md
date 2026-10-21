# games／圈圈叉叉（tic-tac-toe）

雙人對戰的命令列遊戲，給開發者在repo 裡玩、也當作「規則與介面分離＋命令列怎麼測」的範例。
不在轉錄產品的流程裡，也不會進免安裝版（`build_release.ps1` 不含 `games/`）。

## 怎麼玩

在 repo 根目錄（不需要裝任何額外套件，只用 Python 標準函式庫）：

```powershell
python -m games.tictactoe              # 稱呼是「玩家一」「玩家二」
python -m games.tictactoe 小美 小華    # 自訂稱呼：第一位用 X 並先手
python -m games.tictactoe --rounds 3   # 打三局就結束（每局換對方先手）
```

同一個終端機輪流輸入：

| 輸入 | 作用 |
| --- | --- |
| `1`–`9` | 下在棋盤上那一格（格號由左而右、由上而下） |
| `u` | 悔一手，收回上一手，換回剛剛那個人重下 |
| `h` | 再顯示一次指令說明 |
| `q` | 結束遊戲（這一局不算成績） |
| `y`／`n` | 一局結束後，要不要再來一局 |

先連成三子（橫、直、斜任一方向）的人獲勝；9 格都滿而沒人連成三子就是平手。
計分板會一路累計各人勝場與平手次數，並標出每局的三連珠是哪三格（例如 `三連珠：1-2-3`）。

## 檔案

| 路徑 | 內容 |
| --- | --- |
| `games/tictactoe/engine.py` | 規則：棋盤、輪次、下子、悔手、勝負與平手。不讀輸入也不印東西 |
| `games/tictactoe/cli.py` | 輸入輸出：印棋盤、讀格號、計分、多局與換先手 |
| `games/tictactoe/__main__.py` | `python -m games.tictactoe` 的進入點 |
| `tests/unit/test_tictactoe_engine.py` | 規則的單元測試（每條必勝線、平手、悔手、輸入驗證） |
| `tests/unit/test_tictactoe_cli.py` | 把 `stdin`／`stdout` 換成 `StringIO` 跑整局遊戲，不用真的開終端機 |

## 用詞

`GLOSSARY.md` 是轉錄產品的領域詞彙，沒有遊戲相關的字；這裡自己定義並全專案統一：

**棋盤**（board）：3x3 共 9 格。
**格**（cell）：棋盤上的一格。使用者輸入格號 1-9，程式內部的索引是 0-8。
**悔手**（undo）：收回上一手，換回剛剛那個人重下。
**三連珠**（winning line）：同一方向連著的三格，也就是獲勝的條件。
**平手**（draw）：9 格都滿了但沒人連成三子。

## 為什麼只用 ASCII 畫棋盤

使用者的 Windows 終端機常用 Big5 碼頁（cp950），方框線那個 `│`（U+2502）在某些碼頁會印不出來。
棋盤只用 `|`、`-`、`+`；`__main__.py` 另外把輸出的編碼錯誤改成 `backslashreplace`
（和 `tools/check.py` 一樣），印不出的字元不會讓遊戲崩掉。

## 檢查

`tools/check.py` 的 `PYTHON_DIRS` 含 `games/`，所以改到遊戲時，commit 前的 ruff 與 CI 的
pytest 都會蓋到它，和後端其他程式碼一樣。
