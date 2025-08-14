from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.api import model_manager
from app.api import transcription

from fastapi.middleware.cors import CORSMiddleware
from app.database.session import init_db
from app.utils.logger import setup_logger

# 建立 logger
logger = setup_logger(__name__)

# 初始化資料庫
init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理"""
    logger.info("正在啟動 AI Voice Transcription API...")

    # 預先初始化 VAD 服務
    try:
        from app.services.vad.service import initialize_vad_service
        vad_service = initialize_vad_service()
        if vad_service:
            logger.info("VAD 服務已在應用程式啟動時成功初始化")
        else:
            logger.warning("VAD 服務初始化失敗，將在首次使用時延遲載入")
    except Exception as e:
        logger.warning(f"無法預先初始化 VAD 服務: {e}")

    logger.info("應用程式啟動完成")
    yield
    logger.info("應用程式正在關閉...")


app = FastAPI(title="AI Voice Transcription API",
              version="1.0.0", lifespan=lifespan)


# 更新路由設定
app.include_router(transcription.router, prefix="/api/v1",
                   tags=["Transcription"])
app.include_router(model_manager.router,
                   prefix="/api/v1/model-manager",
                   tags=["Model Settings"])

origins = [
    "http://localhost:8000",
    "http://localhost:3000",
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["DELETE", "GET", "POST", "PUT"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
