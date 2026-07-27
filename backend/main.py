from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
from app.api import local_models
from app.api import model_manager
from app.api import transcription
from app.api import upload
from app.api import batch
from app.api import history
from app.api import vad
from app.websocket.manager import manager as websocket_manager

from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.database.session import init_db, SessionLocal
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("正在啟動 AI Voice Transcription API...")
    settings = get_settings()

    init_db()

    # 清掃孤兒紀錄：worker 中途被終止時，單檔任務會留下永遠 PROCESSING 的紀錄。
    # standalone 模式任務跑在本行程內，重啟後必死 → 全掃（max_age=0）
    try:
        stale_hours = 0 if settings.is_standalone \
            else settings.stale_processing_max_age_hours
        with SessionLocal() as db:
            swept = TranscriptionLogRepository().mark_stale_processing_failed(
                db, stale_hours)
        if swept:
            logger.info(f"啟動清掃：{swept} 筆逾時 PROCESSING 紀錄已標記為 FAILED")
    except Exception as e:
        logger.warning(f"啟動清掃逾時 PROCESSING 紀錄失敗: {e}")

    # 啟動 WebSocket 狀態監聽器（docker：Redis pub/sub；standalone：local_bus）
    websocket_manager.start()

    # 預熱 VAD，避免首個任務才載模型
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
    try:
        yield
    finally:
        logger.info("應用程式正在關閉...")
        await websocket_manager.shutdown()
        if settings.is_standalone:
            from app.runtime.executor import shutdown_executor
            shutdown_executor()


app = FastAPI(title="AI Voice Transcription API",
              version="1.0.0", lifespan=lifespan)


@app.get("/api/v1/health", tags=["Health"])
def health():
    """launcher / 監控探活用。"""
    return {"status": "ok"}


app.include_router(transcription.router, prefix="/api/v1",
                   tags=["Transcription"])
app.include_router(model_manager.router,
                   prefix="/api/v1/setting",
                   tags=["Model Settings"])
app.include_router(local_models.router,
                   prefix="/api/v1/setting",
                   tags=["Local Models"])
app.include_router(upload.router, prefix="/api/v1", tags=["Upload"])
app.include_router(batch.router, prefix="/api/v1/batch", tags=["Batch Transcription"])
app.include_router(history.router, prefix="/api/v1/history", tags=["History"])
app.include_router(vad.router, prefix="/api/v1/vad", tags=["VAD"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["DELETE", "GET", "POST", "PUT"],
    allow_headers=["*"],
)


class _SPAStaticFiles(StaticFiles):
    """服務前端 SPA：未知路徑退回 index.html，讓 react-router 處理。

    /api/ 開頭的未知路徑維持 404 — 那是 API 錯誤，不是前端路由。
    """

    async def get_response(self, path: str, scope):
        # Windows 上 StaticFiles 的 path 以反斜線正規化，統一後再判斷
        is_api = path.replace("\\", "/").startswith("api/")
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code == 404 and not is_api:
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404 and not is_api:
            return await super().get_response("index.html", scope)
        return response


# standalone 模式：FastAPI 同源直接服務 frontend/dist（前端 API/WS 都是
# 相對路徑，無需任何前端修改）；docker 模式維持 Vite dev server，不掛載
_static_path = get_settings().static_path
if _static_path is not None:
    if _static_path.is_dir():
        app.mount("/", _SPAStaticFiles(directory=str(_static_path), html=True),
                  name="spa")
        logger.info(f"前端靜態檔已掛載: {_static_path}")
    else:
        logger.warning(
            f"找不到前端靜態檔目錄 {_static_path}，僅提供 API（請先 vite build）")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
