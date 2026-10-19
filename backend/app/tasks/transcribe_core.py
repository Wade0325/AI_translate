"""單檔轉錄任務的入口（純同步 Python，與任務框架無關）。

Docker 模式由 `app.celery.task.transcribe_media_task` 包裝執行，免安裝模式由
`app.runtime.in_process.InProcessRunMode.submit_transcription` 丟進行程內執行緒池；
兩邊共用這裡的同一份流程。任務的狀態轉換與副作用在 :mod:`app.tasks.lifecycle`，
這裡只負責「怎麼轉錄」：查出供應商轉接器，經分段轉錄轉錄輸入音檔。
"""

from pathlib import Path

from app.celery.models import TranscriptionTaskParams
from app.core.config import get_settings
from app.core.default_prompt import build_prompt
from app.provider.base import Progress, TranscribeRequest
from app.provider.registry import open_provider
from app.services.transcription.flows import TranscriptionTask
from app.services.transcription.models import TranscriptionTaskResult
from app.tasks.lifecycle import TaskLifecycle
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def run_transcription(task_params_dict: dict, task_uuid: str, retries_left: int = 0) -> dict:
    """單檔轉錄：去靜音 → 轉錄 → 格式轉換 → 計費 → 寫 DB。

    暫時錯誤會往上拋，由執行模式重試（Celery autoretry 或 LocalExecutor 的 retry wrapper）；
    ``retries_left`` 是這次之後還會重試幾次，0 時暫時錯誤照失敗處理。
    """
    params = TranscriptionTaskParams.model_validate(task_params_dict)
    return TaskLifecycle(task_uuid, params, retries_left=retries_left).run(
        lambda audio, progress: _transcribe(params, task_uuid, audio, progress))


def _transcribe(
    params: TranscriptionTaskParams, task_uuid: str, audio: Path, progress: Progress,
) -> TranscriptionTaskResult:
    # 查出供應商轉接器：模型不屬於這個供應商、或供應商還不能轉錄
    # （缺權重、金鑰無效）都在這裡以明確訊息失敗，不必等去靜音跑完
    adapter = open_provider(params.provider, params.model, params.api_keys)
    progress.report("正在初始化模型...")

    chunked = TranscriptionTask(
        provider=adapter,
        request=TranscribeRequest(
            model=params.model,
            prompt=_prompt(params),
            source_lang=params.source_lang,
            service_tier=params.service_tier,
        ),
        progress=progress,
        # 不用 audio.parent：重試時輸入音檔在保留區，暫存檔寫到那裡就清不掉
        temp_dir=get_settings().temp_uploads_path,
        artifact_task_id=str(task_uuid),
        original_filename=params.original_filename,
    )
    try:
        logger.info(f"Starting transcription. Task ID : {task_uuid}")
        return chunked.transcribe_audio(audio)
    finally:
        # 供應商的遠端資源與分段轉錄的暫存檔；輸入音檔由任務生命週期保留或清理
        chunked.cleanup()


def _prompt(params: TranscriptionTaskParams) -> str:
    # 有提供逐字稿時改走「對齊」prompt，只補時間戳不重新轉錄
    if params.original_text:
        return f"""
請你扮演一位專業的逐字稿專家。你的任務是將提供的音檔與以下的完整逐字稿內容進行對齊，並生成一個帶有時間戳的LRC格式檔案。

這是完整的逐字稿：
---
{params.original_text}
---

請仔細聆聽音檔，為這份逐字稿加上精確的時間戳，並以LRC格式輸出。
"""
    return build_prompt(
        source_lang=params.source_lang,
        target_lang=params.target_lang,
        multi_speaker=params.multi_speaker,
        template=params.prompt or None,
    )
