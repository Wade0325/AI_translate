# 🎙️ AI Voice Transcription — 專案架構說明書

> **版本**: 1.0.0  
> **最後更新**: 2026-02-26  
> **用途**: 提供給 AI IDE（如 Antigravity、Cursor、Windsurf）作為開發輔助的完整專案上下文  

---

## 1. 專案概述

**AI Voice Transcription** 是一個 AI 驅動的語音轉錄與字幕生成工具。核心功能為將音訊/視頻檔案轉換成帶有精確時間戳的多格式字幕檔案（LRC、SRT、VTT、TXT）。

### 1.1 核心功能
- **多格式上傳**：支援 MP3、WAV、FLAC、M4A、MP4、WebM 等音訊/視頻格式
- **YouTube 支援**：直接貼上 YouTube 連結下載並轉錄（透過 yt-dlp）
- **智能語音偵測 (VAD)**：使用 Silero VAD 自動偵測語音活動區段，移除靜音提升轉錄精確度
- **AI 語音轉錄**：整合 Google Gemini 多模態模型進行高品質語音轉文字
- **自動翻譯**：支援轉錄後自動翻譯至目標語言
- **精確時間戳**：生成毫秒級時間戳的字幕檔案
- **文稿對齊**：附加原始文稿，AI 將為其配上精確時間戳
- **自訂 Prompt**：完全自訂轉錄指令，支援特定術語和說話者標記
- **批次處理 (Batch API)**：使用 Gemini Batch API 以 50% 費用進行批次轉錄
- **即時進度推送**：WebSocket 即時推送處理進度與狀態
- **費用估算**：自動計算 API Token 用量與成本
- **歷史紀錄**：查詢過去的轉錄任務紀錄（分頁、篩選、統計）
- **批次恢復**：Docker 容器重啟後可恢復未完成的批次任務

### 1.2 支援語言
- 繁體中文（台灣）`zh-TW`
- 英文（美國）`en-US`
- 日文（日本）`ja-JP`
- 可透過自訂 Prompt 擴展更多語言

---

## 2. 技術棧

### 2.1 前端
| 套件 | 版本 | 說明 |
|------|------|------|
| React | ^18.2.0 | 使用者介面框架（使用函數式元件 + Hooks） |
| Vite | ^5.4.19 | 前端建構工具（HMR、Proxy） |
| Ant Design (antd) | ^5.17.0 | UI 元件庫 |
| @ant-design/icons | ^5.3.7 | Ant Design 圖示 |
| Axios | ^1.9.0 | HTTP 客戶端 |
| JSZip | ^3.10.1 | 批量下載時的 ZIP 壓縮 |
| ESLint | ^8.57.0 | 程式碼品質檢查 |
| @vitejs/plugin-react | ^4.2.1 | Vite 的 React 插件 |

### 2.2 後端
| 套件 | 版本 | 說明 |
|------|------|------|
| Python | 3.11 | 程式語言（Docker image: python:3.11-slim） |
| FastAPI | 0.115.12 | Web 框架（含 WebSocket 支援） |
| Uvicorn | 0.34.2 | ASGI 伺服器 (standard extras) |
| Pydantic | 2.11.4 | 資料驗證與序列化 |
| pydantic-settings | latest | 環境變數管理 |
| Celery | 5.5.2 | 分散式任務佇列 |
| Redis | 6.0.0 | Python Redis 客戶端（Celery broker + Pub/Sub） |
| SQLAlchemy | 2.0.31 | ORM 資料庫存取 |
| psycopg2-binary | 2.9.9 | PostgreSQL 資料庫驅動 |
| python-dotenv | 1.1.0 | 環境變數載入 |
| python-multipart | latest | 檔案上傳支援 |
| gevent | 25.4.2 | Celery worker 的協程池（Windows 相容） |
| langdetect | latest | 語言偵測 |

### 2.3 AI / 機器學習
| 套件 | 版本 | 說明 |
|------|------|------|
| google-genai | ≥1.64.0 | Google Gemini API 客戶端（需 ≥1.64.0 支援 Batch API inline requests） |
| google-api-core | latest | Google API 基礎核心 |
| openai | 1.84.0 | OpenAI API 客戶端（預留，目前未使用） |
| PyTorch (torch) | 2.7.0 | 深度學習框架（僅用於 VAD 模型推論） |
| torchaudio | 2.7.0 | 音訊處理（配合 Silero VAD） |
| silero-vad | 5.1.2 | 語音活動偵測模型 |
| soundfile | 0.12.1 | 音訊檔案讀寫 |
| yt-dlp | 2025.6.25 | YouTube 影片/音訊下載 |
| pika | 1.3.2 | RabbitMQ 客戶端（已安裝，目前未使用） |

### 2.4 基礎設施
| 技術 | 版本 | 說明 |
|------|------|------|
| PostgreSQL | 13-alpine | 關聯式資料庫（Docker image） |
| Redis | 6-alpine | Celery 訊息佇列 + WebSocket Pub/Sub（Docker image） |
| Docker | 20.10+ | 容器化部署 |
| Docker Compose | v2.0+ | 多容器編排 |
| Nginx | alpine | 前端靜態檔案伺服器 + 反向代理（生產環境，Docker image） |
| FFmpeg | apt-get | 音訊格式轉換與 ffprobe 取時長（在 backend Dockerfile 中安裝） |
| Node.js | 18-alpine | 前端開發環境（Docker image） |

---

## 3. 系統架構

### 3.1 架構總覽

