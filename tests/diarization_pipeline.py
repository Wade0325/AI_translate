"""VibeVoice-ASR 說話者分離（diarization）獨立測試 pipeline。

把音檔放進 tests/audio_input/，每檔流程：
  1. VAD 靜音移除（與 vad_pipeline / 正式轉錄同一份程式碼）
  2. 整檔（不切片）餵 microsoft/VibeVoice-ASR-HF 做說話者分離
  3. 輸出到 tests/audio_output/{檔名}/：
     speakers.json       說話者摘要 + 各片段（時間為「分:秒.小數」，
                         同時給 speech_only 與原始音檔兩種時間軸）
     speaker_00.wav ...  依說話者拼接的音檔（試聽判斷每個 Speaker 是誰）
     speech_only_vad.wav 餵給模型的 VAD 處理檔（與 vad_pipeline 產物相同）

模型約 18GB（BF16），16GB VRAM 放不下的層由 accelerate 自動降載到 CPU RAM
（--gpu-mem 控制 GPU 權重上限，剩餘空間留給 KV cache）。
首次執行會下載模型（約 18GB）到 D:\\AI_translate\\models\\hf_cache。

用法：
  tests\\diarization_pipeline.bat                # 全部檔案
  tests\\diarization_pipeline.bat foo.wav        # 指定檔案
  tests\\diarization_pipeline.bat --gpu-mem 9GiB        # OOM 時降低
  tests\\diarization_pipeline.bat --chunk-size 720000   # OOM 時降低
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", r"D:\AI_translate\models\hf_cache")

import numpy as np
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from vad_pipeline import INPUT_DIR, OUTPUT_DIR, to_minutes, _collect_inputs  # noqa: E402
from app.services.vad.preprocess import run_vad_extraction  # noqa: E402
from app.services.vad.service import get_vad_service        # noqa: E402
from app.utils.audio import convert_to_wav, get_audio_duration  # noqa: E402

MODEL_ID = "microsoft/VibeVoice-ASR-HF"
MODEL_SAMPLE_RATE = 24000


def load_model(gpu_mem: str):
    """載入 processor 與模型（bf16，整批只載一次）。"""
    import torch
    from transformers import AutoProcessor, VibeVoiceAsrForConditionalGeneration

    print(f"載入模型 {MODEL_ID}（首次會下載約 18GB）...")
    processor = AutoProcessor.from_pretrained(MODEL_ID)

    model = VibeVoiceAsrForConditionalGeneration.from_pretrained(
        MODEL_ID,
        device_map="auto",
        dtype=torch.bfloat16,
        # GPU 只放到 gpu_mem 上限，其餘層降載 CPU；剩餘 VRAM 留給 KV cache 與運算
        max_memory={0: gpu_mem, "cpu": "26GiB"},
    )
    model.eval()
    return processor, model


def to_model_wav(source: Path, work_dir: Path) -> Path | None:
    """轉成模型要求的 mono 24kHz wav 暫存檔。"""
    output = work_dir / f"{source.stem}_diar24k.wav"
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(source), "-ac", "1", "-ar", str(MODEL_SAMPLE_RATE), str(output)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    if result.returncode != 0:
        print(f"  [失敗] ffmpeg 轉 24kHz 失敗: {result.stderr.strip()[-200:]}")
        return None
    return output


def build_remapper(segments: list[dict]):
    """speech_only 時間軸 → 原始音檔時間軸（依 VAD 片段累積時長換算）。"""
    if not segments:
        return lambda t: t
    bounds = []
    acc = 0.0
    for seg in segments:
        dur = seg["end"] - seg["start"]
        bounds.append((acc, acc + dur, seg["start"]))
        acc += dur

    def remap(t: float) -> float:
        for start, end, orig in bounds:
            if t <= end:
                return orig + max(0.0, t - start)
        last_start, last_end, last_orig = bounds[-1]
        return last_orig + (last_end - last_start)

    return remap


def transcribe(processor, model, wav_path: Path, *, max_new_tokens: int, chunk_size: int | None):
    """整檔（不切片）推論，回傳 (parsed_segments, raw_text, stats)。"""
    import torch

    inputs = processor.apply_transcription_request(audio=str(wav_path))
    inputs = inputs.to(model.device).to(torch.bfloat16)

    gen_kwargs: dict = {"max_new_tokens": max_new_tokens}
    if chunk_size:
        gen_kwargs["tokenizer_chunk_size"] = chunk_size

    torch.cuda.reset_peak_memory_stats()
    started = time.time()
    with torch.inference_mode():
        output_ids = model.generate(**inputs, **gen_kwargs)
    elapsed = time.time() - started

    generated_ids = output_ids[:, inputs["input_ids"].shape[1]:]
    raw_text = processor.decode(generated_ids[0], skip_special_tokens=True)

    stats = {
        "inference_seconds": round(elapsed, 1),
        "gpu_peak_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 2),
        "new_tokens": int(generated_ids.shape[1]),
    }

    try:
        parsed = processor.decode(generated_ids, return_format="parsed")[0]
    except Exception as e:
        print(f"  [警告] 結構化解析失敗（{e}），保留原始輸出")
        return None, raw_text, stats

    if isinstance(parsed, dict):
        parsed = [parsed]
    return parsed, raw_text, stats


def _safe_write_wav(path: Path, data: np.ndarray, sr: int) -> bool:
    try:
        sf.write(str(path), data, sr)
        return True
    except (PermissionError, RuntimeError):
        print(f"  [警告] {path.name} 被其他程式占用（播放器？），保留舊檔")
        return False


def process_file(input_path: Path, processor, model, vad_service, args) -> dict:
    work_dir = OUTPUT_DIR / input_path.stem
    work_dir.mkdir(parents=True, exist_ok=True)
    cleanup: list[Path] = []

    total_duration = get_audio_duration(input_path) or 0.0
    report: dict = {
        "input": input_path.name,
        "total_duration": to_minutes(total_duration),
    }

    # --- 1. 轉 wav + VAD 靜音移除（與正式流程/vad_pipeline 相同）---
    wav_path = convert_to_wav(input_path, work_dir)
    if wav_path is None:
        report["error"] = "ffmpeg 轉 WAV 失敗"
        return report
    if wav_path != input_path:
        cleanup.append(wav_path)

    extraction = run_vad_extraction(wav_path, work_dir, vad_service)
    cleanup.extend(extraction.cleanup_files)

    if extraction.success and extraction.speech_only_path:
        model_source = extraction.speech_only_path
        vad_segments = extraction.segments
        report["audio_fed_to_model"] = "speech_only_vad.wav（VAD 靜音移除、整檔不切片）"
        report["speech_only_duration"] = to_minutes(extraction.speech_duration)
    else:
        model_source = wav_path
        vad_segments = []
        report["audio_fed_to_model"] = "原始音檔（VAD 提取失敗，整檔不切片）"
        print("  [警告] VAD 提取失敗，改用原始音檔")

    # 讀出音訊資料供切片；speech_only 檔另存一份供試聽對照
    audio_data, sr = sf.read(str(model_source), dtype="float32")
    if extraction.success and extraction.speech_only_path:
        speech_only_keep = work_dir / "speech_only_vad.wav"
        try:
            extraction.speech_only_path.replace(speech_only_keep)
        except PermissionError:
            print("  [警告] speech_only_vad.wav 被其他程式占用（播放器？），保留舊檔")

    # --- 2. 轉 24kHz mono 餵模型 ---
    model_wav = to_model_wav(
        speech_only_keep if (extraction.success and extraction.speech_only_path) else model_source,
        work_dir,
    )
    if model_wav is None:
        report["error"] = "無法產生模型輸入檔"
        return report
    cleanup.append(model_wav)

    # --- 3. 整檔推論 ---
    segments, raw_text, stats = transcribe(
        processor, model, model_wav,
        max_new_tokens=args.max_new_tokens, chunk_size=args.chunk_size,
    )
    report["params"] = {
        "model": MODEL_ID,
        "precision": "bf16 + CPU offload",
        "gpu_mem_limit": args.gpu_mem,
        "chunk_size": args.chunk_size,
        "max_new_tokens": args.max_new_tokens,
        **stats,
    }

    if not segments:
        report["success"] = False
        report["error"] = "模型輸出無法解析為片段"
        (work_dir / "diarization_raw.txt").write_text(raw_text, encoding="utf-8")
        (work_dir / "speakers.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    # --- 4. 依說話者拼接音檔 + 組 speakers.json ---
    remap = build_remapper(vad_segments)
    speech_total = len(audio_data) / sr
    by_speaker: dict[int, list[np.ndarray]] = {}
    out_segments = []

    for seg in segments:
        start = float(seg.get("Start", 0.0))
        end = float(seg.get("End", 0.0))
        speaker = int(seg.get("Speaker", 0))
        piece = audio_data[int(start * sr):int(end * sr)]
        if len(piece):
            by_speaker.setdefault(speaker, []).append(piece)
        out_segments.append({
            "speaker": speaker,
            "start": to_minutes(start),
            "end": to_minutes(end),
            "original_start": to_minutes(remap(start)),
            "original_end": to_minutes(remap(end)),
            "text": seg.get("Content", ""),
        })

    speakers_summary = {}
    for speaker in sorted(by_speaker):
        joined = np.concatenate(by_speaker[speaker])
        out_wav = work_dir / f"speaker_{speaker:02d}.wav"
        _safe_write_wav(out_wav, joined, sr)
        duration = len(joined) / sr
        speakers_summary[str(speaker)] = {
            "output": out_wav.name,
            "total_duration": to_minutes(duration),
            "ratio": round(duration / speech_total, 4) if speech_total else 0.0,
            "segment_count": sum(1 for s in out_segments if s["speaker"] == speaker),
        }

    report["success"] = True
    report["speaker_count"] = len(by_speaker)
    report["speakers"] = speakers_summary
    report["segments"] = out_segments

    for path in cleanup:
        if path.exists() and path != input_path:
            path.unlink()

    (work_dir / "speakers.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="VibeVoice-ASR 說話者分離獨立測試 pipeline")
    parser.add_argument("files", nargs="*", help="只處理 audio_input 內的指定檔名（預設全部）")
    parser.add_argument("--gpu-mem", default="11GiB",
                        help="GPU 權重上限，其餘降載 CPU（預設 11GiB，留空間給長音檔 KV cache）")
    parser.add_argument("--chunk-size", type=int, default=None,
                        help="透傳 tokenizer_chunk_size，OOM 時降低（預設模型內建 60 秒）")
    parser.add_argument("--max-new-tokens", type=int, default=8192)
    args = parser.parse_args()

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    inputs = _collect_inputs(args.files)
    if not inputs:
        print("tests/audio_input/ 內沒有可處理的音檔")
        return 1

    vad_service = get_vad_service()
    processor, model = load_model(args.gpu_mem)

    print(f"\n共 {len(inputs)} 個檔案，輸出到 {OUTPUT_DIR}\n")
    failed = 0
    for input_path in inputs:
        print(f"=== {input_path.name} ===")
        report = process_file(input_path, processor, model, vad_service, args)

        if report.get("success"):
            stats = report["params"]
            print(f"  說話者數: {report['speaker_count']}（推論 {stats['inference_seconds']}s，"
                  f"GPU 峰值 {stats['gpu_peak_gb']}GB）")
            for spk, info in report["speakers"].items():
                print(f"    Speaker {spk}: {info['total_duration']}"
                      f"（佔比 {info['ratio']:.1%}，{info['segment_count']} 段）→ {info['output']}")
        else:
            failed += 1
            print(f"  [失敗] {report.get('error')}")
        print(f"  → {OUTPUT_DIR / input_path.stem}\n")

    print("完成。請到 tests/audio_output/ 試聽 speaker_XX.wav 判斷各說話者身分，"
          "對照 speakers.json 的時間軸。")
    return 1 if failed == len(inputs) else 0


if __name__ == "__main__":
    sys.exit(main())
