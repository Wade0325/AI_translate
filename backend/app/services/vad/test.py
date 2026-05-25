"""VAD 切割測試 — 僅執行前處理，不呼叫 Gemini 轉錄。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from app.core.config import get_settings
from app.services.vad.artifacts import persist_speech_extraction, persist_split
from app.services.vad.preprocess import run_vad_extraction
from app.services.vad.service import get_vad_service
from app.utils.audio import convert_to_wav, get_audio_duration
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _cleanup_paths(paths: list[Path]) -> None:
    for path in paths:
        try:
            if path.exists() and "temp_uploads" in str(path):
                path.unlink()
        except Exception as e:
            logger.warning(f"清理 VAD 測試暫存檔失敗 ({path.name}): {e}")


def run_vad_test(
    file_path: Path,
    *,
    original_filename: str,
    include_split: bool = True,
) -> dict[str, Any]:
    """
    對單一音檔執行 VAD 測試：
      1. 靜音移除 → speech_only.wav
      2. （可選）靜音分割 → part1.wav / part2.wav

    產物一律保存到 vad_artifacts/（不受 VAD_KEEP_ARTIFACTS 開關限制）。
    """
    temp_dir = file_path.parent
    task_id = uuid.uuid4().hex[:12]
    settings = get_settings()
    threshold = settings.vad_speech_ratio_skip_threshold
    to_cleanup: list[Path] = []

    try:
        vad_service = get_vad_service()
    except Exception as e:
        return {"success": False, "error": f"VAD 服務不可用: {e}"}

    total_duration = get_audio_duration(file_path) or 0.0
    extraction_payload: Optional[dict[str, Any]] = None
    split_payload: Optional[dict[str, Any]] = None
    artifact_dir: Optional[str] = None

    # --- 1. 靜音移除 ---
    extract_result = run_vad_extraction(file_path, temp_dir, vad_service)
    to_cleanup.extend(extract_result.cleanup_files)

    if extract_result.success and extract_result.speech_only_path:
        used = extract_result.speech_ratio < threshold
        saved = persist_speech_extraction(
            task_id=task_id,
            original_filename=original_filename,
            speech_only_path=extract_result.speech_only_path,
            segments=extract_result.segments,
            speech_ratio=extract_result.speech_ratio,
            speech_duration=extract_result.speech_duration,
            total_duration=total_duration,
            used_for_transcription=used,
            force=True,
        )
        if saved:
            artifact_dir = str(saved.resolve())

        extraction_payload = {
            "success": True,
            "speech_ratio": round(extract_result.speech_ratio, 4),
            "speech_duration_seconds": round(extract_result.speech_duration, 2),
            "total_duration_seconds": round(total_duration, 2),
            "segment_count": len(extract_result.segments),
            "would_use_speech_only": used,
            "segments": extract_result.segments[:20],  # UI 預覽上限
            "segments_truncated": len(extract_result.segments) > 20,
        }
    else:
        extraction_payload = {
            "success": False,
            "error": "無法提取語音片段（可能全段靜音或格式不支援）",
        }

    # --- 2. 靜音分割（模擬轉錄失敗後的重試切割）---
    if include_split:
        wav_path = convert_to_wav(file_path, temp_dir)
        if wav_path is None:
            split_payload = {"success": False, "error": "無法轉換為 WAV 格式"}
        else:
            if wav_path != file_path:
                to_cleanup.append(wav_path)

            part1_path, part2_path, split_point = vad_service.split_audio_on_silence(
                audio_path=str(wav_path),
                output_dir=str(temp_dir),
            )
            if part1_path and part2_path and split_point is not None:
                p1 = Path(part1_path)
                p2 = Path(part2_path)
                to_cleanup.extend([p1, p2])

                saved = persist_split(
                    task_id=task_id,
                    original_filename=original_filename,
                    part1_path=p1,
                    part2_path=p2,
                    split_point=split_point,
                    force=True,
                )
                if saved and artifact_dir is None:
                    artifact_dir = str(saved.resolve())

                part2_dur = get_audio_duration(p2) or max(0.0, total_duration - split_point)
                split_payload = {
                    "success": True,
                    "split_point_seconds": round(split_point, 2),
                    "part1_duration_seconds": round(split_point, 2),
                    "part2_duration_seconds": round(part2_dur, 2),
                }
            else:
                split_payload = {
                    "success": False,
                    "error": "找不到合適的靜音分割點",
                }

    _cleanup_paths(to_cleanup)

    overall_ok = bool(
        (extraction_payload and extraction_payload.get("success"))
        or (split_payload and split_payload.get("success"))
    )

    return {
        "success": overall_ok,
        "task_id": task_id,
        "original_filename": original_filename,
        "artifact_dir": artifact_dir,
        "speech_extraction": extraction_payload,
        "split": split_payload,
        "error": None if overall_ok else "VAD 測試未產生有效結果",
    }