```mermaid
graph TB
    subgraph Frontend ["前端 (React + Vite)"]
        UI[React UI<br/>Ant Design]
        WS_Client[WebSocket Client]
        HTTP_Client["Axios HTTP Client"]
    end

    subgraph Nginx_Prod ["Nginx (生產環境)"]
        NGINX[靜態檔案 + 反向代理]
    end

    subgraph Backend ["後端 (FastAPI)"]
        API_Upload["POST /api/v1/upload"]
        API_WS["WS /api/v1/ws/{file_uid}"]
        API_Batch_WS["WS /api/v1/batch/ws/{batch_id}"]
        API_Model["API /api/v1/setting/models"]
        API_History["API /api/v1/history"]
        API_Batch_REST["API /api/v1/batch"]
        WS_Manager["WebSocket Manager<br/>(ConnectionManager)"]
    end

    subgraph Workers ["Celery Workers"]
        Task_Single["transcribe_media_task"]
        Task_Batch["batch_transcribe_task"]
        Task_Recover["batch_recover_task"]
    end

    subgraph Services ["服務層"]
        VAD["VAD Service<br/>(Silero VAD)"]
        Transcription["Transcription Service"]
        Converter["Converter Service<br/>(LRC→SRT/VTT/TXT)"]
        Calculator["Calculator Service<br/>(費用計算)"]
        Translator["Translator Service"]
    end

    subgraph External ["外部服務"]
        Gemini["Google Gemini API"]
    end

    subgraph Data ["資料層"]
        PG[(PostgreSQL)]
        REDIS[(Redis)]
    end

    UI --> HTTP_Client
    UI --> WS_Client
    HTTP_Client --> NGINX
    WS_Client --> NGINX
    NGINX --> API_Upload
    NGINX --> API_WS
    NGINX --> API_Batch_WS
    NGINX --> API_Model
    NGINX --> API_History
    NGINX --> API_Batch_REST

    API_WS --> WS_Manager
    API_Batch_WS --> WS_Manager
    WS_Manager --> REDIS

    API_WS --> Task_Single
    API_Batch_WS --> Task_Batch
    API_Batch_REST --> Task_Recover

    Task_Single --> VAD
    Task_Single --> Transcription
    Task_Single --> Converter
    Task_Single --> Calculator
    Task_Batch --> Transcription
    Task_Batch --> Converter
    Task_Batch --> Calculator
    Task_Batch --> Translator

    Transcription --> Gemini
    Translator --> Gemini
    Task_Batch --> Gemini

    Task_Single --> REDIS
    Task_Batch --> REDIS
    Task_Recover --> REDIS

    Task_Single --> PG
    Task_Batch --> PG
    Task_Recover --> PG
    API_Model --> PG
    API_History --> PG
    API_Batch_REST --> PG
```

### 3.2 資料流程

#### 單檔轉錄流程
```
前端上傳檔案 → POST /api/v1/upload → 儲存至 temp_uploads/
前端建立 WebSocket → WS /api/v1/ws/{file_uid}
前端發送轉錄請求 JSON → API 層解析並建立 Celery 任務
Celery Worker 執行：
  1. VAD 靜音移除 → 建立純語音檔案
  2. 上傳至 Gemini File API
  3. 計算 Token 數量
  4. 呼叫 Gemini 轉錄 → 取得 LRC 格式結果
  5. 時間戳重映射回原始時間軸
  6. 格式轉換 (LRC → SRT/VTT/TXT)
  7. 費用計算
  8. 寫入 TranscriptionLog 資料庫
  9. 透過 Redis Pub/Sub 推送結果至 WebSocket
前端接收結果 → 顯示字幕 + 下載選項
```

#### 批次轉錄流程
```
前端上傳多個檔案 → 各自 POST /api/v1/upload
前端建立 WebSocket → WS /api/v1/batch/ws/{batch_id}
前端發送批次請求 JSON → API 層解析並建立 Celery 任務
Celery Worker 執行：
  1. 建立 BatchJob 資料庫紀錄
  2. 逐一上傳至 Gemini File API
  3. 建立 Gemini Batch API 任務（inline requests）
  4. 更新 DB 狀態為 BATCH_SUBMITTED
  5. 輪詢 Gemini 任務直到完成
  6. 逐一處理結果：格式轉換、翻譯、費用計算
  7. 結果存入 BatchJob.results_json
  8. 透過 Redis Pub/Sub 推送個別檔案與整體批次結果
```

#### 批次恢復流程（Docker 重啟後）
```
前端呼叫 GET /api/v1/batch/pending → 取得未完成的批次任務列表
前端呼叫 POST /api/v1/batch/{batch_id}/recover → 
  - 若 DB 有 results_json → 直接從 DB 回傳結果
  - 若無 → 派送 batch_recover_task 至 Celery → 從 Gemini 取得結果
```

---

## 4. 目錄結構

