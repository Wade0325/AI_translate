"""VAD 產物持久化 — 供本機檢查切割是否正確。

啟用 ``VAD_KEEP_ARTIFACTS=true`` 後，每次 VAD 前處理或分割會把 wav 與
segments 資訊複製到 ``vad_artifacts/{檔名}_{task_id}/``，不受轉錄完成後
temp_uploads 清理影響。
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.core.config import get_settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _sanitize(name: str, max_len: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned[:max_len] or "audio"


def _artifact_run_dir(
    task_id: str,
    original_filename: str,
    *,
    force: bool = False,
) -> Optional[Path]:
    settings = get_settings()
    if not settings.vad_keep_artifacts and not force:
        return None

    base = Path(settings.vad_artifacts_dir)
    stem = _sanitize(Path(original_filename).stem)
    short_id = re.sub(r"[^a-zA-Z0-9]", "", task_id)[:12] or "task"
    run_dir = base / f"{stem}_{short_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _load_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "task_id": None,
        "original_filename": None,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "operations": [],
        "files": {},
    }


def _save_manifest(run_dir: Path, manifest: dict[str, Any]) -> None:
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _copy_file(source: Path, run_dir: Path, dest_name: str) -> str:
    dest = run_dir / dest_name
    shutil.copy2(source, dest)
    return dest.name


def persist_speech_extraction(
    *,
    task_id: str,
    original_filename: str,
    speech_only_path: Path,
    segments: list,
    speech_ratio: float,
    speech_duration: float,
    total_duration: float = 0.0,
    used_for_transcription: bool,
    force: bool = False,
) -> Optional[Path]:
    """保存 VAD 純語音提取結果（speech_only.wav + segments.json）。"""
    run_dir = _artifact_run_dir(task_id, original_filename, force=force)
    if run_dir is None:
        return None

    try:
        manifest = _load_manifest(run_dir)
        manifest["task_id"] = task_id
        manifest["original_filename"] = original_filename

        manifest["files"]["speech_only"] = _copy_file(
            speech_only_path, run_dir, "speech_only.wav"
        )
        segments_path = run_dir / "segments.json"
        segments_path.write_text(
            json.dumps(segments, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manifest["files"]["segments"] = segments_path.name

        manifest["operations"].append({
            "type": "speech_extraction",
            "at": datetime.now().isoformat(timespec="seconds"),
            "speech_ratio": round(speech_ratio, 4),
            "speech_duration_seconds": round(speech_duration, 2),
            "total_duration_seconds": round(total_duration, 2),
            "segment_count": len(segments),
            "used_for_transcription": used_for_transcription,
        })
        _save_manifest(run_dir, manifest)
        logger.info(f"VAD 檢查用音訊已保存: {run_dir.resolve()}")
        return run_dir
    except Exception as e:
        logger.warning(f"保存 VAD 產物失敗 ({original_filename}): {e}")
        return None


def persist_split(
    *,
    task_id: str,
    original_filename: str,
    part1_path: Path,
    part2_path: Path,
    split_point: float,
    force: bool = False,
) -> Optional[Path]:
    """保存 VAD 靜音分割結果（part1.wav + part2.wav）。"""
    run_dir = _artifact_run_dir(task_id, original_filename, force=force)
    if run_dir is None:
        return None

    try:
        manifest = _load_manifest(run_dir)
        manifest["task_id"] = task_id
        manifest["original_filename"] = original_filename

        manifest["files"]["part1"] = _copy_file(part1_path, run_dir, "part1.wav")
        manifest["files"]["part2"] = _copy_file(part2_path, run_dir, "part2.wav")

        manifest["operations"].append({
            "type": "split_on_silence",
            "at": datetime.now().isoformat(timespec="seconds"),
            "split_point_seconds": round(split_point, 2),
        })
        _save_manifest(run_dir, manifest)
        logger.info(f"VAD 分割檢查用音訊已保存: {run_dir.resolve()}")
        return run_dir
    except Exception as e:
        logger.warning(f"保存 VAD 分割產物失敗 ({original_filename}): {e}")
        return None
