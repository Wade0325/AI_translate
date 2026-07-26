"""VAD / ffmpeg 靜音切割獨立測試 pipeline — 不經 Docker / API，直接對本機音檔測試。

把測試音檔放進 tests/audio_input/，執行後兩種切割方式都會跑一次，
結果輸出到 tests/audio_output/{檔名}/，方便試聽比較（尚未做方法選擇機制）：
  speech_only_vad.wav      VAD（RMS 音量閾值）靜音移除結果
  segments_vad.json        VAD 各語音片段在原始音檔上的起訖時間（分:秒.小數）
  speech_only_ffmpeg.wav   ffmpeg silencedetect 靜音移除結果（參數沿用根目錄 test.py）
  segments_ffmpeg.json     ffmpeg 各語音片段起訖時間
  report.json              兩種方法的統計摘要（語音佔比、正式流程是否會採用等）
  part1.wav/part2.wav      （--split 時）VAD 靜音分割結果

VAD 路徑走的程式碼與正式轉錄完全相同：
  convert_to_wav（ffmpeg 16k 單聲道）→ run_vad_extraction（RMS 靜音移除）
  --split 時再跑 split_audio_on_silence（Silero VAD，首次執行會下載模型）
ffmpeg 路徑：silencedetect 找靜音 → 依區間切割拼接（邏輯移植自 test.py）。

用法（repo 根目錄，用 backend/.venv 的 Python）：
  backend\\.venv\\Scripts\\python.exe tests\\vad_pipeline.py             # 全部檔案
  backend\\.venv\\Scripts\\python.exe tests\\vad_pipeline.py foo.mp3     # 指定檔案
  backend\\.venv\\Scripts\\python.exe tests\\vad_pipeline.py --split     # 加測靜音分割
或直接執行 tests\\vad_pipeline.bat（自動使用 backend/.venv）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import get_settings          # noqa: E402
from app.services.vad.preprocess import run_vad_extraction  # noqa: E402
from app.services.vad.service import get_vad_service        # noqa: E402
from app.utils.audio import AUDIO_MIME_MAP, convert_to_wav, get_audio_duration  # noqa: E402

INPUT_DIR = REPO_ROOT / "tests" / "audio_input"
OUTPUT_DIR = REPO_ROOT / "tests" / "audio_output"

# ffmpeg silencedetect 切割參數（沿用根目錄 test.py 的設定）
FFMPEG_NOISE_DB = "-45dB"   # 低於此音量視為靜音
FFMPEG_MIN_SILENCE = 0.9    # 靜音至少持續秒數才切
FFMPEG_MERGE_GAP = 0.7      # 相鄰片段間隔小於此秒數則合併
FFMPEG_MAX_SEG = 15.0       # 單段最長秒數（超過強制切段）
FFMPEG_MIN_VOICE = 0.3      # 片段至少秒數，低於視為雜訊捨棄


def to_minutes(seconds: float) -> str:
    """秒數轉「分:秒.小數」字串，例如 727.05 → \"12:07.05\"。"""
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"{minutes}:{remainder:05.2f}"


def _collect_inputs(names: list[str]) -> list[Path]:
    if names:
        files = []
        for name in names:
            path = INPUT_DIR / name
            if not path.exists():
                print(f"[略過] 找不到 {path}")
                continue
            files.append(path)
        return files
    return sorted(
        p for p in INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_MIME_MAP
    )