```
AI_translate/
├── .agents/                          # AI IDE 設定
│   └── PROJECT_ARCHITECTURE.md       # 本說明書
├── .cursor/                          # Cursor IDE 設定
├── .env.prod                         # Docker 生產環境變數（POSTGRES_USER/PASSWORD/DB）
├── .dockerignore                     # Docker build 忽略規則
├── .gitignore                        # Git 忽略規則
│
├── backend/                          # 後端服務（FastAPI + Celery）
│   ├── .env                          # 本地開發環境變數（不進版控）
│   ├── .env.example                  # 環境變數範本
│   ├── Dockerfile                    # 後端 Docker 映像（python:3.11-slim + ffmpeg）
│   ├── .dockerignore                 # 後端 Docker build 忽略規則
│   ├── requirements.txt              # Python 依賴清單
│   ├── main.py                       # FastAPI 應用程式入口點
│   ├── __init__.py
│   │
│   └── app/                          # 應用程式核心
│       ├── __init__.py
│       ├── core/                     # 核心設定
│       │   ├── __init__.py
│       │   ├── config.py             # 集中設定管理（Pydantic Settings）
│       │   └── default_prompt.py     # 系統預設 Prompt 模板
│       │
│       ├── api/                      # API 路由層
│       │   ├── __init__.py
│       │   ├── upload.py             # POST /api/v1/upload — 檔案上傳
│       │   ├── transcription.py      # WS /api/v1/ws/{file_uid} — 單檔轉錄
│       │   ├── batch.py              # WS + REST /api/v1/batch/ — 批次轉錄與恢復
│       │   ├── model_manager.py      # CRUD /api/v1/setting/models — 模型設定
│       │   └── history.py            # CRUD /api/v1/history — 歷史紀錄
│       │
│       ├── celery/                   # Celery 非同步任務
│       │   ├── __init__.py
│       │   ├── celery.py             # Celery app 實例與設定
│       │   ├── models.py             # Pydantic 任務參數模型
│       │   ├── task.py               # 單檔轉錄 Celery 任務
│       │   └── batch_task.py         # 批次轉錄 + 恢復 Celery 任務
│       │
│       ├── database/                 # 資料庫層
│       │   ├── __init__.py
│       │   ├── models.py             # SQLAlchemy ORM 模型定義
│       │   └── session.py            # 資料庫引擎、Session、初始化、自動遷移
│       │
│       ├── repositories/             # 資料存取層（Repository Pattern）
│       │   ├── model_manager_repository.py   # 模型設定 CRUD
│       │   ├── transcription_log_repository.py # 轉錄日誌 CRUD
│       │   ├── batch_job_repository.py        # 批次任務 CRUD
│       │   └── history_repository.py          # 歷史紀錄查詢（分頁、篩選、統計）
│       │
│       ├── schemas/                  # Pydantic API 請求/回應模型
│       │   └── schemas.py            # 所有 API Schema 定義
│       │
│       ├── services/                 # 業務邏輯服務層
│       │   ├── __init__.py
│       │   ├── vad/                  # 語音活動偵測服務
│       │   │   ├── __init__.py
│       │   │   ├── models.py         # VAD 資料模型
│       │   │   ├── service.py        # VADService 類別（模型管理、語音偵測）
│       │   │   └── flows.py          # VAD 處理流程（提取語音片段、分割音訊）
│       │   │
│       │   ├── transcription/        # 轉錄服務
│       │   │   ├── __init__.py
│       │   │   ├── models.py         # 轉錄結果資料模型
│       │   │   └── flows.py          # TranscriptionTask 類別（主轉錄流程）
│       │   │
│       │   ├── converter/            # 格式轉換服務
│       │   │   ├── __init__.py
│       │   │   ├── models.py         # SubtitleFormats 資料模型
│       │   │   └── service.py        # LRC → SRT/VTT/TXT 轉換
│       │   │
│       │   ├── calculator/           # 費用計算服務
│       │   │   ├── __init__.py
│       │   │   ├── models.py         # 計費資料模型
│       │   │   ├── service.py        # CalculatorService 類別
│       │   │   └── flows.py          # 價格計算邏輯
│       │   │
│       │   └── translator/           # 翻譯服務
│       │       ├── __init__.py
│       │       ├── models.py         # 翻譯結果資料模型
│       │       └── flows.py          # 翻譯流程（呼叫 Gemini 翻譯）
│       │
│       ├── provider/                 # AI 服務提供者
│       │   └── google/
│       │       └── gemini.py         # GeminiClient + 所有 Gemini API 互動函式
│       │
│       ├── websocket/                # WebSocket 管理
│       │   └── manager.py            # ConnectionManager（連線管理 + Redis 監聽）
│       │
│       └── utils/                    # 共用工具
│           ├── __init__.py
│           ├── audio.py              # 音訊工具（ffprobe 取時長、MIME 類型、WAV 轉換）
│           └── logger.py             # 統一 Logger 設定（自訂格式、路徑對齊）
│
├── frontend/                         # 前端應用（React + Vite）
│   ├── Dockerfile                    # 多階段建構（node:18-alpine build → nginx:alpine）
│   ├── nginx.conf                    # Nginx 設定（靜態檔案 + API/WS 反向代理）
│   ├── .env.development              # 開發環境變數
│   ├── .gitignore
│   ├── package.json                  # NPM 依賴與腳本
│   ├── package-lock.json
│   ├── vite.config.js                # Vite 設定（React 插件、API Proxy）
│   ├── eslint.config.js              # ESLint 設定
│   ├── index.html                    # HTML 入口
│   │
│   └── src/                          # 前端原始碼
│       ├── main.jsx                  # React 應用程式入口（ReactDOM.createRoot）
│       ├── App.jsx                   # 根元件（Layout、導覽列、頁面切換）
│       ├── index.css                 # 全域樣式
│       │
│       ├── components/               # React 元件
│       │   ├── ModelManager.jsx      # 模型設定元件（API Key、模型選擇、Prompt 編輯）
│       │   │                         #   提供 ModelManagerProvider Context
│       │   ├── FileManager.jsx       # 檔案管理元件（上傳、YouTube URL 輸入）
│       │   ├── Transcription.jsx     # 轉錄主頁面元件
│       │   ├── History.jsx           # 歷史紀錄頁面（分頁表格、統計總覽）
│       │   └── Transcription/        # 轉錄子元件
│       │       ├── UploadArea.jsx    # 上傳區域
│       │       ├── FileQueueHeader.jsx # 檔案佇列標題
│       │       ├── FileQueueTable.jsx  # 檔案佇列表格（狀態、預覽、下載）
│       │       └── QueueSummary.jsx    # 佇列摘要（費用、進度統計）
│       │
│       ├── constants/                # 常數設定
│       │   └── modelConfig.js        # 模型選項清單 + findProviderForModel 輔助函式
│       │
│       └── context/                  # React Context
│           └── TranscriptionContext.jsx  # 核心狀態管理（776 行）
│                                         # - 檔案上傳狀態
│                                         # - WebSocket 連線管理
│                                         # - 單檔/批次轉錄控制
│                                         # - 結果預覽/下載
│                                         # - 批次恢復 (pending + recover + polling)
│
├── tests/                            # 測試檔案
│   ├── __init__.py
│   ├── conftest.py                   # Pytest fixtures
│   ├── gemini_test.py                # Gemini API 整合測試
│   ├── test_model_manager_api.py     # 模型管理 API 測試
│   ├── test_transcription_api.py     # 轉錄 API 測試
│   ├── audio_input/                  # 測試用音訊輸入
│   └── audio_output/                 # 測試用音訊輸出
│
├── migrations/                       # 資料庫遷移（目前未使用 Alembic，由 session.py 自動遷移）
├── temp_uploads/                     # 臨時上傳目錄（不進版控）
│
├── docker-compose.dev.yml            # 開發環境 Docker Compose
├── docker-compose.prod.yml           # 生產環境 Docker Compose
├── Startup.bat                       # Windows 本地開發快速啟動腳本
├── React_Startup.bat                 # Windows React 快速啟動腳本
├── pytest.ini                        # Pytest 設定
├── package.json                      # 根目錄 package.json（空，僅用於 node_modules）
└── README.md                         # 專案說明文件
```

