<div align="center">
  <h1>🎙️ AI Voice Transcription</h1>
  <p><strong>AI 驅動的語音轉錄與字幕生成工具</strong></p>
  <p>將音訊/視頻轉換成帶有精確時間戳的多格式字幕檔案</p>
  
  ![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
  ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
  ![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
  ![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)
</div>

---

## 📖 目錄

- [✨ 功能特色](#-功能特色)
- [🖥️ 系統截圖](#️-系統截圖)
- [🏗️ 系統架構](#️-系統架構)
- [🛠️ 技術棧](#️-技術棧)
- [📋 環境需求](#-環境需求)
- [🚀 快速開始](#-快速開始)
  - [Docker 部署（推薦）](#docker-部署推薦)
  - [本地開發環境](#本地開發環境)
- [⚙️ 環境變數配置](#️-環境變數配置)
- [📚 API 文件](#-api-文件)
- [📁 專案結構](#-專案結構)
- [🔧 開發指南](#-開發指南)
- [📝 授權](#-授權)

---

## ✨ 功能特色

### 🎯 核心功能

| 功能 | 說明 |
|------|------|
| 📤 **多格式上傳** | 支援 MP3、WAV、FLAC、M4A、MP4、WebM 等多種音訊/視頻格式 |
| 🔗 **YouTube 支援** | 直接貼上 YouTube 連結即可下載並轉錄 |
| 🗣️ **智能語音偵測 (VAD)** | 使用 Silero VAD 自動偵測語音活動區段，提升轉錄精確度 |
| 🤖 **AI 語音轉錄** | 整合 Google Gemini 多模態模型進行高品質語音轉文字 |
| 🌐 **自動翻譯** | 支援轉錄後自動翻譯至目標語言 |
| ⏱️ **精確時間戳** | 生成帶有毫秒級時間戳的字幕檔案 |

### 🎨 進階功能

- **📝 文稿對齊**：附加原始文稿，AI 將為其配上精確時間戳
- **🎛️ 自訂 Prompt**：完全自訂轉錄指令，支援特定術語和說話者標記
- **📊 即時進度**：WebSocket 即時推送處理進度與狀態
- **💰 費用估算**：自動計算 API Token 用量與成本
- **📥 多格式匯出**：支援 LRC、SRT、VTT、TXT 等多種字幕格式

### 🌍 語言支援

- 繁體中文（台灣）
- 英文（美國）
- 日文（日本）
- *更多語言可透過自訂 Prompt 擴展*

---

## 🖥️ 系統截圖

> 📸 *待補充系統截圖*

---

## 🏗️ 系統架構

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (React)                         │
│                   React 19 + Vite 6 + Ant Design 6                │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ HTTP / WebSocket
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Backend API (FastAPI)                         │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  Upload API  │  │ Transcribe   │  │  Model Settings API  │   │
│  │              │  │   WebSocket  │  │                      │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
┌──────────────────┐  ┌────────────────┐  ┌────────────────┐
│  Redis           │  │  PostgreSQL    │  │  Celery        │
│  (Message Queue) │  │  (Database)    │  │  (Task Queue)  │
└──────────────────┘  └────────────────┘  └────────────────┘
                                                   │
                                                   ▼
                              ┌──────────────────────────────────┐
                              │        Celery Worker              │
                              │                                   │
                              │  ┌─────────┐  ┌─────────────────┐ │
                              │  │ VAD     │  │  Google Gemini  │ │
                              │  │ Service │  │  Transcription  │ │
                              │  └─────────┘  └─────────────────┘ │
                              └──────────────────────────────────┘
```

---

## 🛠️ 技術棧

### 前端
| 技術 | 版本 | 說明 |
|------|------|------|
| React | 19.2 | 使用者介面框架 |
| Vite | 6.3 | 前端建構工具 |
| Ant Design | 6.3 | UI 元件庫 |
| React Router | 7.5 | 前端路由 |
| Recharts | 2.15 | 資料圖表 |
| JSZip | 3.10 | 批量下載壓縮 |

### 後端
| 技術 | 版本 | 說明 |
|------|------|------|
| Python | 3.11 | 程式語言 |
| FastAPI | 0.115 | Web 框架 |
| Uvicorn | 0.34 | ASGI 伺服器 |
| Celery | 5.5 | 分散式任務佇列 |
| SQLAlchemy | 2.0 | ORM 資料庫存取 |
| Pydantic | 2.11 | 資料驗證 |

### AI / 機器學習
| 技術 | 版本 | 說明 |
|------|------|------|
| PyTorch | 2.7 | 深度學習框架 |
| Silero VAD | 5.1 | 語音活動偵測 |
| Google GenAI | 1.20 | Gemini API 客戶端 |
| yt-dlp | 2025.6 | YouTube 下載器 |

### 基礎設施
| 技術 | 說明 |
|------|------|
| PostgreSQL | 關聯式資料庫 |
| Redis | 訊息佇列 & 快取 |
| Docker | 容器化部署 |
| Nginx | 前端靜態檔案伺服器 |

---

## 📋 環境需求

### Docker 部署
- Docker Engine 20.10+
- Docker Compose v2.0+

### 本地開發
- Python 3.11+
- Node.js 18+
- PostgreSQL 13+
- Redis 6+
- FFmpeg（音訊處理必需）

---

## 🚀 快速開始

### Docker 部署（推薦）

1. **Clone 專案**
   ```bash
   git clone https://github.com/Wade0325/AI_translate.git
   cd AI_translate
   ```

2. **設定環境變數**
   ```bash
   # 複製環境變數範本
   cp .env.example .env.prod
   
   # 編輯 .env.prod，填入您的 API 金鑰
   ```

3. **啟動所有服務**
   ```bash
   docker-compose -f docker-compose.prod.yml up --build -d
   ```

4. **開啟應用程式**
   - 🌐 前端介面：[http://localhost](http://localhost)
   - 📡 API 文件：[http://localhost:8000/docs](http://localhost:8000/docs)

5. **查看日誌**
   ```bash
   # 查看所有服務日誌
   docker-compose -f docker-compose.prod.yml logs -f
   
   # 查看特定服務日誌
   docker-compose -f docker-compose.prod.yml logs -f backend-service
   ```

6. **停止服務**
   ```bash
   docker-compose -f docker-compose.prod.yml down
   ```

---

### 本地開發環境

#### 1️⃣ 後端設定

```bash
# 進入後端目錄
cd backend

# 建立虛擬環境
python -m venv .venv

# 啟用虛擬環境 (Windows)
.venv\Scripts\activate

# 啟用虛擬環境 (macOS/Linux)
source .venv/bin/activate

# 安裝依賴
pip install -r requirements.txt
```

#### 2️⃣ 前端設定

```bash
# 進入前端目錄
cd frontend

# 安裝依賴
npm install
```

#### 3️⃣ 啟動服務

使用專案提供的啟動腳本（Windows）：

```bash
# 終端機 1 - 啟動 FastAPI 後端
Startup.bat app

# 終端機 2 - 啟動 Celery Worker
Startup.bat celery

# 終端機 3 - 啟動 React 前端
Startup.bat react
```

或手動啟動：

```bash
# 終端機 1 - FastAPI 後端
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 終端機 2 - Celery Worker
cd backend
celery -A app.celery.celery:celery_app worker -l INFO -P gevent

# 終端機 3 - React 前端
cd frontend
npm run dev
```

#### 4️⃣ 存取應用程式

- 🌐 前端介面：[http://localhost:5173](http://localhost:5173)
- 📡 API 文件：[http://localhost:8000/docs](http://localhost:8000/docs)
- 📊 ReDoc：[http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## ⚙️ 環境變數配置

建立 `.env.prod` 檔案（Docker 部署）或 `.env` 檔案（本地開發）：

```env
# ===== 資料庫設定 =====
POSTGRES_USER=your_db_user
POSTGRES_PASSWORD=your_db_password
POSTGRES_DB=transcription_db
DATABASE_URL=postgresql://user:password@localhost:5432/transcription_db

# ===== Redis 設定 =====
REDIS_HOST=localhost
REDIS_PORT=6379

# ===== AI 模型 API 金鑰 =====
# Google Gemini (必填)
GOOGLE_API_KEY=your_google_api_key

# OpenAI (選填)
OPENAI_API_KEY=your_openai_api_key

# ===== 應用程式設定 =====
TEMP_UPLOADS_DIR=temp_uploads
```

---

## 📚 API 文件

啟動後端服務後，可透過以下網址存取互動式 API 文件：

| 文件類型 | URL |
|----------|-----|
| Swagger UI | [http://localhost:8000/docs](http://localhost:8000/docs) |
| ReDoc | [http://localhost:8000/redoc](http://localhost:8000/redoc) |

### 主要 API 端點

| 方法 | 端點 | 說明 |
|------|------|------|
| `POST` | `/api/v1/upload` | 上傳音訊/視頻檔案 |
| `WebSocket` | `/api/v1/ws/{file_uid}` | 轉錄任務即時進度 |
| `GET` | `/api/v1/setting/model` | 取得模型設定 |
| `PUT` | `/api/v1/setting/model` | 更新模型設定 |

---

## 📁 專案結構

```
AI_translate/
├── 📂 backend/                    # 後端服務
│   ├── 📂 app/
│   │   ├── 📂 api/                # API 路由
│   │   │   ├── model_manager.py   # 模型設定 API
│   │   │   ├── transcription.py   # 轉錄 WebSocket
│   │   │   └── upload.py          # 檔案上傳 API
│   │   ├── 📂 celery/             # Celery 任務
│   │   │   ├── celery.py          # Celery 設定
│   │   │   ├── models.py          # 任務參數模型
│   │   │   └── task.py            # 轉錄任務邏輯
│   │   ├── 📂 database/           # 資料庫
│   │   │   ├── models.py          # SQLAlchemy 模型
│   │   │   └── session.py         # 資料庫連線
│   │   ├── 📂 provider/           # AI 服務提供者
│   │   │   └── google/
│   │   │       └── gemini.py      # Gemini API 客戶端
│   │   ├── 📂 services/           # 業務邏輯
│   │   │   ├── calculator/        # 費用計算服務
│   │   │   ├── converter/         # 格式轉換服務
│   │   │   ├── transcription/     # 轉錄服務
│   │   │   ├── translator/        # 翻譯服務
│   │   │   └── vad/               # 語音活動偵測服務
│   │   ├── 📂 websocket/          # WebSocket 管理
│   │   └── 📂 utils/              # 工具函式
│   ├── main.py                    # FastAPI 應用程式入口
│   ├── requirements.txt           # Python 依賴
│   └── Dockerfile
│
├── 📂 frontend/                   # 前端應用 (React 19 + Vite 6 + Ant Design 6)
│   ├── 📂 src/
│   │   ├── 📂 components/         # React 元件
│   │   │   ├── ModelManager.jsx   # 模型設定元件
│   │   │   ├── app-sidebar.jsx    # 側邊欄導航
│   │   │   ├── 📂 dashboard/     # 儀表板元件
│   │   │   ├── 📂 transcribe/    # 轉錄相關元件
│   │   │   └── 📂 result/        # 結果檢視元件
│   │   ├── 📂 constants/          # 常數設定
│   │   │   └── modelConfig.js     # 模型選項
│   │   ├── 📂 context/            # React Context
│   │   │   └── TranscriptionContext.jsx
│   │   ├── 📂 layouts/            # 版面配置
│   │   │   └── DashboardLayout.jsx
│   │   ├── 📂 pages/              # 頁面元件
│   │   │   ├── DashboardPage.jsx  # 儀表板
│   │   │   ├── TranscribePage.jsx # 轉錄頁面
│   │   │   ├── ResultPage.jsx     # 結果檢視
│   │   │   ├── TaskPage.jsx       # 任務管理
│   │   │   ├── HistoryPage.jsx    # 歷史記錄
│   │   │   ├── BillingPage.jsx    # 用量計費
│   │   │   └── SettingsPage.jsx   # 設定
│   │   ├── App.jsx                # 路由設定 (react-router-dom)
│   │   └── main.jsx               # 應用程式入口
│   ├── package.json
│   ├── vite.config.js
│   ├── nginx.conf                 # 生產環境 Nginx 設定
│   └── Dockerfile
│
├── 📂 tests/                      # 測試檔案
├── docker-compose.prod.yml        # Docker Compose 設定
├── Startup.bat                    # Windows 啟動腳本
└── README.md
```

---

## 🔧 開發指南

### 新增 AI 模型

1. 在 `frontend/src/constants/modelConfig.js` 新增模型選項：

```javascript
export const modelOptions = {
  Google: [
    { value: 'gemini-2.5-flash', label: 'gemini-2.5-flash' },
    { value: 'gemini-2.5-pro', label: 'gemini-2.5-pro' },
    // 新增更多模型...
  ],
  // 新增其他服務商...
};
```

2. 如需新增服務商，在 `backend/app/provider/` 建立對應的客戶端。

### 自訂 Prompt

Prompt 模板由後端統一管理，在 `backend/app/core/default_prompt.py` 中修改：

- `build_prompt()` 函式負責組裝最終 Prompt
- 支援自訂術語表與說話者標記規則
- 前端透過 API 傳遞參數，後端動態生成 Prompt

### 執行測試

```bash
cd backend
pytest tests/ -v
```

---

## 🔗 相關連結

- [FastAPI 官方文件](https://fastapi.tiangolo.com/)
- [React 官方文件](https://react.dev/)
- [Ant Design 元件庫](https://ant.design/)
- [Google Gemini API](https://ai.google.dev/)
- [Silero VAD](https://github.com/snakers4/silero-vad)

---

## 📝 授權

本專案採用 [MIT License](LICENSE) 授權。

---

<div align="center">
  <p>Made with ❤️ by Wade</p>
  <p>
    <a href="https://github.com/Wade0325/AI_translate">⭐ Star this repo</a> •
    <a href="https://github.com/Wade0325/AI_translate/issues">🐛 Report Bug</a> •
    <a href="https://github.com/Wade0325/AI_translate/pulls">✨ Contribute</a>
  </p>
</div>