def ffmpeg_speech_intervals(path: Path, total_duration: float) -> list[tuple[float, float]]:
    """用 ffmpeg silencedetect 找出語音區間（邏輯移植自 test.py 的 get_speech_intervals）。"""
    p = subprocess.run(
        ["ffmpeg", "-i", str(path),
         "-af", f"silencedetect=noise={FFMPEG_NOISE_DB}:d={FFMPEG_MIN_SILENCE}",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    log = p.stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", log)]

    intervals: list[tuple[float, float]] = []
    current = 0.0
    for i in range(len(starts)):
        sil_start = starts[i]
        sil_end = ends[i] if i < len(ends) else total_duration
        if sil_start - current > FFMPEG_MIN_VOICE:
            intervals.append((current, sil_start))
        current = sil_end
    if total_duration - current > FFMPEG_MIN_VOICE:
        intervals.append((current, total_duration))

    merged: list[tuple[float, float]] = []
    for st, en in intervals:
        if merged and st - merged[-1][1] <= FFMPEG_MERGE_GAP and en - merged[-1][0] <= FFMPEG_MAX_SEG:
            merged[-1] = (merged[-1][0], en)
        else:
            merged.append((st, en))

    final: list[tuple[float, float]] = []
    for st, en in merged:
        while (en - st) > FFMPEG_MAX_SEG:
            final.append((st, st + FFMPEG_MAX_SEG))
            st += FFMPEG_MAX_SEG
        if (en - st) > FFMPEG_MIN_VOICE:
            final.append((st, en))
    return final


def run_ffmpeg_extraction(wav_path: Path, work_dir: Path) -> dict:
    """ffmpeg silencedetect 靜音移除：偵測語音區間後切割拼接成 speech_only_ffmpeg.wav。"""
    data, sr = sf.read(str(wav_path), dtype="float32")
    total_duration = len(data) / sr

    intervals = ffmpeg_speech_intervals(wav_path, total_duration)
    if not intervals:
        return {"success": False, "error": "silencedetect 未找到任何語音區間"}

    pieces = [data[int(st * sr):int(en * sr)] for st, en in intervals]
    speech = np.concatenate([p for p in pieces if len(p)])

    output = work_dir / "speech_only_ffmpeg.wav"
    try:
        sf.write(str(output), speech, sr)
    except (PermissionError, RuntimeError):
        # Windows：檔案被播放器等程式鎖定時無法覆蓋
        print("  [警告] speech_only_ffmpeg.wav 被其他程式占用（播放器？），保留舊檔，僅更新 JSON")

    (work_dir / "segments_ffmpeg.json").write_text(
        json.dumps(
            [{"start": to_minutes(st), "end": to_minutes(en)} for st, en in intervals],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    speech_duration = float(sum(en - st for st, en in intervals))
    return {
        "success": True,
        "output": output.name,
        "speech_duration": to_minutes(speech_duration),
        "speech_ratio": round(speech_duration / total_duration, 4) if total_duration else 0.0,
        "segment_count": len(intervals),
        "params": {
            "noise": FFMPEG_NOISE_DB,
            "min_silence": FFMPEG_MIN_SILENCE,
            "merge_gap": FFMPEG_MERGE_GAP,
            "max_seg": FFMPEG_MAX_SEG,
            "min_voice": FFMPEG_MIN_VOICE,
        },
    }


def process_file(input_path: Path, *, include_split: bool, min_silence: float) -> dict:
    settings = get_settings()
    threshold = settings.vad_speech_ratio_skip_threshold
    vad_service = get_vad_service()

    work_dir = OUTPUT_DIR / input_path.stem
    work_dir.mkdir(parents=True, exist_ok=True)

    # 移除舊版命名的產物（改名為 *_vad / *_ffmpeg 前的版本），避免試聽時混淆
    for stale in ("speech_only.wav", "segments.json"):
        try:
            (work_dir / stale).unlink(missing_ok=True)
        except PermissionError:
            pass  # 被占用就先留著

    report: dict = {
        "input": input_path.name,
        "total_duration": to_minutes(get_audio_duration(input_path) or 0.0),
    }
    cleanup: list[Path] = []

    # --- 轉 WAV（16kHz 單聲道，與正式流程相同）---
    wav_path = convert_to_wav(input_path, work_dir)
    if wav_path is None:
        report["error"] = "ffmpeg 轉 WAV 失敗"
        return report
    if wav_path != input_path:
        cleanup.append(wav_path)

    # --- 方法一：VAD 靜音移除（正式轉錄的前處理主路徑）---
    extraction = run_vad_extraction(wav_path, work_dir, vad_service)
    cleanup.extend(extraction.cleanup_files)

    if extraction.success and extraction.speech_only_path:
        speech_only = work_dir / "speech_only_vad.wav"
        try:
            extraction.speech_only_path.replace(speech_only)
        except PermissionError:
            # Windows：目標檔案被播放器等程式鎖定時無法覆蓋，舊檔內容相同故保留
            print("  [警告] speech_only_vad.wav 被其他程式占用（播放器？），保留舊檔，僅更新 JSON")

        (work_dir / "segments_vad.json").write_text(
            json.dumps(
                [
                    {"start": to_minutes(seg["start"]), "end": to_minutes(seg["end"])}
                    for seg in extraction.segments
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        report["vad"] = {
            "success": True,
            "output": speech_only.name,
            "speech_duration": to_minutes(extraction.speech_duration),
            "speech_ratio": round(extraction.speech_ratio, 4),
            "segment_count": len(extraction.segments),
            "skip_threshold": threshold,
            "would_use_speech_only": extraction.speech_ratio < threshold,
        }
    else:
        report["vad"] = {
            "success": False,
            "error": "無法提取語音片段（可能全段靜音或格式不支援）",
        }

    # --- 方法二：ffmpeg silencedetect 靜音移除（移植自 test.py）---
    try:
        report["ffmpeg"] = run_ffmpeg_extraction(wav_path, work_dir)
    except Exception as e:
        report["ffmpeg"] = {"success": False, "error": str(e)}

    # --- 靜音分割（模擬長檔轉錄失敗後的重試切割，VAD 專屬）---
    if include_split:
        part1, part2, split_point = vad_service.split_audio_on_silence(
            audio_path=str(wav_path),
            output_dir=str(work_dir),
            min_silence_duration=min_silence,
        )
        if part1 and part2 and split_point is not None:
            try:
                Path(part1).replace(work_dir / "part1.wav")
                Path(part2).replace(work_dir / "part2.wav")
            except PermissionError:
                cleanup.extend([Path(part1), Path(part2)])
                print("  [警告] part1/part2 被其他程式占用（播放器？），保留舊檔，僅更新 JSON")
            report["split"] = {
                "success": True,
                "split_point": to_minutes(split_point),
                "part1": "part1.wav",
                "part2": "part2.wav",
            }
        else:
            report["split"] = {"success": False, "error": "找不到合適的靜音分割點"}

    for path in cleanup:
        if path.exists() and path != input_path:
            path.unlink()

    (work_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="VAD / ffmpeg 靜音切割獨立測試 pipeline")
    parser.add_argument("files", nargs="*", help="只處理 audio_input 內的指定檔名（預設全部）")
    parser.add_argument("--split", action="store_true", help="同時測試靜音分割（part1/part2）")
    parser.add_argument("--min-silence", type=float, default=1.0,
                        help="分割所需最小靜音秒數（預設 1.0）")
    args = parser.parse_args()

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    inputs = _collect_inputs(args.files)
    if not inputs:
        print(f"tests/audio_input/ 內沒有可處理的音檔（支援: {', '.join(sorted(AUDIO_MIME_MAP))}）")
        return 1

    print(f"共 {len(inputs)} 個檔案，輸出到 {OUTPUT_DIR}\n")
    failed = 0
    for input_path in inputs:
        print(f"=== {input_path.name} ===")
        report = process_file(
            input_path, include_split=args.split, min_silence=args.min_silence
        )

        vad = report.get("vad", {})
        if vad.get("success"):
            decision = "會使用 speech_only" if vad["would_use_speech_only"] \
                else f"語音佔比 >= {vad['skip_threshold']:.0%}，正式流程會直接用原檔"
            print(f"  [VAD]    原始 {report['total_duration']} → "
                  f"純語音 {vad['speech_duration']}"
                  f"（佔比 {vad['speech_ratio']:.1%}，{vad['segment_count']} 段）")
            print(f"           正式流程判定: {decision}")
        else:
            print(f"  [VAD]    失敗: {vad.get('error') or report.get('error')}")

        ff = report.get("ffmpeg", {})
        if ff.get("success"):
            print(f"  [ffmpeg] 純語音 {ff['speech_duration']}"
                  f"（佔比 {ff['speech_ratio']:.1%}，{ff['segment_count']} 段）")
        else:
            print(f"  [ffmpeg] 失敗: {ff.get('error') or report.get('error')}")

        if not vad.get("success") and not ff.get("success"):
            failed += 1

        split = report.get("split")
        if split:
            if split["success"]:
                print(f"  分割點: {split['split_point']} → part1.wav / part2.wav")
            else:
                print(f"  [分割失敗] {split['error']}")
        print(f"  → {OUTPUT_DIR / input_path.stem}\n")

    print("完成。請到 tests/audio_output/ 試聽比較 speech_only_vad.wav 與 speech_only_ffmpeg.wav。")
    return 1 if failed == len(inputs) else 0


if __name__ == "__main__":
    sys.exit(main())