---

## 5. 後端詳細架構

### 5.1 應用程式入口 — `main.py`

FastAPI 應用程式的啟動點，負責：
- **Lifespan 管理**：`asynccontextmanager` 控制啟動/關閉生命週期
- **資料庫初始化**：呼叫 `init_db()` 建立資料表和預設資料
- **WebSocket Redis 監聽器**：啟動背景 `asyncio.Task` 監聽 Redis Pub/Sub
- **VAD 預載**：應用程式啟動時預先載入 Silero VAD 模型
- **路由註冊**：5 個路由器 (transcription, model_manager, upload, batch, history)
- **CORS 中介軟體**：允許所有來源 (`["*"]`)

### 5.2 核心設定 — `app/core/`

#### `config.py` — Settings 類別
使用 `pydantic-settings` 集中管理所有環境設定：
- **優先順序**：環境變數 > `.env` 檔案 > 預設值
- **單例模式**：`@lru_cache` 確保每個進程只建立一次 `Settings` 實例
- **Key Properties**：
  - `sync_database_url` → PostgreSQL 連線 URL
  - `async_database_url` → 非同步版本（`postgresql+asyncpg://`）
  - `redis_url` → `redis://{host}:{port}/0`
  - `celery_backend_url` → `db+postgresql://` 格式
- **可設定項**：
  - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_SERVER`, `POSTGRES_PORT`, `POSTGRES_DB`
  - `DATABASE_URL`（可覆蓋自動組裝的 URL）
  - `REDIS_HOST`, `REDIS_PORT`
  - `CELERY_TIMEZONE` (預設 Asia/Taipei), `CELERY_RESULT_EXPIRES` (預設 86400)
  - `TEMP_UPLOADS_DIR` (預設 "temp_uploads")
  - `DB_POOL_SIZE` (預設 10), `DB_MAX_OVERFLOW` (預設 20)

#### `default_prompt.py` — Prompt 模板
系統預設 Prompt 的唯一真實來源 (Single Source of Truth)：
- **`DEFAULT_PROMPT_TEMPLATE`**：可填入 `{source_lang}`, `{speaker_instruction}`, `{translate_instruction}`
- **`LANG_MAP`**：語言代碼 → 顯示名稱（`zh-TW` → `繁體中文`）
- **`build_prompt()`**：根據參數動態組裝最終 Prompt

### 5.3 API 路由層 — `app/api/`

#### `upload.py`
| 端點 | 方法 | 說明 |
|------|------|------|
| `/api/v1/upload` | POST | 上傳音訊/視頻檔案至 `temp_uploads/` |

- 支援 MIME 類型白名單驗證
- 檔名衝突時自動加編號 `file(1).mp3`
- 回傳 `{ filename, message }`

#### `transcription.py`
| 端點 | 方法 | 說明 |
|------|------|------|
| `/api/v1/ws/{file_uid}` | WebSocket | 單檔轉錄即時進度 |

- WebSocket 連線後，前端發送 JSON (`WebSocketTranscriptionRequest`)
- 在獨立執行緒中啟動 Celery 任務 (`run_in_threadpool`)
- 保持連線開啟接收 Redis Pub/Sub 推送的進度

#### `batch.py`
| 端點 | 方法 | 說明 |
|------|------|------|
| `/api/v1/batch/ws/{batch_id}` | WebSocket | 批次轉錄即時進度 |
| `/api/v1/batch/pending` | GET | 查詢未完成的批次任務 |
| `/api/v1/batch/{batch_id}/recover` | POST | 恢復批次任務結果 |

- WebSocket 端點與單檔類似，但所有檔案共用一個 `batch_id`
- 恢復邏輯：先查 DB → 有結果直接回傳，否則派送 Celery 恢復任務

#### `model_manager.py`
| 端點 | 方法 | 說明 |
|------|------|------|
| `/api/v1/setting/models` | POST | 儲存模型設定 (provider, apiKeys, model, prompt) |
| `/api/v1/setting/models/{provider}` | GET | 取得特定提供者的模型設定 |
| `/api/v1/setting/test` | POST | 測試 API 連線 |
| `/api/v1/setting/default-prompt` | GET | 取得系統預設 Prompt 模板 |

- API Keys 以 JSON 字串儲存在資料庫
- 目前僅實作 Google (Gemini) 的測試邏輯，OpenAI 預留 TODO

#### `history.py`
| 端點 | 方法 | 說明 |
|------|------|------|
| `/api/v1/history` | GET | 分頁查詢歷史紀錄 |
| `/api/v1/history/stats` | GET | 取得統計總覽 |
| `/api/v1/history/{task_uuid}` | GET | 查詢單筆紀錄詳情 |
| `/api/v1/history/{task_uuid}` | DELETE | 刪除單筆紀錄 |

- 支援篩選：`status`, `is_batch`, `keyword`
- 統計包含：總任務數、完成/失敗數、成功率、總費用、總 Token、總音訊時長、平均處理時間

### 5.4 Celery 非同步任務 — `app/celery/`

#### `celery.py` — Celery App
- Broker: Redis
- Backend: PostgreSQL (`db+postgresql://`)
- 序列化: JSON
- 時區: Asia/Taipei
- Include: `app.celery.task`, `app.celery.batch_task`

