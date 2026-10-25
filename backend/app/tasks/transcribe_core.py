"""單檔轉錄任務的入口（純同步 Python，與任務框架無關）。

Docker 模式由 `app.celery.task.transcribe_media_task` 包裝執行，免安裝模式由
`app.runtime.in_process.InProcessRunMode.submit_transcription` 丟進行程內執行緒池；
兩邊共用這裡的同一份流程。任務的狀態轉換與副作用在 :mod:`app.tasks.lifecycle`，
這裡只負責「怎麼轉錄」：查出供應商轉接器、去靜音拿到語音視圖，經分段轉錄轉錄它。
語音視圖與轉接器由這裡建立，也由這裡清理與釋放。
"""

from pathlib import Path

from app.celery.models import TranscriptionTaskParams
from app.core.config import get_settings
from app.core.default_prompt import build_prompt
from app.provider.base import ProgressAndCancel, Provider, TranscribeRequest
from app.provider.registry import open_provider
from app.services import chunked_transcription
from app.services.silence_removal import speech_view
from app.services.transcription.models import TranscriptionTaskResult
from app.tasks.lifecycle import Task, TaskLifecycle
from app.utils.audio import get_audio_duration
from app.utils.logger import setup_logger
from app.utils.paths import delete_temp_files

logger = setup_logger(__name__)


def run_transcription(task_params_dict: dict, task_uuid: str) -> dict:
    """單檔轉錄：去靜音 → 轉錄 → 格式轉換 → 計費 → 寫 DB。

    暫時錯誤在分段轉錄裡重試出錯的那一段，執行模式不重試整個任務。
    """
    params = TranscriptionTaskParams.model_validate(task_params_dict)
    return TaskLifecycle(task_uuid, _task(params)).run(
        lambda audio, progress: transcribe_audio(params, task_uuid, audio, progress))


def abandon_transcription(task_params_dict: dict, task_uuid: str, *, cancelled: bool) -> None:
    """收尾一個不會再執行的單檔任務（見 :meth:`TaskLifecycle.abandon`）。

    執行模式在任務不會再執行時呼叫：在佇列中被撤銷（``cancelled``），或應用程式關閉時還在排隊。
    """
    params = TranscriptionTaskParams.model_validate(task_params_dict)
    TaskLifecycle(task_uuid, _task(params)).abandon(cancelled=cancelled)


def _task(params: TranscriptionTaskParams) -> Task:
    return Task(
        file_path=params.file_path,
        file_uid=params.file_uid,
        client_id=params.client_id,
        original_filename=params.original_filename,
        provider=params.provider,
        model=params.model,
        source_lang=params.source_lang,
        target_lang=params.target_lang,
        session_id=params.session_id,
    )


def transcribe_audio(
    params: TranscriptionTaskParams, task_uuid: str, audio: Path, progress: ProgressAndCancel,
) -> TranscriptionTaskResult:
    """轉錄一段音檔：建立供應商轉接器，去靜音拿到語音視圖，經分段轉錄轉錄它，最後釋放轉接器。

    不碰任務紀錄與狀態廣播（那些在任務生命週期）；評測指令（``python -m tools.eval transcribe``）
    也直接呼叫這裡，評的就是正式的轉錄路徑。

    暫存檔寫在設定的 ``temp_uploads_path``，呼叫端要先建立它：應用程式由 API 模組在 import 時
    建立。資料夾不存在時 WAV 以外的音檔轉不成 WAV，去靜音會退回送原音檔。
    """
    # 查出供應商轉接器：模型不屬於這個供應商、或供應商還不能轉錄
    # （缺權重、金鑰無效）都在這裡以明確訊息失敗，不必等去靜音跑完
    adapter = open_provider(params.provider, params.model, params.api_keys)
    try:
        progress.report("正在初始化模型...")
        logger.info(f"Starting transcription. Task ID : {task_uuid}")
        return _transcribe_speech_view(adapter, params, task_uuid, audio, progress)
    finally:
        # 供應商這次用到的遠端與暫存資源；輸入音檔由任務生命週期保留或清理
        try:
            adapter.release()
        except Exception as e:
            logger.warning(f"釋放供應商資源失敗: {e}")


def _transcribe_speech_view(
    adapter: Provider, params: TranscriptionTaskParams, task_uuid: str, audio: Path,
    progress: ProgressAndCancel,
) -> TranscriptionTaskResult:
    """去靜音拿到語音視圖，經分段轉錄轉錄它；語音視圖的暫存檔用完就清掉。"""
    duration = get_audio_duration(audio)
    if duration is None:
        logger.error(f"無法取得音訊時長 {audio.name}")
        return TranscriptionTaskResult(success=False, text=f"[[無法讀取檔案 {audio.name}]]")

    # 不用 audio.parent：同一個任務再執行一次時（Docker 模式的重派）輸入音檔在保留區，
    # 暫存檔寫到那裡就清不掉
    temp_dir = get_settings().temp_uploads_path
    original_filename = params.original_filename or audio.name
    progress.report("分析語音活動...")
    view = speech_view(
        audio,
        duration,
        remove_silence=adapter.capabilities()[params.model].remove_silence,
        temp_dir=temp_dir,
        task_id=str(task_uuid),
        original_filename=original_filename,
    )
    try:
        return chunked_transcription.transcribe(
            view,
            adapter,
            TranscribeRequest(
                model=params.model,
                prompt=_prompt(params),
                source_lang=params.source_lang,
                service_tier=params.service_tier,
            ),
            progress,
            temp_dir=temp_dir,
            task_id=str(task_uuid),
            original_filename=original_filename,
        )
    finally:
        # 轉成的 wav、只剩語音的音檔
        delete_temp_files(view.temp_files)


def _prompt(params: TranscriptionTaskParams) -> str:
    # 有使用者文稿時改用「對齊」的提示詞：只補時間戳，不重新轉錄
    if params.original_text:
        return f"""
請你扮演一位專業的逐字稿專家。你的任務是將提供的音檔與以下的完整逐字稿內容進行對齊，並生成一個帶有時間戳的LRC格式檔案。

這是完整的逐字稿：
---
{params.original_text}
---

請仔細聆聽音檔，為這份逐字稿加上精確的時間戳，並以LRC格式輸出。
"""
    # 設定頁存的提示詞範本，空一行接上轉錄頁填的補充說明（#144）
    return build_prompt(
        source_lang=params.source_lang,
        target_lang=params.target_lang,
        multi_speaker=params.multi_speaker,
        template=params.prompt_template,
        supplement=params.prompt,
    )
