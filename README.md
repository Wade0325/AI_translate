<div align="center">
  <h1>🎙️ AI Voice Transcription</h1>
  <p><strong>AI 驅動的語音轉錄與字幕生成工具</strong></p>
  <p>上傳音訊／視頻 → 自動偵測語音 → 由 Gemini 轉錄並輸出多格式字幕</p>

  ![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
  ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
  ![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
  ![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)
</div>

---

## 📖 目錄

- [✨ 功能特色](#-功能特色)
- [🚀 快速開始](#-快速開始)
- [📘 使用教學](#-使用教學)
- [⚙️ 環境變數](#️-環境變數)
- [🏗️ 專案架構](#️-專案架構)
- [🔧 開發指南](#-開發指南)
- [📝 授權](#-授權)

---

## ✨ 功能特色

### 🎯 核心能力

- **🤖 高品質 AI 轉錄**：整合 Google Gemini 多模態模型，支援 `gemini-3.5-flash` / `gemini-2.5-flash` 等。
- **🖥️ 本地模型轉錄**：VibeVoice-ASR 說話者分離 + Qwen3-ASR 轉錄（主機 GPU 執行，零 API 費用；以 `local_worker.bat` 啟動）。
- **🗣️ 智能 VAD 切片**：使用 Silero VAD 自動移除靜默段落，提升精度並節省 Token。
- **⏱️ 毫秒級時間戳**：輸出帶 `[mm:ss.xxx]` 精確時間戳的逐字稿。
- **📦 多格式匯出**：LRC、SRT、VTT、TXT 一鍵下載；批量任務支援 ZIP 打包。
- **📤 多來源輸入**：支援 MP3 / WAV / FLAC / M4A / MP4 / WebM 等音訊與視頻格式。

### 🚀 進階功能

| 功能 | 說明 |
|------|------|
| 📚 **批次轉錄** | 採用 Gemini Batch API，**費用為標準 API 的 50%**，適合大量檔案非同步處理 |
| 🔄 **任務恢復** | 重啟服務後可自動恢復未完成的批次任務（無需重新上傳） |
| 👥 **多人對話模式** | 自動以 `Speaker 1:` / `Speaker 2:` 標記不同說話者 |
| 📝 **自訂 Prompt** | 自定指令，搭配術語表、特殊標記、ASMR 聲響描述等 |
| 📊 **即時進度** | WebSocket 推送 VAD → 上傳 → 轉錄 → 完成 各階段狀態 |
| 💰 **成本追蹤** | 自動計算每次任務的 Token 用量與費用，提供儀表板與計費頁查詢 |
| 🕘 **歷史紀錄** | 所有轉錄結果儲存於 PostgreSQL，可隨時回查與重新下載 |

---

## 🚀 快速開始

兩種安裝方式，擇一即可：

| 方式 | 適合對象 | 需要什麼 |
|------|---------|---------|
| **A. Windows 免安裝版**（下載 zip） | 一般使用者 | 什麼都不用裝，解壓雙擊即用 |
| **B. Docker 部署**（clone 專案） | 開發者 / 伺服器部署 | Docker Desktop |

### 方式 A — Windows 免安裝版（推薦一般使用者）

1. 到 [**Releases**](https://github.com/Wade0325/AI_translate/releases) 下載最新的 `AI_Translate-vX.Y.Z-win64.zip`
2. 解壓到任意位置（建議路徑不含中文與空白）
3. 雙擊 **`AI_Translate.exe`**
   - 首次啟動會自動下載執行環境（約 3.5 GB，含 PyTorch），中斷可續傳
   - 就緒後自動開啟瀏覽器；關閉黑色視窗即停止程式
4. 在 **⚙️ Settings** 頁填入 [Gemini API Key](https://aistudio.google.com/apikey) 即可轉錄
5. 要用 **Local 本機 GPU 轉錄**（零 API 費用，需 NVIDIA GPU）：在 Settings 頁的
   Local Models 卡片下載模型權重（約 25 GB，總磁碟需求約 35 GB）

> 所有資料（資料庫、模型權重）都在解壓資料夾的 `data\` 內；升級新版時把舊版 `data\` 複製過來即可保留紀錄。

### 方式 B — Docker 部署（開發者）

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

> 首次啟動後，到左側 **⚙️ 設定 (Settings)** 頁面填入 Google Gemini API 金鑰即可開始使用。

常用指令（一鍵腳本）：

```bash
.\dc.bat                            # 第一次 / 改程式後：build + up -d
.\dc.bat start                      # 只是要執行（不 build、秒起，最常用）
.\dc.bat stop                       # 收工：停止但保留容器，下次 start 秒起
.\dc.bat restart celery-worker      # 改 celery 程式後重啟
.\dc.bat logs backend-service       # 看單一服務 log
.\dc.bat rebuild                    # --no-cache 重新 build 並重啟
.\dc.bat down                       # 停止並移除全部容器
.\dc.bat help                       # 看全部用法
```

程式碼以 volume 掛載：改後端（FastAPI `--reload`）與前端（Vite HMR）會自動熱更新；改 celery 需 `.\dc.bat restart celery-worker`。

若想直接用原生 docker compose 指令：

```bash
docker compose --env-file .env up --build -d
docker compose --env-file .env logs -f backend-service
docker compose --env-file .env down
```

---

## 📘 使用教學

### 步驟 1️⃣ — 設定 API 金鑰

1. 點擊左側選單 **⚙️ 設定 (Settings)**。
2. 選擇服務商 **Google**，貼上你的 [Gemini API Key](https://aistudio.google.com/apikey)。
3. 選擇預設模型（推薦 `gemini-2.5-flash`，速度與品質平衡）並儲存。

### 步驟 2️⃣ — 上傳並設定轉錄參數

進入 **🎙️ 轉錄 (Transcribe)** 頁面：

1. **上傳檔案**：拖曳或點擊上傳音訊／視頻（可一次選擇多個檔案進入批次模式）。
2. **選擇來源語言**：日文 / 英文 / 繁體中文。
3. **（選填）多人對話模式**：開啟後自動標記 `Speaker 1` / `Speaker 2`。
4. **（選填）自訂 Prompt**：可加入術語表、額外指令；不填則使用系統預設模板。

### 步驟 3️⃣ — 開始轉錄

- **單檔轉錄**：點擊「開始轉錄」，右側即時顯示 VAD → 上傳 → 轉錄 → 完成的進度。
- **批次轉錄**：處理模式選擇「Batch（半價）」後送出，可關閉視窗稍後在 **📋 任務 (Tasks)** 頁面查看；批次任務即使重啟後端也會自動恢復。

### 步驟 4️⃣ — 檢視與下載結果

到 **📄 結果 (Result)** 頁面：

- 預覽逐字稿與時間戳。
- 下載 `.lrc` / `.srt` / `.vtt` / `.txt`（批次任務可一鍵 ZIP 下載全部）。

### 步驟 5️⃣ — 追蹤紀錄與費用

- **🕘 歷史 (History)**：列出所有完成的任務，可重新下載字幕。
- **💰 計費 (Billing)**：依日期、模型查詢 Token 用量與成本。
- **📊 儀表板 (Dashboard)**：總覽近期使用統計。

> 💡 **省錢技巧**：非急件大量檔案請使用「批次轉錄」，費用直接 5 折。

---

## ⚙️ 環境變數

於專案根目錄建立 `.env`（複製 `.env.example`）：

```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_DB=transcription_db
```

> 只需這三個變數。`DATABASE_URL` 與 `REDIS_HOST` 由 docker-compose 自動注入；**Google Gemini API 金鑰不放這裡**，而是啟動後在前端「設定 (Settings)」頁面填入（儲存於資料庫）。

---

## 🏗️ 專案架構

### 系統流程

```
React Frontend  ──HTTP/WebSocket──▶  FastAPI  ──▶  Redis Pub/Sub
                                        │              │
                                        ▼              ▼
                                  PostgreSQL    Celery Worker
                                                      │
                                                      ▼
                                          Silero VAD + Gemini API
```

`Celery Worker` 完成後將結果發布到 `Redis Pub/Sub`，由 `FastAPI` 的 `ConnectionManager` 經 WebSocket 推送至前端。

### 技術棧

| 層級 | 主要技術 |
|------|---------|
| 前端 | React 19、Vite 6、Ant Design 6、React Router 7 |
| 後端 | FastAPI 0.115、Celery 5.5（gevent）、SQLAlchemy 2.0、Pydantic 2 |
| AI | Google Gemini（`google-genai` ≥ 1.64）、Silero VAD 5.1、PyTorch 2.7 |
| 基礎設施 | PostgreSQL 13、Redis 6、Docker Compose |

### 目錄概覽

```
AI_translate/
├── backend/                 # FastAPI + Celery 服務
│   ├── app/
│   │   ├── api/             # REST / WebSocket 路由
│   │   ├── celery/          # 單檔 / 批次轉錄任務
│   │   ├── core/            # 設定、預設 Prompt（單一真實來源）
│   │   ├── database/        # ORM 模型、自動遷移
│   │   ├── provider/        # google（Gemini）與 local（VibeVoice + Qwen3-ASR）客戶端
│   │   ├── services/        # vad / transcription / converter / calculator
│   │   └── websocket/       # ConnectionManager + Redis 監聽器
│   └── main.py
├── frontend/                # React 19 + Vite 6
│   └── src/
│       ├── pages/           # Dashboard / Transcribe / Result / Tasks / History / Billing / Settings
│       ├── components/      # UI 元件（含 ModelManager）
│       └── context/         # TranscriptionContext（單檔/批次/WS 狀態管理）
├── docker-compose.yml       # 本機單一環境（5 個容器）
└── dc.bat / dc.ps1          # Docker 一鍵管理腳本
```

---

## 🔧 開發指南

### 新增 AI 模型

1. 在 `frontend/src/constants/modelConfig.js` 新增選項：

```javascript
export const modelOptions = {
  Google: [
    { value: 'gemini-2.5-flash', label: 'gemini-2.5-flash' },
    { value: 'gemini-2.5-pro', label: 'gemini-2.5-pro' },
  ],
};
```

2. 若是新服務商，於 `backend/app/provider/{provider}/` 新增對應客戶端模組。

### 修改預設 Prompt

`backend/app/core/default_prompt.py` 是 **唯一真實來源**，內含 `DEFAULT_PROMPT_TEMPLATE` 與 `build_prompt()`。修改此檔即同步生效於前後端。

### 執行測試

```bash
pytest tests/ -v
```

> 從專案根目錄執行。`pytest.ini` 已設定 `pythonpath = backend`，測試可直接 `from app.api import ...` 匯入；測試自帶 SQLite in-memory 與 mock，不需 Postgres/Redis。

### 建置 Windows 免安裝發布包

```powershell
.\build_release.ps1 -Version v1.2.3
```

產出 `build\AI_Translate-v1.2.3-win64.zip`（約 150 MB —— Python 依賴不進 zip，
由使用者首次啟動時以隨包 `uv` 依 `backend/requirements-standalone.txt` 自動下載）。
推 `v*` tag 時 GitHub Actions（`.github/workflows/release.yml`）會自動建置並發布 Release。

單機模式的程式碼開關是 `APP_MODE=standalone` 環境變數：SQLite + 行程內執行緒
+ asyncio queue 取代 Postgres / Redis / Celery，同一份程式碼與 Docker 模式並存。
開發時可直接用 venv 驗證，不需打包：

```powershell
$env:APP_MODE='standalone'
cd backend
.\.venv\Scripts\python.exe -m uvicorn main:app --port 8000
```

---

## 📝 授權

本專案採用 MIT License。

---

<div align="center">
  <p>Made with ❤️ by Wade</p>
  <p>
    <a href="https://github.com/Wade0325/AI_translate">⭐ Star</a> •
    <a href="https://github.com/Wade0325/AI_translate/issues">🐛 Issues</a> •
    <a href="https://github.com/Wade0325/AI_translate/pulls">✨ PR</a>
  </p>
</div>