#### `models.py` — 任務參數模型
- **`TranscriptionTaskParams`**：單檔任務參數 (file_path, provider, model, api_keys, source_lang, target_lang, etc.)
- **`BatchFileItemParams`**：批次中的單一檔案 (file_path, original_filename, file_uid)
- **`BatchTranscriptionTaskParams`**：批次任務參數 (files, provider, model, api_keys, etc.)

#### `task.py` — 單檔轉錄任務 `transcribe_media_task`
1. 反序列化參數 → `TranscriptionTaskParams`
2. 建立 `TranscriptionLog` 資料庫紀錄 (status=PROCESSING)
3. 初始化 `GeminiClient`
4. 建立 `TranscriptionTask`
5. 執行轉錄（含 VAD、分割重試邏輯）
6. 格式轉換 (LRC → SRT/VTT/TXT)
7. 費用計算
8. 更新 `TranscriptionLog` (status=COMPLETED)
9. 透過 Redis Pub/Sub 發布結果
10. 清理暫存檔案

#### `batch_task.py` — 批次轉錄任務
- **`batch_transcribe_task`**：
  1. 建立 `BatchJob` DB 紀錄
  2. 逐一上傳檔案至 Gemini File API
  3. 建立 `create_batch_transcription_job`（inline requests）
  4. 更新 DB 狀態為 `BATCH_SUBMITTED`
  5. 輪詢 `poll_batch_job_status` 直到完成
  6. 逐一處理結果 (`_process_single_result`)
  7. 存入 `results_json`

- **`batch_recover_task`**：
  1. 從 DB 載入 `BatchJob`
  2. 使用 `client.batches.get()` 從 Gemini 取得結果
  3. 處理並存入 DB
  4. 透過 Redis 發布結果

- **批次費用折扣**：`BATCH_COST_DISCOUNT = 0.5`（50% off）

### 5.5 資料庫層 — `app/database/`

#### `models.py` — SQLAlchemy ORM 模型

**`model_configurations` 資料表**：
| 欄位 | 類型 | 說明 |
|------|------|------|
| provider | String (PK) | AI 服務提供者名稱 |
| api_keys | Text | API 金鑰（JSON 字串） |
| model | String | 模型名稱 |
| prompt | Text | 自訂 Prompt |
| last_updated | DateTime | 最後更新時間 |

**`transcription_logs` 資料表**：
| 欄位 | 類型 | 說明 |
|------|------|------|
| task_uuid | UUID (PK) | 任務唯一識別碼 |
| request_timestamp | DateTime | 請求時間 |
| status | String | 狀態 (PROCESSING/COMPLETED/FAILED) |
| original_filename | String | 原始檔名 |
| audio_duration_seconds | Float | 音訊時長 |
| processing_time_seconds | Float | 處理時間 |
| model_used | String | 使用的模型 |
| source_language | String | 音訊語言 |
| target_language | String | 目標語言 |
| total_tokens | Integer | 總 Token 數 |
| cost | Float | 費用 |
| error_message | Text | 錯誤訊息 |
| user_id | String | 使用者 ID |
| is_batch | Boolean | 是否為批次任務 |
| batch_id | String | 批次 ID |
| provider | String | AI 提供者 |
| completed_at | DateTime | 完成時間 |

**`batch_jobs` 資料表**：
| 欄位 | 類型 | 說明 |
|------|------|------|
| batch_id | String (PK) | 前端的批次 ID |
| gemini_job_name | String | Gemini API 的 job name |
| status | String | UPLOADING / POLLING / BATCH_SUBMITTED / COMPLETED / FAILED / RETRIEVED / RECOVERING |
| task_params_json | Text | 序列化的任務參數（不含 api_keys） |
| file_mapping_json | Text | `{index: {file_uid, original_filename}}` |
| file_durations_json | Text | `{file_uid: duration}` |
| file_log_uuids_json | Text | `{file_uid: task_uuid}` |
| results_json | Text | `{file_uid: result_dict}` — 完成後存入的結果 |
| file_count | Integer | 總檔案數 |
| completed_file_count | Integer | 已完成檔案數 |
| created_at / updated_at | DateTime | 時間戳 |

#### `session.py` — 資料庫初始化
- **`engine`**：`create_engine` + pool_size/max_overflow/pool_pre_ping
- **`SessionLocal`**：sessionmaker
- **`_migrate_add_missing_columns()`**：自動新增 models 中有但 DB 表中缺少的欄位（簡易自動遷移）
- **`init_db()`**：`Base.metadata.create_all` + 插入預設 provider（Google, Anthropic, OpenAI）
- **`get_db()`**：FastAPI 依賴注入

### 5.6 Repository 層 — `app/repositories/`

