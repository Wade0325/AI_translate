<div align="center">
  <h1>🎙️ Mimiji</h1>
  <p><strong>日文、中文語音轉錄與字幕</strong></p>
  <p>給 Windows 個人使用者的語音轉錄工具：把日文與中文音檔轉成帶說話者標記與時間戳的字幕和逐字稿，預設在本機 GPU 上執行，沒有合適顯卡時可改用 Gemini。</p>
  <p><sub>Mimiji 寫作「耳字」：用耳朵聽，變成字。</sub></p>

  ![Windows x64](https://img.shields.io/badge/Windows-x64-0078D4)
  ![License](https://img.shields.io/badge/License-Apache_2.0-blue)
</div>

---

## 📖 目錄

- [✨ 功能特色](#-功能特色)
- [💻 系統需求](#-系統需求)
- [🚀 安裝](#-安裝)
- [📘 使用教學](#-使用教學)
- [🔒 資料與隱私](#-資料與隱私)
- [🐛 回報問題](#-回報問題)
- [🚧 已知限制](#-已知限制)
- [🔧 開發者指南](#-開發者指南)
- [📝 授權](#-授權)

---

## ✨ 功能特色

### 🎯 核心能力

- **🖥️ 本機轉錄（預設）**：在自己的 NVIDIA 顯卡上轉錄，音檔不離開這台電腦，也沒有 API 費用。預設的 MOSS-Transcribe-Diarize 一次完成說話者分離與轉錄，再由 Qwen3-ForcedAligner 做強制對齊並斷行；另可選 MOSS + Qwen3-ASR、舊版 VibeVoice + Qwen3-ASR。
- **👥 說話者分離**：本機的轉錄結果每一行都標上說話者標記，寫成 `[S0] 文字`、`[S1] 文字`；Gemini 在開啟 Multi-Speaker 時也這樣標。
- **🌏 日文與中文**：官方支援日文與中文。中文的轉錄結果一律是台灣繁體的字形與用詞；看得出是日文時不轉，日文漢字不會被改。
- **⏱️ 逐行時間戳**：LRC、SRT、VTT 每一行都帶時間戳（LRC 為 `[mm:ss.xx]`），TXT 只有文字；單檔任務與批次相同。
- **📦 多格式匯出**：LRC、SRT、VTT、TXT 一鍵下載，多個檔案可以打包成 ZIP。字幕照實際說話的時間顯示，並依說話者上色。
- **🗣️ 長音檔分段轉錄**：超過模型單次能處理的長度時，切在靜音處分段轉錄再接回。本機的模型不去靜音，因為剪掉靜音會讓說話者分離變差；Gemini 轉錄前剪掉長段靜音以節省 Token。本機的模型切在靜音的正中間，Gemini 切在剪掉靜音的位置；語音佔比不低於 90% 的音檔兩者都改用 Silero VAD 找，都找不到時切在正中間。
- **🕘 歷史紀錄**：轉錄結果存在你電腦上的 `data\app.db`，可以隨時回查與重新下載。

### ☁️ 選用：Gemini

沒有合適的顯卡時，可以改用 Google Gemini 轉錄（`gemini-3.5-flash`、`gemini-2.5-flash` 等）。要自備 [Gemini API 金鑰](https://aistudio.google.com/apikey)，音檔會上傳到 Google（見[資料與隱私](#-資料與隱私)）。下面這些功能只有 Gemini 有：

| 功能 | 說明 |
|------|------|
| 📚 **批次** | 採用 Gemini Batch API，**費用為標準 API 的 50%**，適合大量檔案非同步處理 |
| 🔄 **批次恢復** | 應用程式重啟或網路中斷後，停住或失敗的批次在任務頁按「恢復」，就接著等 Gemini 的結果（無需重新上傳） |
| 📝 **提示詞** | 補充說話者是誰、要照寫的人名與專有名詞、ASMR 聲響描述等；本機的模型不支援提示詞 |
| 🔁 **暫時錯誤重試** | Gemini 回應 429／503 時只重試出錯的那一段，已經轉好的段不重送；批次只重做出錯的那一步（上傳、送出或查詢狀態）。照回應建議的秒數等待（沒有建議時 10、20、40 秒），等待時畫面寫出是哪一段或哪一步、等幾秒 |
| 💰 **成本追蹤** | 自動計算每次任務的 Token 用量與費用（包含失敗後被重試取代的那次呼叫；任務失敗或取消時，供應商已經回應的部分照樣收費，也照記），可在計費頁（`/billing`）查詢 |

---

## 💻 系統需求

| 項目 | 需求 |
|------|------|
| 作業系統 | Windows（64 位元） |
| 顯卡（本機轉錄） | NVIDIA 顯卡，顯卡記憶體 12 GB 以上，建議 16 GB。8–12 GB 沒有測過；低於 8 GB 可能很慢，長音檔的說話者編號也比較容易對不上，畫面會提示，但照樣能用。GTX 900 系列（Maxwell）以前的顯卡不支援；GTX 10 系列（Pascal）沒有測過 |
| 顯卡（Gemini） | 不需要，但要自備 Gemini API 金鑰 |
| 磁碟空間 | 首次啟動下載的執行環境約 3.5 GB；本機的預設模型權重約 3.7 GB，選用模型另需約 21 GB |
| 網路 | 首次啟動與下載模型權重時需要；用 Gemini 轉錄時也需要 |

---

## 🚀 安裝

Mimiji 只發布 Windows 免安裝版：下載 zip、解壓縮就能用，不必安裝其他軟體。

1. 到 [**Releases**](https://github.com/Wade0325/AI_translate/releases) 下載最新的 `AI_Translate-vX.Y.Z-win64.zip`。
2. 解壓到任意位置（建議路徑不含中文與空白）。
3. 雙擊 **`AI_Translate.exe`**，會開一個黑色視窗。
   - 首次啟動會自動下載執行環境（約 3.5 GB，含 PyTorch），視網速需要數分鐘到數十分鐘；中斷後重開會接著下載。沒有 NVIDIA 顯卡的電腦也一樣會下載這些，只用 Gemini 時其中大部分用不到。
   - 就緒後自動開啟瀏覽器。網址以黑色視窗顯示的為準：預設是 `http://127.0.0.1:8000`，8000 埠被占用時會改用其他埠。
   - 關閉黑色視窗就停止程式。
4. 到 **Settings** 頁的 **Local Models (本機 GPU 模型)** 卡片按「下載模型權重」（預設模型約 3.7 GB）。下載完成後，就能在 **New Transcription** 頁用本機轉錄。
5. 沒有合適的顯卡時，轉錄頁會寫出原因，可以按「改用 Gemini」，再到 Settings 頁的 Gemini 卡片填入 [Gemini API 金鑰](https://aistudio.google.com/apikey)。Gemini 會把音檔上傳到 Google。

> 所有資料（資料庫、模型權重）都在解壓資料夾的 `data\` 內；升級新版時把舊版 `data\` 複製過來即可保留紀錄。哪些是個人資料、怎麼清掉，見[資料與隱私](#-資料與隱私)。
>
> 程式不會自己檢查或下載更新。目前的版本號在 Settings 頁的 About 卡片，新版本請到 [Releases](https://github.com/Wade0325/AI_translate/releases) 下載；想在新版發布時收到通知，可以在 GitHub 上對這個專案按 **Watch**，選 **Custom** 裡的 **Releases**。

---

## 📘 使用教學

### 步驟 1️⃣ — 準備供應商

供應商分**本機**與 **Gemini** 兩個，預設用本機。設定都在左側選單的 **Settings** 頁。

- **本機（預設）**：
  1. **Local Models (本機 GPU 模型)** 卡片顯示偵測到的顯卡與模型權重的狀態。先按「下載模型權重」下載預設模型所需的兩項；要用 MOSS + Qwen3-ASR 或舊版 VibeVoice + Qwen3-ASR 時，再按「下載選用模型」。下載中斷時已下載的部分會保留，重新下載會接著下載。沒有偵測到可用的 NVIDIA 顯卡時，下載按鈕會停用。
  2. 本機不需要 API 金鑰，卡片上沒有金鑰欄位。本機卡片的 **Test Connection** 會檢查顯卡與預設模型的模型權重是否就緒；要檢查別的模型，在轉錄頁選好再按「測試 API」。
- **Gemini（選用）**：
  1. 在 **Gemini** 卡片貼上你的 [Gemini API 金鑰](https://aistudio.google.com/apikey) 並按 **Save**。只有一個金鑰欄位，清空後儲存就是刪掉金鑰。
  2. Gemini 的卡片與轉錄頁選 Gemini 時，會說明音檔會上傳到 Google、Google 怎麼使用，並連到條款原文，見[資料與隱私](#-資料與隱私)。

模型在轉錄頁選，設定頁沒有預設模型的欄位；轉錄頁會記住你上次選的供應商與模型。

### 步驟 2️⃣ — 上傳並設定轉錄參數

進入 **New Transcription** 頁面：

1. **選擇供應商與模型**：先選供應商（本機／Gemini），模型選單只列這個供應商的模型。下次開頁會沿用這次的選擇（記在瀏覽器裡，只有供應商與模型的名稱）。「測試 API」測的是這裡選的模型；「編輯 API」只在選 Gemini 時出現，本機不需要金鑰。
2. **上傳檔案**：拖曳或點擊上傳音檔或影片。音檔支援 MP3、WAV、M4A、FLAC；影片支援 MP4、MOV、MKV、WebM、AVI、WMV、M4V、3GP、MPG、MPEG，上傳時先在這台電腦抽出聲音，之後只轉錄聲音，影片本身不保留、也不會送到 Gemini。單檔最大 2 GB，放得下 2 小時的 WAV。可以一次加入多個檔案，每個檔案各是一個任務。
3. **選擇來源語言**：選單最上面是 Auto Detect，下面分兩組。「官方支援」是日文與中文（繁體）；「未驗證」的語言（英文、韓文等）可以選，但轉錄品質沒有經過驗證，選了之後選單與檔案卡都會標「（未驗證）」。中文的轉錄結果一律是台灣繁體的字形與用詞：講者說「軟件」也寫成「軟體」。用詞是照字典自動換的，偶爾會換錯（例如「我支持你」寫成「我支援你」），校正時請留意；結果看得出是日文時，選了中文或 Auto Detect 也不轉，日文漢字不會被改。
4. **（選填）Multi-Speaker**：目前只影響 Gemini，開啟後自動標記不同說話者（`[S0]`、`[S1]`）。本機的轉錄結果一律帶說話者標記。
5. **（選填）提示詞**：只有 Gemini 支援，選本機的模型時提示詞欄位會停用並註明原因。轉錄頁填的提示詞是補充說明，例如說話者是誰、人名照寫，送出時空一行接在提示詞範本後面；範本裡要求 LRC 格式與時間戳的指示一定會送出。全域的提示詞會送給每個沒有個別設定提示詞的檔案，不必按 Apply to All；個別檔案可以在每檔設定改用自己的，清空就回到跟著全域。都沒填時只送提示詞範本。提示詞範本是設定頁各供應商的 Prompt Template 欄位存的（轉錄頁的「編輯參數」也能改，會帶出目前的範本，沒存過就是系統內建的），想整份改寫就改那裡，並保留要求 LRC 格式與時間戳的指示，否則轉錄會失敗。

### 步驟 3️⃣ — 開始轉錄

- 按 **Start** 開始轉錄，畫面即時顯示每個檔案的進度。
- **處理模式**預設是「標準」，結果直接回到轉錄頁。只有 Gemini 的模型支援 Flex 與批次，選本機的模型時這兩個選項會停用並註明原因，已經選了的會退回標準。
- **批次（Gemini）**：改選「批次（50% 費用．非同步）」後送出，可關閉視窗稍後在 **Tasks** 頁面查看。批次還在等 Gemini 的結果時關掉應用程式（例如關掉免安裝版的黑色視窗），重新開啟後任務頁會把它標成「已中斷」；等結果時網路斷了，批次會標成「失敗」。兩種都按「恢復」接著等，不必重新上傳（要先在 Settings 設定 Gemini 的 API 金鑰）。還在上傳時就關掉的批次沒有送出給 Gemini，重新開啟後標成「失敗」，要重新送出。失敗的批次在任務頁留 24 小時。

> 💡 **省錢技巧**：用 Gemini 轉錄不急的大量檔案時，請選「批次」，費用直接 5 折。

### 步驟 4️⃣ — 檢視與下載結果

到 **Result Viewer** 頁面：

- 預覽逐字稿與時間戳。
- 下載 `.lrc` / `.srt` / `.vtt` / `.txt`（多個檔案可以用 **Download All** 打包成 ZIP）。
- SRT／VTT 的字幕照實際說話的時間顯示：另一位說話者插話時，兩行字幕會同時出現，靠行首的說話者標記分辨；同一位說話者的字幕不重疊。每一行至少顯示 0.8 秒，同一位說話者緊接著說下一句時例外。部分字幕編輯器會把重疊的字幕標成錯誤，原因見 [ADR-0008](docs/adr/0008-subtitles-follow-speech-and-may-overlap.md)。
- SRT／VTT 的字幕依說話者上色：S0 白色、S1 黃、S2 青、S3 綠，第 5 位說話者起從白色重新輪；沒有說話者標記的行不上色。SRT 的顏色在 VLC 與 mpv 看得到；VTT 的顏色寫在檔頭的 STYLE 區塊，Chrome 看得到，Firefox 不支援，照樣顯示白字。ffmpeg 7.0 之前的版本讀不了帶 STYLE 區塊的 VTT，用這類工具時請改下載 SRT。LRC、TXT 不上色。
- 一則字幕超過兩行的量（日文 26 個、其他語言 32 個全形字寬，半形字算半個）時，SRT／VTT 照逐字時間拆成數則，優先切在「、」「，」之後；只有本機的轉錄有逐字時間，Gemini 的結果不拆。LRC、TXT 保持一句一行。

### 步驟 5️⃣ — 追蹤紀錄與費用

- **History**：列出所有完成的任務，可重新下載轉錄結果。成功率是「完成 ÷（完成＋失敗）」，處理中與已取消的任務不算在內。
- **計費（Gemini）**：只對 Gemini 有意義，側欄沒有入口，要對帳時直接開 `/billing`。依日期、模型查詢 Token 用量與成本；失敗與取消的任務已經用掉的 Token 與費用也算在內，檔案數只算完成的。
- 轉錄頁的費用估算只在選 Gemini 時出現；選本機時只顯示檔案數與大小。

---

## 🔒 資料與隱私

app 不收集任何遙測，也不自動回報錯誤（[ADR-0005](docs/adr/0005-no-telemetry.md)）。選本機轉錄時，音檔不會離開你的電腦。Settings 頁的「資料與隱私」卡片列出下面這些資訊。

- **保留音檔**：
  - 轉錄結束後，不論成功、失敗或取消，音檔都會留在 `data\audio_store`，日後校正時可以重聽。
  - 預設留 30 天，從上傳時算起；超過的在下次開啟 app 時刪除。
  - 卡片顯示目前留了幾個、多大，按「立即刪除全部保留音檔」就全部刪掉。轉錄結果與紀錄不受影響。
  - 在歷史頁刪掉一筆紀錄時，也會刪掉它的保留音檔。
  - 要改天數或關掉保留，在 `.env` 加一行 `AUDIO_RETENTION_DAYS=天數`（0 是不自動刪除）或 `RETAIN_AUDIO=false`，再重新開啟 app。免安裝版的 `.env` 放在 `data\` 裡。
- **選 Gemini 時**：
  - 音檔與提示詞會上傳到 Google。
  - 金鑰所屬的專案沒有啟用計費時（免費層），Google 可能拿這些內容改善產品，也可能由人工審閱；條款要求不要送出敏感或個人資訊。
  - Settings 的 Gemini 卡片與轉錄頁都有這段說明，並連到 [Gemini API 條款](https://ai.google.dev/gemini-api/terms)。條款常改，以原文為準。
- **資料放在哪**：免安裝版的所有資料都在解壓資料夾的 `data\`。
  - `app.db`：任務紀錄、轉錄結果與 API 金鑰
  - `audio_store`：保留音檔
  - `temp_uploads`：上傳後還沒轉錄完的音檔
  - `vad_artifacts`：去靜音與切點預覽留下的音檔
  - `logs`：日誌檔，見下一項
  - `models`：本機模型的權重
- **日誌檔**：免安裝版把 app 的執行紀錄寫進 `data\logs`。
  - 每天一個檔（`app-年-月-日.log`），留最近 7 天；更早的在開啟 app 或跨日時刪除。
  - 回報問題時，附上出問題那天的檔案（見下一節[回報問題](#-回報問題)）。
  - 日誌檔不寫原檔名、提示詞與轉錄內容：上傳的音檔在電腦上改用隨機名稱，路徑裡的使用者資料夾寫成 `~`。附上之前也可以先打開看一遍。
- **診斷資訊**：回報問題時，在 Settings 頁的 About 卡片按「複製診斷資訊」，貼進 Issue。
  - 內容是版本、執行模式、作業系統、Python 與主要套件的版本、NVIDIA 驅動、顯卡、本機模型權重有沒有下載、ffmpeg，以及 data 資料夾所在磁碟的剩餘空間。
  - 不含原檔名、提示詞、轉錄內容、API 金鑰、路徑、電腦名稱與使用者名稱。按下後畫面會顯示複製了什麼，app 自己不會送出。
- **清掉個人資料**：
  - app 裡還沒有「清除所有資料」與「匯出所有資料」。
  - 要清掉個人資料，先關掉 app，再刪掉 `models` 以外的項目；刪掉 `models` 就要重新下載權重。
  - 換電腦時，把整個 `data\` 複製過去。

---

## 🐛 回報問題

app 不會自動回報錯誤，問題與建議都請到 GitHub [開一個 Issue](https://github.com/Wade0325/AI_translate/issues/new/choose)（要先登入 GitHub 帳號）；Settings 頁的 About 卡片也有連結。開 Issue 時選一個範本：

- **Bug 回報**：當機、錯誤訊息、按了沒反應、下載的檔案打不開。
- **轉錄品質**：錯字、漏掉或多出內容、說話者分錯、時間不準、出現簡體字。
- **功能建議**：想要新功能，或希望現有的功能改得更好用。

Issue 是公開的，任何人都看得到：

- 不要貼轉錄結果的內容（字幕、逐字稿），也不要附私人錄音，或看得到轉錄內容與檔名的截圖。
- 不要貼 API 金鑰。
- 回報 Bug 時，在 Settings 頁的 About 卡片按「複製診斷資訊」貼進 Issue（見上一節的「診斷資訊」）。日誌檔的位置見上一節的「日誌檔」，附上之前可以先打開看一遍。
- 任務失敗時，轉錄頁的檔案卡寫出原因與下一步，最下面一行是錯誤碼與細節（Tasks、History 頁滑過失敗原因也看得到）。回報時按那一行旁邊的複製圖示，連同錯誤碼一起貼進 Issue；細節是供應商或程式回報的原文，貼之前先看一遍。

---

## 🚧 已知限制

目前是測試版，下面這些還沒做，之後的版本處理：

- **長音檔的說話者編號**：本機一次能處理的長度約 70 分鐘，顯卡記憶體較小時更短；更長的音檔分段轉錄，每一段各自分離說話者，段與段之間的說話者編號可能對不上（例如前一段的 `[S0]` 到下一段變成 `[S1]`）。
- **介面語言**：介面中英夾雜，例如左側選單、頁面標題與部分按鈕是英文。
- **API 金鑰沒有加密**：Gemini 的 API 金鑰照原樣存在 `data\app.db`，不要把 `data\` 資料夾或 `app.db` 交給別人。
- **執行檔沒有數位簽章**：第一次執行 `AI_Translate.exe` 時，Windows 可能跳出 SmartScreen 的警告。

---

## 🔧 開發者指南

這一節給要改程式的人。一般使用者照上面的[安裝](#-安裝)用免安裝版即可，不需要 Docker。

### 執行模式

同一份程式碼有兩種執行模式：

| 執行模式 | 用途 | 資料庫與佇列 |
|------|------|------|
| **免安裝模式**（`APP_MODE=standalone`） | 免安裝版；開發時也可以直接用 venv 驗證 | SQLite＋行程內執行緒＋asyncio queue |
| **Docker 模式** | 開發；未來企業部署或自架線上服務的基礎 | PostgreSQL＋Redis＋Celery |

### 免安裝模式（不打包直接執行）

```powershell
$env:APP_MODE='standalone'
cd backend
.\.venv\Scripts\python.exe -m uvicorn main:app --port 8000
```

要看前端的畫面，先在 `frontend/` 執行 `npm run build`。帶環境變數 `AIT_DATA_DIR=<資料夾>` 可以把資料寫到別的資料夾，不動到既有的紀錄。

免安裝模式比 Docker 模式多三項限制（#16）：

- 只接受用 `127.0.0.1` 或 `localhost` 開的頁面與請求，用區網 IP 或其他主機名開會得到 400（`Invalid host header`）。
- 不接受跨來源的呼叫（沒有 CORS），WebSocket 也只接受同源。
- 沒有 `/docs` 與 `/redoc`，因為它們會向第三方的 CDN 要資源。要看 API 文件請用 Docker 模式；`/openapi.json` 兩種模式都有。

兩種模式共通的一點：轉錄、批次恢復與 Test Connection 的請求不能帶明文的 API 金鑰，帶了會被拒收。金鑰先在 Settings 存好，請求不帶金鑰即可。

### Docker 模式（開發用）

> ⚠️ Docker 模式只供開發，**不要開放到外網**：目前沒有帳號、權限，也沒有使用者之間的資料隔離（[ADR-0004](docs/adr/0004-ship-portable-build-only.md)）。`docker-compose.yml` 把 Postgres（5432）、Redis（6379，沒有密碼）、後端（8000）與前端（5173）的埠綁在主機的所有網路介面上，防火牆沒擋時，同一個網路的其他電腦也連得到；只在信任的網路上執行。

只需要 **Docker Desktop**——Postgres / Redis / FFmpeg 全都在容器內，不必自行安裝。

```bash
# 1. Clone 專案
git clone https://github.com/Wade0325/AI_translate.git
cd AI_translate

# 2. 建立環境變數：複製 .env.example 為 .env，填入 Postgres 帳密
copy .env.example .env

# 3. 一鍵 build + 啟動全部服務（Postgres / Redis / FastAPI / Celery / Vite）
.\dc.bat
```

> `dc.bat` / `dc.ps1` 是專案附的 Docker 管理腳本：自動偵測 `docker compose` v2/v1、自動帶 `--env-file .env`、跑前先檢查 Docker Desktop 是否啟動；零依賴、雙擊即可執行。

開啟瀏覽器：

- 🌐 前端：<http://localhost:5173>
- 📡 API 文件：<http://localhost:8000/docs>

> 要用 Gemini 時，到 Settings 頁面填入 Gemini API 金鑰。Docker 模式的本機轉錄在主機的 GPU worker 執行，見下面的「本機 GPU worker（Docker 模式）」。

常用指令（一鍵腳本）：

```bash
.\dc.bat                            # 第一次 / 改程式後：build + up -d
.\dc.bat start                      # 只是要執行（不 build、秒起，最常用）
.\dc.bat stop                       # 收工：停止但保留容器，下次 start 秒起
.\dc.bat restart celery-worker      # 手動重啟單一服務（例如 worker 卡住或停掉時）
.\dc.bat logs backend-service       # 看單一服務 log
.\dc.bat rebuild                    # --no-cache 重新 build 並重啟
.\dc.bat down                       # 停止並移除全部容器
.\dc.bat help                       # 看全部用法
```

程式碼以 volume 掛載：改後端（FastAPI `--reload`）與前端（Vite HMR）會自動熱更新；改 `backend/app/` 底下的 `.py` 檔時，celery-worker 容器裡的 worker 也會自動重啟（watchfiles），執行中的任務會因此中斷。主機的 GPU worker（`local_worker.bat`）不會自動重啟，改了程式要關掉視窗重開。celery-worker 的 worker 重啟時（自動重啟或手動 `.\dc.bat restart celery-worker`），還在等 Gemini 結果的批次，任務頁要等約 10 分鐘才會標成「已中斷」並給「恢復」：Celery 看不出 worker 被砍掉了，任務頁看的是看著批次的任務每次查詢時記下的時間。

若想直接用原生 docker compose 指令：

```bash
docker compose --env-file .env up --build -d
docker compose --env-file .env logs -f backend-service
docker compose --env-file .env down
```

#### 環境變數

於專案根目錄建立 `.env`（複製 `.env.example`）：

```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_DB=transcription_db
```

> 只需這三個變數。`DATABASE_URL` 與 `REDIS_HOST` 由 docker-compose 自動注入；**Gemini API 金鑰不放這裡**，而是啟動後在前端 Settings 頁面填入（儲存於資料庫）。

#### 本機 GPU worker（Docker 模式）

`backend\.venv` 同時是 Docker 模式主機 GPU worker（`local_worker.bat`）的執行環境，
依賴與免安裝版相同，以 `backend/requirements-standalone.txt` 為準。升級到預設 MOSS
模型的既有 venv 至少要補裝：

```powershell
.\backend\.venv\Scripts\python.exe -m pip install --no-deps av==18.1.0 "moss-transcribe-diarize @ https://github.com/OpenMOSS/MOSS-Transcribe-Diarize/archive/e3bdd93f8ad58418e04659818efd5fd87a0bc486.zip"
```

Docker 模式的設定頁沒有模型權重的卡片，Settings 頁的 Test Connection 也檢查不到主機端的 GPU worker。第一次用本機轉錄前，先在主機下載模型權重；
缺權重時，任務失敗的訊息也會指向這個指令。權重下載到和 `local_worker.bat` 相同的
`HF_HOME`，已下載的會跳過，中斷後再執行一次會接著下載：

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.provider.local.download_weights       # 預設模型所需
.\.venv\Scripts\python.exe -m app.provider.local.download_weights all   # 所有本機模型
```

### 專案架構

#### 系統流程（Docker 模式）

```
React Frontend  ──HTTP/WebSocket──▶  FastAPI  ──▶  Redis Pub/Sub
                                        │              │
                                        ▼              ▼
                                  PostgreSQL    Celery Worker
                                                      │
                                                      ▼
                                          Silero VAD + Gemini API
```

`Celery Worker` 完成後將結果發布到 `Redis Pub/Sub`，由 `FastAPI` 的 `ConnectionManager` 經 WebSocket 推送至前端。免安裝模式用 SQLite、行程內執行緒與 asyncio queue 取代 PostgreSQL、Redis 與 Celery。

#### 技術棧

| 層級 | 主要技術 |
|------|---------|
| 前端 | React 19、Vite 6、Ant Design 6、React Router 7 |
| 後端 | FastAPI 0.115、Celery 5.5（gevent）、SQLAlchemy 2.0、Pydantic 2 |
| AI | Google Gemini（`google-genai` 2.6）、Silero VAD 5.1、PyTorch 2.8（免安裝版）／2.7（Docker 模式） |
| 基礎設施 | SQLite（免安裝模式）；PostgreSQL 13、Redis 6、Docker Compose（Docker 模式） |

#### 目錄概覽

```
AI_translate/
├── backend/                 # FastAPI + Celery 服務
│   ├── app/
│   │   ├── api/             # REST / WebSocket 路由
│   │   ├── celery/          # 單檔 / 批次轉錄任務
│   │   ├── core/            # 設定、預設 Prompt（單一真實來源）
│   │   ├── database/        # ORM 模型、自動遷移
│   │   ├── provider/        # google（Gemini）與 local（MOSS／VibeVoice + Qwen3-ASR／ForcedAligner）客戶端
│   │   ├── services/        # silence_removal（去靜音）/ vad（找切點）/ transcription / output_format（輸出格式）/ calculator
│   │   └── websocket/       # ConnectionManager + Redis 監聽器
│   └── main.py
├── frontend/                # React 19 + Vite 6
│   └── src/
│       ├── pages/           # Transcribe / Result / Tasks / History / Billing / Settings
│       ├── components/      # UI 元件（含 ModelManager）
│       └── context/         # TranscriptionContext（單檔/批次/WS 狀態管理）
├── docker-compose.yml       # Docker 模式（5 個容器）
└── dc.bat / dc.ps1          # Docker 一鍵管理腳本
```

### 新增 AI 模型

供應商、模型與模型能力只寫在後端，前端從 `GET /api/v1/providers` 讀，不必改前端：

1. Gemini 的模型加進 `backend/app/provider/google/provider.py` 的 `MODELS`；本機的模型加進 `backend/app/provider/local/weights.py` 的 `MODEL_REPOS`，畫面上的名稱寫在 `backend/app/provider/local/provider.py` 的 `MODEL_LABELS`。清單的順序就是畫面的順序，第一個是預設。
2. 在 `backend/app/services/calculator/flows.py` 的 `MODEL_PRICES` 補上價格。
3. 若是新供應商，於 `backend/app/provider/{provider}/` 新增轉接器，並在 `backend/app/provider/registry.py` 登記。

### 修改預設 Prompt

`backend/app/core/default_prompt.py` 是 **唯一真實來源**，內含 `DEFAULT_PROMPT_TEMPLATE` 與 `build_prompt()`。修改此檔即同步生效於前後端。送出的提示詞是提示詞範本（設定頁存的，沒存過就是 `DEFAULT_PROMPT_TEMPLATE`）代入變數之後，空一行接上轉錄頁填的補充說明（照寫的送出，不代入變數）。

### 執行測試

```powershell
backend\.venv\Scripts\python.exe tools/check.py           # 依序跑 ruff → basedpyright → pytest → ESLint → tsc → vitest → Playwright → ratchet
backend\.venv\Scripts\python.exe tools/check.py pytest    # 只跑指定的項目
```

瀏覽器測試（`frontend/e2e/`）用 Playwright 的 Chromium 開轉錄頁、設定頁與歷史頁，後端與 WebSocket 都在測試裡 mock，不連資料庫、不呼叫任何供應商，也不需要網路。第一次跑之前在 `frontend/` 裝一次 Chromium：

```powershell
cd frontend
npx playwright install chromium   # 只要一次；Playwright 升版後再裝一次
npm run test:browser              # 或從 repo 根目錄 backend\.venv\Scripts\python.exe tools/check.py playwright
```

clone 之後執行一次下面這行，讓 git 在每次 commit 前跑快的檢查（lint、型別檢查與棘輪；測試交給 CI）。只影響開發用的 git checkout，免安裝版的使用者不需要：

```powershell
git config core.hooksPath .githooks
```

> `tools/check.py` 是唯一的檢查清單，CI 與 pre-commit 跑的也是它。Python 的檢查要先安裝 `backend/requirements-dev.txt`，ESLint、tsc、vitest 與 Playwright 要先在 `frontend/` 執行 `npm ci`，Playwright 另外要上面的 Chromium。型別檢查只擋新增的錯誤：既有的 Python 錯誤記在錯誤清單 `.basedpyright/baseline.json`，有錯的舊前端檔標了 `// @ts-nocheck`；ratchet 確認兩者都沒有比 `origin/main` 多。修掉清單裡的錯誤時，basedpyright 會自己改寫錯誤清單，記得把它一起 commit。`pytest.ini` 已設定 `pythonpath = backend`，測試可直接 `from app.api import ...` 匯入；測試自帶暫存的 SQLite 資料庫與 mock，不需 Postgres/Redis。

### 預覽去靜音與切點（開發者工具）

轉錄頁的檔案卡可以多一個「去靜音與切點預覽」按鈕：不轉錄，只顯示這個音檔的語音佔比、找到的有聲段與切點，並把剪好的音檔存進 `vad_artifacts/` 給你試聽。它會在資料夾留下音檔副本，一般使用者用不到，所以預設關閉。要用時加一行 `DEV_TOOLS=true`：Docker 模式加在專案根目錄的 `.env`，再執行一次 `.\dc.bat` 重建容器；免安裝版加在解壓資料夾的 `data\` 裡的 `.env`，再重新開啟應用程式。

### 評測轉錄品質

`backend\.venv\Scripts\python.exe -m tools.eval transcribe ...` 用正式的轉錄路徑轉錄一個音檔，輸出轉錄結果與記下環境和耗時的 manifest；`backend\.venv\Scripts\python.exe -m tools.eval eval ...` 拿轉錄結果和評測集的標準答案比對，算錯字率與說話者歸屬。標準答案留在 repo 外的研究區。用法見 [`tools/eval/README.md`](tools/eval/README.md)。

### 建置 Windows 免安裝發布包

```powershell
.\build_release.ps1 -Version v1.2.3
```

產出 `build\AI_Translate-v1.2.3-win64.zip`（約 150 MB —— Python 依賴不進 zip，
由使用者首次啟動時以隨包 `uv` 依 `backend/requirements-standalone.txt` 自動下載）。
推 `v*` tag 時 GitHub Actions（`.github/workflows/release.yml`）會先跑一次完整的 CI，通過後自動建置並發布 Release。

---

## 📝 授權

本專案採用 [Apache License 2.0](LICENSE)，理由見 [ADR 0006](docs/adr/0006-license-apache-2.md)。

---

<div align="center">
  <p>Made with ❤️ by Wade</p>
  <p>
    <a href="https://github.com/Wade0325/AI_translate">⭐ Star</a> •
    <a href="https://github.com/Wade0325/AI_translate/issues">🐛 Issues</a> •
    <a href="https://github.com/Wade0325/AI_translate/pulls">✨ PR</a>
  </p>
</div>
