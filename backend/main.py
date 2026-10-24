import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
from app.api import local_models
from app.api import model_manager
from app.api import providers
from app.api import transcription
from app.api import upload
from app.api import batch
from app.api import history
from app.api import transcripts
from app.api import vad
from app.websocket.manager import manager as websocket_manager
from app.websocket.origin import WebSocketOriginMiddleware

from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.runtime import run_mode
from app.database.session import init_db, SessionLocal, without_db_details
from app.repositories.transcription_log_repository import TranscriptionLogRepository
from app.tasks import batch_core, older_batches
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def end_stale_processing() -> None:
    """啟動清掃孤兒紀錄：worker 中途被終止時，單檔任務會留下永遠 PROCESSING 的紀錄，記成失敗。
    免安裝模式的任務跑在本行程內，重啟後必死 → 全掃（max_age=0）。出錯時只記 log，照樣啟動。"""
    settings = get_settings()
    try:
        stale_hours = 0 if settings.is_standalone \
            else settings.stale_processing_max_age_hours
        with SessionLocal() as db:
            swept = TranscriptionLogRepository().mark_stale_processing_failed(
                db, stale_hours)
        if swept:
            logger.info(f"啟動清掃：{swept} 筆逾時 PROCESSING 紀錄已標記為 FAILED")
    except Exception as e:
        logger.warning(f"啟動清掃逾時 PROCESSING 紀錄失敗: {without_db_details(e)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("正在啟動 AI Voice Transcription API...")
    settings = get_settings()

    init_db()

    end_stale_processing()

    # 舊版送出的批次補上每個檔案的列：之後和這一版的批次一樣復原、取回結果、在任務頁列出檔名
    try:
        with SessionLocal() as db:
            added = older_batches.add_file_rows(db)
        if added:
            logger.info(f"舊版送出的 {added} 個批次補上了每個檔案的列")
    except Exception as e:
        logger.warning(f"替舊版送出的批次補列失敗: {without_db_details(e)}")

    # 清掉超過保留天數的保留音檔（它不是永久保存）
    from app.services import audio_store
    try:
        audio_store.purge_expired()
    except Exception as e:
        logger.warning(f"清理過期音檔失敗: {e}")
    # 清掉暫存區裡逾時的上傳檔：沒機會收尾的任務留下的（例如關閉時還在排隊）
    try:
        audio_store.purge_stale_uploads()
    except Exception as e:
        logger.warning(f"清理暫存上傳檔失敗: {e}")

    # 依執行模式選一次轉接器，再啟動 WebSocket 狀態監聽器
    run_mode.get()
    websocket_manager.start()

    # 免安裝模式的批次跑在本行程內：重啟之後，上傳中的批次必定已經停了，記成失敗。Docker 模式由
    # worker 啟動時收（app.celery.celery），API 單獨重啟時 worker 可能還在上傳
    if settings.is_standalone:
        try:
            ended = batch_core.end_stopped_uploads()
            if ended:
                logger.info(f"啟動清掃：{ended} 個上傳時停住的批次記成失敗")
        except Exception as e:
            logger.warning(f"啟動清掃上傳中的批次失敗: {without_db_details(e)}")

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
        run_mode.close()


app = FastAPI(title="AI Voice Transcription API",
              version="1.0.0", lifespan=lifespan)


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
    """端點沒有自己接住的資料庫例外：log 只記例外類型與原因，回固定訊息的 500。

    例外的文字有 SQL 原文，Postgres 附上的 DETAIL 還可能是寫不進去的整列（任務紀錄與批次的那一列有
    原始檔名與轉錄結果）。traceback 留著出錯的位置，但不帶訊息與成因（見 without_db_details）。
    對 SQLAlchemyError 這種特定類別註冊，Starlette 處理完就不再往上拋，uvicorn 不會連同 traceback
    記進 log；對 Exception 註冊的 handler 處理完照樣往上拋。WebSocket 端點自己接住所有例外。
    """
    logger.error(f"{request.method} {request.url.path} 資料庫出錯:\n"
                 f"{''.join(traceback.format_exception(without_db_details(error)))}")
    return JSONResponse(status_code=500,
                        content={"detail": "資料庫出錯了，這次的操作沒有完成，請再試一次；"
                                           "一直失敗的話請回報問題。"})


@app.get("/api/v1/health", tags=["Health"])
def health():
    """launcher / 監控探活用。"""
    return {"status": "ok"}


app.include_router(transcription.router, prefix="/api/v1",
                   tags=["Transcription"])
app.include_router(providers.router, prefix="/api/v1", tags=["Providers"])
app.include_router(model_manager.router,
                   prefix="/api/v1/setting",
                   tags=["Model Settings"])
app.include_router(local_models.router,
                   prefix="/api/v1/setting",
                   tags=["Local Models"])
app.include_router(upload.router, prefix="/api/v1", tags=["Upload"])
app.include_router(batch.router, prefix="/api/v1/batch", tags=["Batch Transcription"])
app.include_router(history.router, prefix="/api/v1/history", tags=["History"])
app.include_router(transcripts.router, prefix="/api/v1/transcripts",
                   tags=["Transcripts"])
app.include_router(vad.router, prefix="/api/v1/vad", tags=["VAD"])

# 只放行設定中的來源（預設為開發用的 Vite dev server），不再用 * 搭配 credentials。
# Docker 模式開發時前端經 Vite proxy 呼叫 /api、免安裝模式由本服務同源提供，
# 對瀏覽器而言都是同源請求，不靠 CORS；清單只影響真正跨來源的呼叫
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["DELETE", "GET", "POST", "PUT"],
    allow_headers=["*"],
)
# WebSocket 不受 CORS 保護：握手時 Origin 必須同源或在同一份允許清單內
app.add_middleware(WebSocketOriginMiddleware,
                   allowed_origins=get_settings().cors_origins)


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


# 免安裝模式：FastAPI 同源直接服務 frontend/dist（前端 API/WS 都是
# 相對路徑，無需任何前端修改）；Docker 模式維持 Vite dev server，不掛載
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