使用 Repository Pattern 封裝資料庫操作：
- **`ModelSettingsRepository`**：模型設定 CRUD (`save`, `get_by_name`)
- **`TranscriptionLogRepository`**：轉錄日誌 CRUD (`create`, `update_status`)
- **`BatchJobRepository`**：批次任務 CRUD (`create`, `update_job`, `get_job`, `get_pending_jobs`)
- **`HistoryRepository`**：歷史紀錄查詢 (`get_logs_paginated`, `get_stats`, `get_log_by_uuid`, `delete_log`)

### 5.7 服務層 — `app/services/`

每個服務遵循 `models.py` + `flows.py` + `service.py` 結構：

#### VAD 服務 (`vad/`)
- **`VADService`**：模型管理（延遲載入 Silero VAD via `torch.hub.load`）
- **功能**：
  - `create_speech_only_audio()` — 提取語音部分，建立純語音檔案
  - `split_audio_on_silence()` — 在靜音處分割音訊為兩部分
  - `get_speech_statistics()` — 取得語音統計資訊
- **全域單例**：`get_vad_service()`, `initialize_vad_service()`

#### 轉錄服務 (`transcription/`)
- **`TranscriptionTask`**：轉錄任務管理器
- **主流程** (`transcribe_audio`)：
  1. VAD 靜音移除 → 建立純語音檔案
  2. 上傳至 Gemini → 轉錄
  3. 時間戳重映射回原始時間軸
  4. 如果轉錄失敗且檔案夠長 → 分割重試
- **時間戳處理**：
  - `_remap_lrc_timestamps()` — 從拼接時間軸映射回原始時間軸
  - `_adjust_lrc_timestamps()` — 校正偏移量

#### 格式轉換服務 (`converter/`)
- `_parse_lrc()` — 解析 LRC 格式（支援 `[mm:ss.xx]` 和 `[mm:ss.xxx]`）
- `_to_srt()`, `_to_vtt()`, `_to_txt()` — 各格式轉換
- `convert_from_lrc()` — 統一入口，回傳 `SubtitleFormats` 物件

#### 費用計算服務 (`calculator/`)
- **`CalculatorService.calculate_metrics()`**
- 根據模型名稱和 Token 數量計算費用
- 包含處理時間、音訊時長等性能指標

#### 翻譯服務 (`translator/`)
- `_perform_translation()` — 呼叫 Gemini 翻譯 API
- 回傳 `TranslationTaskResult`（含 token 計數）

### 5.8 Provider 層 — `app/provider/google/gemini.py`

**`GeminiClient`** 類別 + 獨立函式：

| 函式 | 說明 |
|------|------|
| `GeminiClient.__init__()` | 初始化 `genai.Client` |
| `GeminiClient.test_connection()` | 透過列出模型測試 API 連線 |
| `upload_file_to_gemini()` | 上傳檔案至 Gemini File API（含輪詢等待 ACTIVE） |
| `count_tokens_with_uploaded_file()` | 計算已上傳檔案的 Token 數 |
| `transcribe_with_uploaded_file()` | 使用已上傳檔案進行 Gemini 轉錄 |
| `translate_text()` | 使用 Gemini 進行文字翻譯 |
| `cleanup_gemini_file()` | 刪除 Gemini 上的暫存檔案 |
| `create_batch_transcription_job()` | 建立 Batch API 任務（inline requests） |
| `poll_batch_job_status()` | 查詢 Batch API 任務狀態 |
| `get_batch_job_state_name()` | 安全取得批次狀態名稱 |

**Batch 完成狀態**：`JOB_STATE_SUCCEEDED`, `JOB_STATE_FAILED`, `JOB_STATE_CANCELLED`, `JOB_STATE_EXPIRED`

### 5.9 WebSocket 管理 — `app/websocket/manager.py`

**`ConnectionManager`**（單例模式）：
- `active_connections: Dict[str, WebSocket]` — 以 `client_id`/`file_uid`/`batch_id` 為 key
- `connect()` / `disconnect()` — 管理 WebSocket 連線
- `send_personal_message()` — 向特定客戶端發送 JSON 訊息
- `redis_listener()` — 背景 `asyncio.Task`，訂閱 `transcription_updates` Redis 頻道

**通訊流程**：
```
Celery Worker → redis.publish("transcription_updates", JSON) 
→ WebSocket Manager (redis_listener) 
→ 根據 client_id 找到 WebSocket → send_json to 前端
```

### 5.10 工具函式 — `app/utils/`

#### `audio.py`
- `get_audio_duration()` — 使用 `ffprobe` 取得音訊時長
- `get_mime_type()` — 取得音訊 MIME 類型（內建對照表 + fallback）
- `convert_to_wav()` — 使用 `ffmpeg` 轉換為 WAV（16kHz, mono）

#### `logger.py`
- `setup_logger()` — 統一 Logger 設定
- 自訂 `PathAlignedFormatter`：顯示 `模組/檔名:行號` 格式，左對齊 25 字元
- 防止重複 handler 和向上傳播

---

## 6. 前端詳細架構

### 6.1 狀態管理架構

使用 **React Context** 進行全域狀態管理（無 Redux）：

```
App
├── ModelManagerProvider (Context) — 模型設定狀態
│   └── TranscriptionProvider (Context) — 轉錄核心狀態
│       ├── Transcription (頁面)
│       │   ├── FileManager
│       │   ├── UploadArea
│       │   ├── FileQueueHeader
│       │   ├── FileQueueTable
│       │   └── QueueSummary
│       └── History (頁面)
```

### 6.2 核心 Context — `TranscriptionContext.jsx`

這是前端最複雜的檔案（776 行），管理以下狀態和邏輯：

**狀態管理**：
- `fileList` — 上傳檔案列表
- `transcriptionResults` — 轉錄結果 map (file_uid → result)
- `isProcessing` — 處理中狀態
- `useBatchMode` — 批次模式切換
- `pendingBatches` — 待恢復的批次任務
- `previewRecord` / `previewVisible` — 預覽面板

