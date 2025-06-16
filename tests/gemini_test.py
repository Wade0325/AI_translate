import asyncio
import random
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# --- 應用程式設定 ---
app = FastAPI(
    title="模擬 Gemini API 回應的後端",
    description="這個 FastAPI 應用程式用來模擬一個接收音檔並回傳轉錄結果的後端服務。",
    version="1.0.0",
)

# --- CORS 設定 ---
# 允許所有來源，方便前端在不同埠號進行測試
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 模擬資料 ---
mock_transcriptions = [
    "你好，這是一段由模擬後端產生的測試語音轉錄稿。",
    "歡迎使用我們的服務，您的檔案正在被飛快的（假裝）處理中。",
    "測試，測試，1、2、3。麥克風聽起來沒問題。",
    "為什麼這段語音聽起來像貓在彈鋼琴？喔，原來真的是。",
    "這是個秘密訊息：記得在會議結束後餵你的虛擬寵物。",
]

# --- API 端點 ---


@app.post(
    "/api/v1/transcribe",
    tags=["Transcription"],
    summary="模擬音檔轉錄",
    description="接收一個音訊/視訊檔案，並模擬回傳轉錄結果、消耗的 tokens 和費用。",
)
async def mock_transcribe_file(
    file: UploadFile = File(..., description="使用者上傳的音訊或視訊檔案"),
    source_lang: str = Form("zh-TW", description="來源語言"),
    model: str = Form("Google", description="使用的模型"),
):
    """
    這個端點會模擬處理上傳的檔案：
    1. 隨機等待 1 到 3 秒，模擬處理時間。
    2. 從預設列表中隨機選擇一段文稿。
    3. 隨機產生消耗的 tokens 數量和費用。
    4. 回傳一個 JSON 物件。
    """
    print(f"接收到檔案: {file.filename} ({file.content_type})")
    print(f"設定: 來源={source_lang}, 模型={model}")

    # 1. 模擬網路延遲與處理時間
    await asyncio.sleep(random.uniform(1, 3))

    # 2. 產生模擬回應資料
    base_text = random.choice(mock_transcriptions)
    tokens_used = random.randint(500, 3000)
    # 假設一個簡單的計價模型 (例如: $0.00015 / token)
    cost = tokens_used * 0.00015

    transcripts = {
        "lrc": f"[00:01.00] {base_text} (LRC format)",
        "srt": f"1\n00:00:01,000 --> 00:00:05,000\n{base_text} (SRT format)",
        "vtt": f"WEBVTT\n\n00:01.000 --> 00:05.000\n{base_text} (VTT format)",
        "txt": f"{base_text} (TXT format)",
    }

    response_data = {
        "transcripts": transcripts,
        "tokens_used": tokens_used,
        "cost": cost,
        "model": model,
        "source_language": source_lang,
    }

    return JSONResponse(content=response_data)

# --- 啟動伺服器 ---
if __name__ == "__main__":
    print("啟動模擬後端伺服器於 http://localhost:8000")
    print("你可以透過 GET http://localhost:8000/docs 來查看 API 文件")
    uvicorn.run(app, host="0.0.0.0", port=8000)
