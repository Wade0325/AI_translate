"""本地模型 provider：VibeVoice-ASR 說話者分離 + Qwen3-ASR 轉錄。

僅在主機端 GPU worker（local_asr 佇列）上執行——flows.py 於 provider == "local"
分支內才延遲 import 本模組，Docker 容器 worker 不需要 transformers/CUDA 相依。

流程：
  1. VibeVoice-ASR 對整檔做說話者分離（誰、從幾秒到幾秒）→ 釋放模型
  2. Qwen3-ASR 依分離片段逐段轉錄（日文精度較高，取代 VibeVoice 附帶文字）→ 釋放模型
  3. Qwen3-ForcedAligner 把每段文字對回音訊 → 逐詞時間戳 → 依句尾標點重新斷行，
     時間軸以 ASR 對齊結果為準，說話者標籤繼承所屬分離片段
  4. 組成 LRC：每行「[mm:ss.xx][S{n}] 文字」，時間軸為輸入檔（上游 flows 負責
     remap 回原始檔時間軸）；對齊失敗時退回「一個分離片段一行」

VRAM 策略（16GB 卡）：三個模型依序載入、用完即釋放，不可同時常駐。
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
from typing import Callable, Dict, List, Optional

# HF_HOME 由 weights 模組（權重單一事實來源）於 import 時設定
from app.provider.local.weights import (  # noqa: F401 — re-export 供既有引用
    ALIGNER_MODEL_ID,
    ASR_MODEL_ID,
    DIARIZATION_MODEL_ID,
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
from app.utils.binaries import ffmpeg_bin
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# CPU offload 是 VRAM 策略刻意為之（見 _gpu_weight_limit），不需每次提醒
logging.getLogger("accelerate.big_modeling").setLevel(logging.ERROR)
# transformers 5.13 的 VibeVoice 內部自行傳遞已棄用的 acoustic_tokenizer_chunk_size
# kwarg，呼叫端無法避免，濾掉其 FutureWarning
warnings.filterwarnings(
    "ignore", category=FutureWarning, message=r".*acoustic_tokenizer_chunk_size.*")

DIARIZATION_SAMPLE_RATE = 24000

# 字幕斷行：句尾標點切行；單行超過上限秒數時在讀點處再切
MAX_LINE_SECONDS = 12.0
_SENTENCE_END_RE = re.compile(r"(?<=[。．！？!?…])")
_CLAUSE_END_RE = re.compile(r"(?<=[、，,])")
# 內建斷詞把假名視為空白分隔文字、標點僅丟棄不切分，假名串會跨標點黏成一詞；
# 在斷行標點後補空白強制切開，確保「整段斷詞」與「逐句斷詞」的詞序一致
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


def _notify(status_callback, text: str) -> None:
    if status_callback:
        status_callback(text)


def _raise_if_cancelled(cancel_check: Optional[Callable[[], bool]]) -> None:
    if cancel_check is not None and cancel_check():
        raise TranscriptionCancelledError("使用者已取消任務")


def _make_cancel_stopping_criteria(cancel_check: Optional[Callable[[], bool]]):
    """把取消旗標包成 generate 的 StoppingCriteria。

    長檔 diarization 的單次 generate 可達數分鐘，靠它在解碼途中停下
    （prefill 階段無法中斷，會等第一個 token 出來才開始檢查）；
    每 2 秒最多查一次旗標，避免每個解碼步都打 Redis。
    """
    if cancel_check is None:
        return None
    from transformers import StoppingCriteria, StoppingCriteriaList

    class _CancelCriteria(StoppingCriteria):
        def __init__(self):
            self._last_check = 0.0
            self._cancelled = False

        def __call__(self, input_ids, scores, **kwargs):
            now = time.monotonic()
            if not self._cancelled and now - self._last_check >= 2.0:
                self._last_check = now
                self._cancelled = bool(cancel_check())
            return self._cancelled

    return StoppingCriteriaList([_CancelCriteria()])


def _free_model(*objects) -> None:
    import torch
    for obj in objects:
        del obj
    gc.collect()
    torch.cuda.empty_cache()


def _lrc_timestamp(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"[{minutes:02d}:{seconds - minutes * 60:05.2f}]"


def _to_mono_24k(audio_path: Path) -> Path:
    """轉成 VibeVoice 要求的 mono 24kHz wav 暫存檔。"""
    output = audio_path.parent / f"{audio_path.stem}_diar24k.wav"
    result = subprocess.run(
        [ffmpeg_bin(), "-y", "-i", str(audio_path),
         "-ac", "1", "-ar", str(DIARIZATION_SAMPLE_RATE), str(output)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 轉 24kHz 失敗: {result.stderr.strip()[-200:]}")
    return output


def _run_diarization(wav_path: Path, cancel_check=None) -> List[dict]:
    """VibeVoice-ASR 整檔說話者分離，回傳 [{Start, End, Speaker, ...}]。"""
    import torch
    from transformers import AutoProcessor, VibeVoiceAsrForConditionalGeneration

    info = sf.info(str(wav_path))
    gpu_limit = _gpu_weight_limit(info.duration)
    logger.info(f"音檔 {info.duration:.0f}s，GPU 權重上限 {gpu_limit}")

    processor = AutoProcessor.from_pretrained(DIARIZATION_MODEL_ID)
    model = VibeVoiceAsrForConditionalGeneration.from_pretrained(
        DIARIZATION_MODEL_ID,
        device_map="auto",
        dtype=torch.bfloat16,
        max_memory={0: gpu_limit, "cpu": "26GiB"},
    )
    model.eval()

    try:
        inputs = processor.apply_transcription_request(audio=str(wav_path))
        inputs = inputs.to(model.device).to(torch.bfloat16)
        with torch.inference_mode():
            output_ids = model.generate(
                **inputs, max_new_tokens=8192,
                stopping_criteria=_make_cancel_stopping_criteria(cancel_check))
        # 取消可能是 generate 中途被 StoppingCriteria 停下，輸出不完整，
        # 必須在 decode 前中止
        _raise_if_cancelled(cancel_check)
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
    status_callback=None,
    cancel_check=None,
) -> List[dict]:
    """Qwen3-ASR 逐段轉錄，回傳 [{start, end, speaker, text}]（輸入檔時間軸）。"""
    import torch
    from transformers import AutoProcessor, Qwen3ASRForConditionalGeneration

    processor = AutoProcessor.from_pretrained(ASR_MODEL_ID)
    model = Qwen3ASRForConditionalGeneration.from_pretrained(
        ASR_MODEL_ID, device_map="auto", dtype=torch.bfloat16,
    )
    model.eval()

    audio_data, sr = sf.read(str(wav_path), dtype="float32")
    segment_wav = wav_path.parent / f"{wav_path.stem}_seg.wav"
    entries: List[dict] = []

    try:
        total = len(segments)
        for i, seg in enumerate(segments, 1):
            _raise_if_cancelled(cancel_check)
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
                output_ids = model.generate(**inputs, max_new_tokens=512)
            generated_ids = output_ids[:, inputs["input_ids"].shape[1]:]
            text = processor.decode(
                generated_ids, return_format="transcription_only")[0].strip()

            if text:
                entries.append(
                    {"start": start, "end": end, "speaker": speaker, "text": text})
            if i % 10 == 0 or i == total:
                _notify(status_callback, f"本地模型：Qwen3-ASR 轉錄中 {i}/{total}...")
    finally:
        _free_model(model, processor)
        segment_wav.unlink(missing_ok=True)

    return entries


def _split_keep_delimiters(text: str, pattern: re.Pattern) -> List[str]:
    """依標點切開並保留標點於前段尾端，濾掉空白片段。"""
    return [part for part in pattern.split(text) if part.strip()]


def _align_segments(
    wav_path: Path,
    entries: List[dict],
    status_callback=None,
    cancel_check=None,
):
    """Qwen3-ForcedAligner 逐段強制對齊，將逐詞時間戳寫入 entry["words"]。

    詞的時間為「該段內」相對秒數；斷詞用內建逐字模式（language=None，
    不依賴 nagisa），對字幕級精度足夠。回傳 aligner 的 processor 供斷行
    時以相同斷詞方式計數。
    """
    import torch
    from transformers import AutoProcessor, Qwen3ASRForTokenClassification

    processor = AutoProcessor.from_pretrained(ALIGNER_MODEL_ID)
    model = Qwen3ASRForTokenClassification.from_pretrained(
        ALIGNER_MODEL_ID, device_map="auto", dtype=torch.bfloat16,
    )
    model.eval()

    audio_data, sr = sf.read(str(wav_path), dtype="float32")
    segment_wav = wav_path.parent / f"{wav_path.stem}_align.wav"

    try:
        total = len(entries)
        for i, entry in enumerate(entries, 1):
            # 取消檢查必須在 per-segment try 之外，否則會被當成對齊失敗吞掉
            _raise_if_cancelled(cancel_check)
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
                _notify(status_callback, f"本地模型：時間軸對齊中 {i}/{total}...")
    finally:
        # processor 為 CPU 端物件不佔 VRAM，保留供斷行時以相同斷詞方式計數
        _free_model(model)
        segment_wav.unlink(missing_ok=True)

    return processor


def _entry_to_lines(entry: dict, count_words) -> List[str]:
    """把一個轉錄片段依對齊結果斷成多行 LRC；無對齊資料時退回單行。

    count_words: 文字 → 對齊詞數。必須與 _align_segments 餵給
    prepare_forced_aligner_inputs 的斷詞方式一致（先 _insert_align_breaks
    再 split_words_for_alignment），才能把文字單元對應回對齊詞序列的位置。
    """
    speaker_tag = f"[S{entry['speaker']}]"
    fallback = [f"{_lrc_timestamp(entry['start'])}{speaker_tag} {entry['text']}"]

    words = entry.get("words")
    if not words:
        return fallback

    sentences = _split_keep_delimiters(entry["text"], _SENTENCE_END_RE)
    if not sentences:
        return fallback

    # 每個句子再展開成 (文字, 詞數)；過長句子在讀點處細分
    units: List[tuple] = []
    for sentence in sentences:
        units.append((sentence, count_words(sentence)))

    if sum(n for _, n in units) != len(words):
        logger.warning("斷行詞數與對齊詞數不一致，退回片段時間戳")
        return fallback

    lines: List[str] = []
    offset = 0
    pending_text = ""       # 純標點單元（詞數 0）併入下一行行首
    for text, count in units:
        if count == 0:
            pending_text += text
            continue
        unit_start = words[offset]["start_time"]
        unit_end = words[offset + count - 1]["end_time"]

        pieces = [(pending_text + text, offset, count)]
        pending_text = ""
        if unit_end - unit_start > MAX_LINE_SECONDS:
            pieces = _split_long_unit(pieces[0][0], offset, words, count_words)

        for piece_text, piece_offset, _ in pieces:
            start = entry["start"] + words[piece_offset]["start_time"]
            lines.append(f"{_lrc_timestamp(start)}{speaker_tag} {piece_text.strip()}")
        offset += count

    # 結尾殘留的純標點單元（如末尾省略號）併入最後一行
    if pending_text and lines:
        lines[-1] += pending_text

    return lines or fallback


def _split_long_unit(text: str, offset: int, words: List[dict], count_words) -> List[tuple]:
    """過長句子在讀點（、，,）處切成多行，每行不超過 MAX_LINE_SECONDS。

    回傳 [(文字, 詞序起點, 詞數)]；無法細分時整句一行。
    """
    clauses = _split_keep_delimiters(text, _CLAUSE_END_RE)
    if len(clauses) < 2:
        return [(text, offset, count_words(text))]

    pieces: List[tuple] = []
    cur_text, cur_offset, cur_count, cur_start = "", None, 0, None
    pos = offset
    for clause in clauses:
        n = count_words(clause)
        if n == 0:
            cur_text += clause
            continue
        clause_end = words[pos + n - 1]["end_time"]
        if cur_offset is not None and clause_end - cur_start > MAX_LINE_SECONDS:
            pieces.append((cur_text, cur_offset, cur_count))
            cur_text, cur_offset, cur_count = "", None, 0
        if cur_offset is None:
            cur_offset = pos
            cur_start = words[pos]["start_time"]
        cur_text += clause
        cur_count += n
        pos += n
    if cur_text:
        pieces.append((cur_text, cur_offset if cur_offset is not None else offset, cur_count))
    return pieces


def _build_lrc_lines(
    wav_path: Path,
    entries: List[dict],
    status_callback=None,
    cancel_check=None,
) -> List[str]:
    """強制對齊 + 依句斷行；對齊流程整體失敗時退回「一個片段一行」。"""
    try:
        _notify(status_callback, "本地模型：Qwen3-ForcedAligner 時間軸對齊中...")
        aligner_processor = _align_segments(
            wav_path, entries, status_callback, cancel_check)
    except TranscriptionCancelledError:
        raise
    except Exception as e:
        logger.warning(f"強制對齊不可用，全部退回片段時間戳: {e}")
        return [
            f"{_lrc_timestamp(entry['start'])}[S{entry['speaker']}] {entry['text']}"
            for entry in entries
        ]

    def count_words(text: str) -> int:
        return len(aligner_processor.split_words_for_alignment(
            _insert_align_breaks(text), None))

    lines: List[str] = []
    for entry in entries:
        lines.extend(_entry_to_lines(entry, count_words))
    return lines


def transcribe_with_local_models(
    audio_path: Path,
    source_lang: Optional[str] = None,
    status_callback=None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict:
    """對單一音訊檔執行分離＋轉錄，回傳與 Gemini provider 相同合約的 dict。

    cancel_check 回傳 True 時在各檢查點拋出 TranscriptionCancelledError；
    各階段的 finally 會照常釋放模型與暫存檔。
    """
    language = _LANGUAGE_MAP.get((source_lang or "").strip().lower())
    wav_24k: Optional[Path] = None

    try:
        _notify(status_callback, "本地模型：準備音訊...")
        wav_24k = _to_mono_24k(audio_path)
        _raise_if_cancelled(cancel_check)

        _notify(status_callback, "本地模型：VibeVoice-ASR 說話者分離中（長檔需較久）...")
        segments = _run_diarization(wav_24k, cancel_check)
        speakers = {int(s.get("Speaker", 0)) for s in segments}
        logger.info(f"說話者分離完成: {len(segments)} 段, {len(speakers)} 位說話者")

        _notify(status_callback,
                f"本地模型：分離完成（{len(speakers)} 位說話者），Qwen3-ASR 轉錄中...")
        entries = _transcribe_segments(
            wav_24k, segments, language, status_callback, cancel_check)
        lines = _build_lrc_lines(wav_24k, entries, status_callback, cancel_check)

        return {
            "success": bool(lines),
            "text": "\n".join(lines),
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "service_tier_used": "local",
        }
    finally:
        if wav_24k:
            wav_24k.unlink(missing_ok=True)