**核心函式**：
| 函式 | 說明 |
|------|------|
| `handleRegularTranscription()` | 一般模式：每個檔案各自建立 WebSocket |
| `handleBatchTranscription()` | 批次模式：所有檔案共用一個 Batch WebSocket |
| `handleStartTranscription()` | 分流 Wrapper：根據 `useBatchMode` 選擇模式 |
| `checkPendingBatches()` | 檢查待恢復的批次任務 |
| `recoverBatch()` | 恢復批次任務 + 輪詢結果 |
| `downloadFile()` | 下載單一字幕檔案 |
| `downloadAllFiles()` | 下載所有檔案並打包 ZIP |
| `handleReprocess()` | 重新處理失敗的檔案 |
| `clearAllFiles()` | 清除所有檔案 |

**WebSocket 通訊協定**：
- 連線後發送 `WebSocketTranscriptionRequest` / `WebSocketBatchRequest` JSON
- 接收狀態更新：`{ status_code, status_text, result_data, file_uid }`
- 狀態碼：`PROCESSING`, `COMPLETED`, `FAILED`, `BATCH_COMPLETED`, `BATCH_SUBMITTED`

### 6.3 元件說明

#### `ModelManager.jsx`
- 提供 `ModelManagerProvider` Context
- 管理 AI 服務提供者的設定（API Key、模型選擇）
- 呼叫 `/api/v1/setting/models` CRUD API
- 提供 `useModelManager()` Hook

#### `FileManager.jsx`
- 檔案上傳區域（拖放 + 點擊）
- YouTube URL 輸入
- 呼叫 `POST /api/v1/upload` 上傳檔案

#### `Transcription.jsx`
- 轉錄主頁面，整合所有子元件
- 控制面板：語言選擇、Prompt 編輯、批次模式切換

#### `History.jsx`
- 歷史紀錄表格（分頁、篩選、排序）
- 統計卡片（總任務數、成功率、總費用等）
- 呼叫 `/api/v1/history` API

### 6.4 模型設定 — `modelConfig.js`

```javascript
export const modelOptions = {
  Google: [
    { value: 'gemini-3.1-pro-preview', label: 'gemini-3.1-pro-preview' },
    { value: 'gemini-2.5-flash', label: 'gemini-2.5-flash' },
    { value: 'gemini-2.5-pro', label: 'gemini-2.5-pro' }
  ]
  // Anthropic, OpenAI 已註解預留
};
```

---

## 7. Docker 環境

### 7.1 服務架構

```mermaid
graph LR
    subgraph Docker Compose
        PG[postgres<br/>13-alpine<br/>:5432]
        RD[redis<br/>6-alpine]
        BE[backend-service<br/>python:3.11-slim<br/>:8000]
        CW[celery-worker<br/>python:3.11-slim]
        FE_DEV[frontend-dev<br/>node:18-alpine<br/>:5173]
        FE_PROD[frontend<br/>nginx:alpine<br/>:80]
    end

    BE --> PG
    BE --> RD
    CW --> PG
    CW --> RD
    FE_DEV --> BE
    FE_PROD --> BE
```

### 7.2 開發環境 (`docker-compose.dev.yml`)

| 服務 | 容器名 | 特色 |
|------|--------|------|
| postgres | dev_postgres | 持久化 Volume: `postgres_data_dev` |
| redis | dev_redis | 無持久化 |
| backend-service | dev_backend | `uvicorn --reload` + 原始碼 Volume 掛載 |
| celery-worker | dev_celery | 原始碼 Volume 掛載（修改後需手動 restart） |
| frontend-dev | dev_frontend | Vite dev server + HMR，`npm install && npm run dev -- --host 0.0.0.0` |

- **Volume 掛載**使得程式碼變更無需 rebuild
- Backend 支援 `--reload` 自動重啟
- 前端 Vite proxy: `VITE_PROXY_TARGET=http://backend-service:8000`
- `backend_static_cache` Volume 用於快取 `.cache` 目錄（如 PyTorch 模型）

### 7.3 生產環境 (`docker-compose.prod.yml`)

| 服務 | 容器名 | 特色 |
|------|--------|------|
| postgres | prod_postgres | 持久化 Volume: `postgres_data` |
| redis | prod_redis | 無持久化 |
| backend-service | prod_backend | `uvicorn main:app --host 0.0.0.0 --port 8000`（無 reload） |
| celery-worker | prod_celery_worker | 僅掛載 `temp_uploads` Volume |
| frontend | prod_frontend | 多階段建構：Node build → Nginx 靜態服務 |

- 前端透過 Nginx 反向代理存取後端 API 和 WebSocket
- `DATABASE_URL` 由環境變數注入
- 所有服務時區設定為 `Asia/Taipei`

### 7.4 Nginx 設定 (`frontend/nginx.conf`)

```nginx
# 靜態檔案
location / → /usr/share/nginx/html (try_files, SPA fallback)

# WebSocket 反向代理
location /api/v1/ws/ → http://backend-service:8000
  - proxy_http_version 1.1
  - Upgrade + Connection headers

# REST API 反向代理
location /api/ → http://backend-service:8000
  - 超時設定 600s（長時間 API 呼叫）

# client_max_body_size 1000M（支援大檔案上傳）
```

### 7.5 Backend Dockerfile

```dockerfile
FROM python:3.11-slim
# 安裝 build-essential + ffmpeg
# 先 COPY requirements.txt → pip install（利用 Docker 快取）
# 再 COPY 全部原始碼
EXPOSE 8000
```

### 7.6 Frontend Dockerfile（多階段建構）

