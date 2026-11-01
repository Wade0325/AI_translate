"""本機供應商（local provider）：說話者分離 + 轉錄 + 強制對齊。

Docker 模式下只在主機端 GPU worker（local_asr 佇列）上執行，免安裝模式則在行程內的
local_asr 執行緒池執行——本機轉接器（provider.py）第一次轉錄時才延遲 import 本模組，
Docker 容器 worker 不需要 transformers/CUDA 相依。

三種模型（畫面列出的本機模型，見 GET /providers；權重對照見 weights.MODEL_REPOS）：
  * moss-align（預設）：MOSS-Transcribe-Diarize 一次產生說話者、時間與文字，
    再由 Qwen3-ForcedAligner 斷行並補逐詞時間戳
  * moss-qwen3-asr：MOSS 分離後，文字改由 Qwen3-ASR 逐段轉錄（MOSS 文字留作 text_alt）
  * vibevoice-qwen3-asr（舊版）：VibeVoice-ASR 分離 + Qwen3-ASR 逐段轉錄

共同的後段：
  1. Qwen3-ForcedAligner 把每段文字對回音訊 → 逐詞時間戳；對齊失敗的段沒有逐字時間
  2. 整理成片段：說話者編號、起訖時間、文字與逐字時間，時間軸為輸入檔（上游的分段轉錄
     負責還原回原音檔的時間軸）。依句尾標點斷行、四種輸出格式都由輸出格式模組
     （app.services.output_format）從片段產生

VRAM 策略：各模型依序載入、用完即釋放，不可同時常駐。依音檔長度把部分權重
放到 CPU（_gpu_weight_limit）只有舊版 VibeVoice 會用到。
"""

from __future__ import annotations

import gc
import logging
import os
import re
import subprocess
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional

from app.core.error_codes import ErrorCode
# HF_HOME 由 weights 模組（權重單一事實來源）於 import 時設定
from app.provider.local.weights import (  # noqa: F401 — re-export 供既有引用
    ALIGNER_MODEL_ID,
    ASR_MODEL_ID,
    DIARIZATION_MODEL_ID,
    MOSS_ALIGN,
    is_moss_model,
    load_pretrained,
    normalize_model,
    notice_if_missing,
)
# 權重載入進度條的每次刷新在 Celery 日誌都是一行 WARNING，關閉
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
# transformers 只留 error。被消音的提示皆已逐一確認無害：
# - max_new_tokens 與模型內建 generation config 的 max_length 同時存在
#   （前者優先，即預期行為）
# - "exceeded maximum length (450)" 為誤報：450 是 VibeVoiceAsrConfig 把
#   acoustic tokenizer 每 60s chunk 的音訊 token 數（1440000/3200）暴露成
#   max_position_embeddings 所致，文字解碼器實際上限為 131072
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

import soundfile as sf

from app.exceptions import TranscriptionCancelledError
from app.provider.base import ProgressAndCancel
from app.utils.audio import FFMPEG_ERRORS_ONLY
from app.utils.binaries import ffmpeg_bin
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# CPU offload 是 VRAM 策略刻意為之（見 _gpu_weight_limit），不需每次提醒
logging.getLogger("accelerate.big_modeling").setLevel(logging.ERROR)
# transformers 5.13 的 VibeVoice 內部自行傳遞已棄用的 acoustic_tokenizer_chunk_size
# kwarg，呼叫端無法避免，濾掉其 FutureWarning
warnings.filterwarnings(
    "ignore", category=FutureWarning, message=r".*acoustic_tokenizer_chunk_size.*")

DIARIZATION_SAMPLE_RATE = 24000   # VibeVoice 要求 24 kHz
MOSS_SAMPLE_RATE = 16000          # MOSS（Whisper 前端）16 kHz；Qwen3-ASR／對齊器會自行重採樣

