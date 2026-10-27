"""設定頁「資料與隱私」：資料放在哪、保留音檔留了多少，以及立即刪除全部保留音檔（#231 Q1、Q7）。

清除所有資料與匯出延後（#231 Q7），這裡只說資料放在哪，讓使用者自己刪。
"""

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.schemas import (
    DeleteRetainedAudioResponse,
    LocalDataResponse,
    RetainedAudioResponse,
)
from app.services import audio_store

router = APIRouter()


@router.get("", response_model=LocalDataResponse)
def local_data():
    settings = get_settings()
    usage = audio_store.usage()
    return LocalDataResponse(
        data_folder=str(settings.data_path.resolve()) if settings.is_standalone else None,
        retained_audio=RetainedAudioResponse(
            enabled=settings.retain_audio,
            retention_days=settings.audio_retention_days,
            folder=str(audio_store.store_path().resolve()),
            file_count=usage.file_count,
            total_bytes=usage.total_bytes,
        ),
    )


@router.delete("/retained-audio", response_model=DeleteRetainedAudioResponse)
def delete_retained_audio():
    result = audio_store.delete_all()
    return DeleteRetainedAudioResponse(deleted=result.deleted, failed=result.failed)