```dockerfile
# Stage 1: Build
FROM node:18-alpine AS build → npm install → npm run build

# Stage 2: Serve
FROM nginx:alpine → COPY nginx.conf → COPY dist → EXPOSE 80
```

---

## 8. 環境變數

### 8.1 `.env.prod`（Docker Compose 共用）
```env
POSTGRES_USER=user
POSTGRES_PASSWORD=password
POSTGRES_DB=mydatabase
```

### 8.2 `backend/.env`（本地開發）
```env
# 資料庫
POSTGRES_USER=...
POSTGRES_PASSWORD=...
POSTGRES_DB=...
DATABASE_URL=postgresql://user:password@localhost:5432/mydb

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# AI API Keys
GOOGLE_API_KEY=...
OPENAI_API_KEY=...

# 應用程式
TEMP_UPLOADS_DIR=temp_uploads
```

### 8.3 Docker Compose 環境變數注入
- `POSTGRES_SERVER` → 容器間用 `postgres` (service name)
- `REDIS_HOST` → 容器間用 `redis` (service name)
- `DATABASE_URL` → 生產環境由 `docker-compose.prod.yml` 直接注入完整 URL
- `TZ=Asia/Taipei` → 所有容器統一時區

---

## 9. 開發指南

### 9.1 本地開發環境快速啟動

**前提條件**：Python 3.11+, Node.js 18+, PostgreSQL 13+, Redis 6+, FFmpeg

```bash
# 方式 1：使用 Startup.bat（Windows）
Startup.bat          # 啟動所有服務（各在獨立視窗）
Startup.bat app      # 僅啟動 FastAPI
Startup.bat celery   # 僅啟動 Celery Worker
Startup.bat react    # 僅啟動 React Frontend

# 方式 2：手動啟動
# Terminal 1: FastAPI
cd backend && .venv\Scripts\activate && uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Celery（Windows 使用 gevent pool）
cd backend && .venv\Scripts\activate && celery -A app.celery.celery:celery_app worker -l INFO -P gevent

# Terminal 3: React
cd frontend && npm run dev
```

**存取位址**：
- 前端：http://localhost:5173（開發）/ http://localhost（Docker 生產）
- API 文件：http://localhost:8000/docs（Swagger UI）
- ReDoc：http://localhost:8000/redoc

### 9.2 Docker 開發環境

```bash
docker-compose -f docker-compose.dev.yml up --build
# 修改後端 → 自動重啟（uvicorn --reload）
# 修改 Celery → docker-compose -f docker-compose.dev.yml restart celery-worker
# 修改前端 → 即時熱更新（Vite HMR）
```

### 9.3 測試

```bash
cd backend
pytest tests/ -v
```

測試檔案：
- `tests/conftest.py` — 共用 fixtures
- `tests/gemini_test.py` — Gemini API 整合測試
- `tests/test_model_manager_api.py` — 模型管理 API 測試
- `tests/test_transcription_api.py` — 轉錄 API 測試

### 9.4 新增 AI 模型

1. 在 `frontend/src/constants/modelConfig.js` 新增模型選項
2. 如需新增服務商：在 `backend/app/provider/` 建立對應的客戶端

### 9.5 重要的設計決策

| 決策 | 說明 |
|------|------|
| **Prompt 唯一來源** | `default_prompt.py` 是 Prompt 模板的 Single Source of Truth |
| **自動遷移** | `session.py` 中的 `_migrate_add_missing_columns()` 自動新增缺失欄位，無需 Alembic |
| **批次結果持久化** | `BatchJob.results_json` 存儲完整結果，支援 Docker 重啟後恢復 |
| **Redis Pub/Sub** | Celery Worker → Redis publish → FastAPI WebSocket → 前端，解耦通訊 |
| **VAD 延遲載入** | Silero VAD 模型在首次使用時才載入，減少啟動時間 |
| **Celery gevent pool** | Windows 不支援 prefork，使用 gevent 協程池 |

---

## 10. API Schema 速查

### 10.1 請求 Schema

| Schema | 用途 |
|--------|------|
| `ProviderConfigRequest` | 儲存模型設定 (provider, apiKeys[], model, prompt) |
| `TestProviderRequest` | 測試 API 連線 (provider, apiKeys[], model) |
| `WebSocketTranscriptionRequest` | 單檔轉錄請求 |
| `WebSocketBatchRequest` | 批次轉錄請求 (files[], provider, model, etc.) |
| `RecoverBatchRequest` | 恢復批次任務 (api_keys) |

### 10.2 回應 Schema

| Schema | 用途 |
|--------|------|
| `ProviderConfigResponse` | 模型設定回應 |
| `TestProviderResponse` | API 測試結果 |
| `PendingBatchResponse` | 待恢復的批次任務 |
| `RecoverBatchResponse` | 恢復結果 (files[]) |
| `HistoryLogResponse` | 單筆歷史紀錄 |
| `HistoryListResponse` | 分頁歷史紀錄清單 |
| `HistoryStatsResponse` | 歷史統計總覽 |

---

## 11. 已知的技術債與待辦事項

1. **OpenAI 測試邏輯**：`model_manager.py` 中 OpenAI 測試標記為 TODO
2. **Alembic 遷移**：目前使用自動 ALTER TABLE，未使用正式的遷移框架
3. **前端路由**：目前使用 Menu 切換（非 React Router），無 URL 路由
4. **認證與授權**：無使用者認證機制（`user_id` 欄位存在但未使用）
5. **`pika` 套件**：已安裝但未使用（可能是舊的 RabbitMQ 遺留）
6. **前端 `targetLang` 重命名**：有計畫將前端 `targetLang` 重命名為 `sourceLang`（已延遲）
7. **CORS 設定**：生產環境 CORS 允許 `["*"]`，應限制