# 內建斷詞把假名視為空白分隔文字、標點僅丟棄不切分，假名串會跨標點黏成一詞；
# 在斷行標點後補空白強制切開，確保「整段斷詞」與「逐句斷詞」的詞序一致
# （輸出格式模組斷行時照同樣的規則逐句斷詞，才對得上存下來的逐字時間）
_ALIGN_BREAK_RE = re.compile(r"([。．！？!?…、，,])")


def _insert_align_breaks(text: str) -> str:
    return _ALIGN_BREAK_RE.sub(r"\1 ", text)


def _gpu_weight_limit(duration_seconds: float) -> str:
    """依音檔長度決定 bf16 權重的 GPU 上限：越長的檔 KV cache 越大，
    要把更多權重擠去 CPU 讓出 VRAM（實測 10.5 分鐘 @11GiB 峰值 15.95GB/16GB）。"""
    if duration_seconds <= 480:
        return "11GiB"
    if duration_seconds <= 900:
        return "9GiB"
    return "7GiB"

_LANGUAGE_MAP = {
    "ja": "Japanese", "japanese": "Japanese", "日文": "Japanese", "日本語": "Japanese",
    "zh": "Chinese", "zh-tw": "Chinese", "zh-cn": "Chinese",
    "chinese": "Chinese", "中文": "Chinese", "繁體中文": "Chinese",
    "en": "English", "english": "English", "英文": "English",
    "ko": "Korean", "korean": "Korean", "韓文": "Korean",
}


def _make_cancel_stopping_criteria(progress: ProgressAndCancel):
    """用進度與取消物件產生 generate 的停止生成條件（StoppingCriteria）。

    長檔 diarization 的單次 generate 可達數分鐘，靠它在解碼途中停下
    （prefill 階段無法中斷，會等第一個 token 出來才開始檢查）；
    每 2 秒最多查一次取消，避免每個解碼步都打 Redis。
    """
    from transformers import StoppingCriteria, StoppingCriteriaList

    class _CancelCriteria(StoppingCriteria):
        def __init__(self):
            self._last_check = 0.0
            self._cancelled = False

        def __call__(self, input_ids, scores, **kwargs):
            now = time.monotonic()
            if not self._cancelled and now - self._last_check >= 2.0:
                self._last_check = now
                self._cancelled = progress.cancel_requested()
            return self._cancelled

    return StoppingCriteriaList([_CancelCriteria()])


def _free_model(*objects) -> None:
    import torch
    for obj in objects:
        del obj
    gc.collect()
    torch.cuda.empty_cache()


def _to_mono(audio_path: Path, sample_rate: int) -> Path:
    """轉成分離模型要求取樣率的 mono wav 暫存檔（VibeVoice 24 kHz、MOSS 16 kHz）。"""
    output = audio_path.parent / f"{audio_path.stem}_mono{sample_rate // 1000}k.wav"
    result = subprocess.run(
        [ffmpeg_bin(), *FFMPEG_ERRORS_ONLY, "-y", "-i", str(audio_path),
         "-ac", "1", "-ar", str(sample_rate), str(output)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg 轉 {sample_rate // 1000}kHz 失敗: {result.stderr.strip()[-200:]}")
    return output


def _run_moss(wav_path: Path, progress: ProgressAndCancel) -> List[dict]:
    """MOSS 一次產生說話者、時間與文字，回傳與 VibeVoice 相同結構的片段。"""
    from app.provider.local import moss

    segments, _ = moss.transcribe(
        wav_path,
        stopping_criteria=_make_cancel_stopping_criteria(progress),
        status_callback=progress.report)
    # generate 可能因為取消而中途停下，輸出不完整，必須在使用前中止
    progress.raise_if_cancelled()
    return segments


def _entries_from_segments(segments: List[dict]) -> List[dict]:
    """moss-align：直接採用 MOSS 的文字，不再經 Qwen3-ASR 轉錄（沒有第二份假設）。

    parse_output 已丟棄空文字片段；這裡再擋一次是因為對齊器不能處理空文字。
    """
    return [
        {"start": float(seg["Start"]), "end": float(seg["End"]),
         "speaker": int(seg.get("Speaker", 0)), "text": seg["Content"], "text_alt": None}
        for seg in segments if (seg.get("Content") or "").strip()
    ]


def _run_diarization(wav_path: Path, progress: ProgressAndCancel) -> List[dict]:
    """VibeVoice-ASR 整檔說話者分離，回傳 [{Start, End, Speaker, ...}]。"""
    import torch
    from transformers import AutoProcessor, VibeVoiceAsrForConditionalGeneration

    info = sf.info(str(wav_path))
    gpu_limit = _gpu_weight_limit(info.duration)
    logger.info(f"音檔 {info.duration:.0f}s，GPU 權重上限 {gpu_limit}")

    notice_if_missing(DIARIZATION_MODEL_ID, "VibeVoice-ASR", progress.report)
    processor = load_pretrained(DIARIZATION_MODEL_ID, AutoProcessor.from_pretrained)
    model = load_pretrained(
        DIARIZATION_MODEL_ID,
        lambda path: VibeVoiceAsrForConditionalGeneration.from_pretrained(
            path,
            device_map="auto",
            dtype=torch.bfloat16,
            max_memory={0: gpu_limit, "cpu": "26GiB"},
        ))
    model.eval()

    try:
        inputs = processor.apply_transcription_request(audio=str(wav_path))
        inputs = inputs.to(model.device).to(torch.bfloat16)
        with torch.inference_mode():
            output_ids = model.generate(
                **inputs, max_new_tokens=8192,
                stopping_criteria=_make_cancel_stopping_criteria(progress))
        # 取消可能是 generate 中途被 StoppingCriteria 停下，輸出不完整，
        # 必須在 decode 前中止
        progress.raise_if_cancelled()
        generated_ids = output_ids[:, inputs["input_ids"].shape[1]:]
        segments = processor.decode(generated_ids, return_format="parsed")[0]
    finally:
        _free_model(model, processor)

    if isinstance(segments, dict):
        segments = [segments]
    if not isinstance(segments, list):
        raise RuntimeError(f"VibeVoice 輸出無法解析為片段列表: {type(segments)}")
    return segments


def _write_segment_wav(audio_data, sr: int, start: float, end: float, path: Path) -> bool:
    """把 [start, end) 區間切片寫成暫存 wav，空片段回傳 False。"""
    piece = audio_data[int(start * sr):int(end * sr)]
    if not len(piece):
        return False
    sf.write(str(path), piece, sr)
    return True


def _transcribe_segments(
    wav_path: Path,
    segments: List[dict],
    language: Optional[str],
    progress: ProgressAndCancel,
) -> List[dict]:
    """Qwen3-ASR 逐段轉錄，回傳 [{start, end, speaker, text}]（輸入檔時間軸）。"""
    import torch
    from transformers import AutoProcessor, Qwen3ASRForConditionalGeneration

    notice_if_missing(ASR_MODEL_ID, "Qwen3-ASR", progress.report)
    processor = load_pretrained(ASR_MODEL_ID, AutoProcessor.from_pretrained)
    model = load_pretrained(
        ASR_MODEL_ID,
        lambda path: Qwen3ASRForConditionalGeneration.from_pretrained(
            path, device_map="auto", dtype=torch.bfloat16))
    model.eval()

    audio_data, sr = sf.read(str(wav_path), dtype="float32")
    segment_wav = wav_path.parent / f"{wav_path.stem}_seg.wav"
    entries: List[dict] = []

    try:
        total = len(segments)
        for i, seg in enumerate(segments, 1):
            progress.raise_if_cancelled()
            start = float(seg.get("Start", 0.0))
            end = float(seg.get("End", 0.0))
            speaker = int(seg.get("Speaker", 0))

            if not _write_segment_wav(audio_data, sr, start, end, segment_wav):
                continue

            request_kwargs = {"audio": str(segment_wav)}
            if language:
                request_kwargs["language"] = language
            inputs = processor.apply_transcription_request(**request_kwargs)
            inputs = inputs.to(model.device).to(torch.bfloat16)
            with torch.inference_mode():
                # 至少 512；長片段按每秒 16 token 放寬（語速再快約 8 字/秒），避免尾端被截掉
                output_ids = model.generate(
                    **inputs, max_new_tokens=max(512, int((end - start) * 16)))
            generated_ids = output_ids[:, inputs["input_ids"].shape[1]:]
            text = processor.decode(
                generated_ids, return_format="transcription_only")[0].strip()

            if text:
                entries.append({
                    "start": start, "end": end, "speaker": speaker, "text": text,
                    # 分離模型（VibeVoice 或 MOSS）本來就會產出文字，留著當第二份假設：
                    # 與 Qwen 不一致處就是需要人工複查的候選
                    "text_alt": (seg.get("Content") or "").strip() or None,
                })
            if i % 10 == 0 or i == total:
                progress.report(f"本機模型：Qwen3-ASR 轉錄中 {i}/{total}...")
    finally:
        _free_model(model, processor)
        segment_wav.unlink(missing_ok=True)

    return entries


def _align_segments(
    wav_path: Path,
    entries: List[dict],
    progress: ProgressAndCancel,
):
    """Qwen3-ForcedAligner 逐段強制對齊，將逐詞時間戳寫入 entry["words"]。

    詞的時間為「該段內」相對秒數；斷詞用內建逐字模式（language=None，
    不依賴 nagisa），對字幕級精度足夠。
    """
    import torch
    from transformers import AutoProcessor, Qwen3ASRForTokenClassification

    notice_if_missing(ALIGNER_MODEL_ID, "Qwen3-ForcedAligner", progress.report)
    processor = load_pretrained(ALIGNER_MODEL_ID, AutoProcessor.from_pretrained)
    model = load_pretrained(
        ALIGNER_MODEL_ID,
        lambda path: Qwen3ASRForTokenClassification.from_pretrained(
            path, device_map="auto", dtype=torch.bfloat16))
    model.eval()

    audio_data, sr = sf.read(str(wav_path), dtype="float32")
    segment_wav = wav_path.parent / f"{wav_path.stem}_align.wav"

    try:
        total = len(entries)
        for i, entry in enumerate(entries, 1):
            # 取消檢查必須在 per-segment try 之外，否則會被當成對齊失敗吞掉
            progress.raise_if_cancelled()
            entry["words"] = None
            if not _write_segment_wav(
                    audio_data, sr, entry["start"], entry["end"], segment_wav):
                continue
            try:
                inputs, word_lists = processor.prepare_forced_aligner_inputs(
                    audio=str(segment_wav),
                    transcript=_insert_align_breaks(entry["text"]),
                    language=None)
                inputs.pop("num_audio_tokens", None)
                inputs = inputs.to(model.device).to(torch.bfloat16)
                with torch.inference_mode():
                    logits = model(**inputs).logits
                entry["words"] = processor.decode_forced_alignment(
                    logits, inputs["input_ids"], word_lists,
                    model.config.timestamp_token_id)[0]
            except Exception as e:
                logger.warning(f"片段 {i}/{total} 強制對齊失敗，退回片段時間戳: {e}")
            if i % 10 == 0 or i == total:
                progress.report(f"本機模型：強制對齊中 {i}/{total}...")
    finally:
        _free_model(model, processor)
        segment_wav.unlink(missing_ok=True)


def _align_with_fallback(
    wav_path: Path,
    entries: List[dict],
    progress: ProgressAndCancel,
) -> None:
    """強制對齊，把逐字時間寫進各段；對齊流程整體失敗時不拋例外，只通知使用者，沒對到的段
    不帶逐字時間，輸出格式模組把它們整段當成一行。"""
    try:
        progress.report("本機模型：Qwen3-ForcedAligner 強制對齊中...")
        _align_segments(wav_path, entries, progress)
    except TranscriptionCancelledError:
        raise
    except Exception as e:
        logger.warning(f"強制對齊不可用，全部退回片段時間戳: {e}")
        # 結果仍可用但少了斷行與逐字時間（例如對齊器首次下載失敗），讓使用者看得到
        progress.report("本機模型：強制對齊不可用，改以片段為單位輸出（詳見日誌）")


def _build_segment_records(entries: List[dict], source: str = "qwen") -> List[dict]:
    """把片段整理成上層要持久化的結構（時間軸＝輸入檔，由分段轉錄平移、還原回原音檔）。

    ``seg_key`` 是序號而非時間，因為重新轉錄時片段順序穩定、時間可能微幅
    浮動；以序號為鍵才能覆寫而不是長出重複資料。``source`` 記錄主要文字的來源模型。
    """
    records: List[dict] = []
    for i, e in enumerate(entries):
        words = [
            {"text": w.get("text"),
             "start": e["start"] + w["start_time"],
             "end": e["start"] + w["end_time"]}
            for w in (e.get("words") or [])
            if w.get("start_time") is not None and w.get("end_time") is not None
        ]
        records.append({
            "seg_key": f"{i:04d}",
            "seq": i,
            "start": e["start"],
            "end": e["end"],
            "speaker": f"S{e['speaker']}",
            "text": e["text"],
            "text_alt": e.get("text_alt"),
            "source": source,
            "words": words or None,
        })
    return records


def transcribe_with_local_models(
    audio_path: Path,
    source_lang: Optional[str],
    progress: ProgressAndCancel,
    model: Optional[str] = None,
) -> Dict:
    """對單一音訊檔執行分離＋轉錄，回傳轉錄結果（片段與用量）的 dict，不附著 LRC 文字。

    model 為前端 Local 選項（見模組說明）；未指定或不認得時用預設的 moss-align。
    使用者取消時，各檢查點經 ``progress`` 拋出 TranscriptionCancelledError；
    各階段的 finally 會照常釋放模型與暫存檔。
    """
    model = normalize_model(model)
    use_moss = is_moss_model(model)
    language = _LANGUAGE_MAP.get((source_lang or "").strip().lower())
    wav: Optional[Path] = None

    try:
        progress.report("本機模型：準備音訊...")
        wav = _to_mono(audio_path, MOSS_SAMPLE_RATE if use_moss else DIARIZATION_SAMPLE_RATE)
        progress.raise_if_cancelled()

        if use_moss:
            progress.report("本機模型：MOSS 轉錄與說話者分離中...")
            segments = _run_moss(wav, progress)
        else:
            progress.report("本機模型：VibeVoice-ASR 說話者分離中（長檔需較久）...")
            segments = _run_diarization(wav, progress)
        speakers = {int(s.get("Speaker", 0)) for s in segments}
        logger.info(f"說話者分離完成: {len(segments)} 段, {len(speakers)} 位說話者 (model={model})")

        if model == MOSS_ALIGN:
            entries = _entries_from_segments(segments)
            source = "moss"
        else:
            progress.report(
                f"本機模型：說話者分離完成（{len(speakers)} 位說話者），Qwen3-ASR 轉錄中...")
            entries = _transcribe_segments(wav, segments, language, progress)
            source = "qwen"
        _align_with_fallback(wav, entries, progress)
        records = _build_segment_records(entries, source)

        return {
            # 本機沒有內容時照舊算失敗（分段轉錄時整個任務失敗），只是寫明原因
            "success": bool(records),
            "text": "" if records else "本機的模型沒有轉錄出任何內容",
            "error_code": None if records else ErrorCode.NO_TRANSCRIPT,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "service_tier_used": "local",
            "segments": records,
        }
    finally:
        if wav:
            wav.unlink(missing_ok=True)
