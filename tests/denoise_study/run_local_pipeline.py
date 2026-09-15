"""對單一音檔跑一次「正式」local 轉錄流程（VAD → 切半 → VibeVoice 分離 → Qwen3-ASR → 對齊 → remap）。

直接驅動 app.services.transcription.flows.TranscriptionTask(provider="local")，
與 local_asr worker 走的是同一份程式碼；只額外包一層紀錄器把中間產物存下來：
  transcript.lrc / .srt / .txt   最終結果（原始音檔時間軸）
  diarization.json               每次 VibeVoice 呼叫的分離片段（各半段各自的時間軸）
  asr_entries.json               Qwen3-ASR 逐片段原始文字（對齊/斷行前）
  run.json                       VAD 佔比、切半、耗時、GPU 峰值等
  pipeline.log                   狀態回呼與 backend logger 輸出

backend 預設取本 repo 的 backend/；設 AIT_BACKEND_DIR 可指向其他 checkout
（例如 worktree 內實驗時指回主 checkout，沿用其模型設定與未提交修改）。

用法：
  backend\\.venv\\Scripts\\python.exe tests\\denoise_study\\run_local_pipeline.py IN_AUDIO OUT_DIR [--lang zh-TW]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(os.environ.get("AIT_BACKEND_DIR", REPO_ROOT / "backend"))
sys.path.insert(0, str(BACKEND_DIR))

import soundfile as sf  # noqa: E402


def scored_transcribe_segments(asr, wav_path, segments, language, status_callback=None, cancel_check=None):
    """asr._transcribe_segments 的逐行鏡像，額外取出每段生成 token 的 log 機率。

    解碼仍是 greedy（generate 只多回傳 scores），文字與正式流程完全相同；
    entry 多出 logprob_sum / n_tokens / min_logprob 供無參考品質評估（ASR 自信度）。
    """
    import torch
    from transformers import AutoProcessor, Qwen3ASRForConditionalGeneration

    processor = AutoProcessor.from_pretrained(asr.ASR_MODEL_ID)
    model = Qwen3ASRForConditionalGeneration.from_pretrained(
        asr.ASR_MODEL_ID, device_map="auto", dtype=torch.bfloat16,
    )
    model.eval()

    audio_data, sr = sf.read(str(wav_path), dtype="float32")
    segment_wav = wav_path.parent / f"{wav_path.stem}_seg.wav"
    entries: list[dict] = []

    try:
        total = len(segments)
        for i, seg in enumerate(segments, 1):
            asr._raise_if_cancelled(cancel_check)
            start = float(seg.get("Start", 0.0))
            end = float(seg.get("End", 0.0))
            speaker = int(seg.get("Speaker", 0))

            if not asr._write_segment_wav(audio_data, sr, start, end, segment_wav):
                continue

            request_kwargs = {"audio": str(segment_wav)}
            if language:
                request_kwargs["language"] = language
            inputs = processor.apply_transcription_request(**request_kwargs)
            inputs = inputs.to(model.device).to(torch.bfloat16)
            with torch.inference_mode():
                out = model.generate(**inputs, max_new_tokens=512,
                                     output_scores=True, return_dict_in_generate=True)
            generated_ids = out.sequences[:, inputs["input_ids"].shape[1]:]
            text = processor.decode(
                generated_ids, return_format="transcription_only")[0].strip()
            logprobs = [float(torch.log_softmax(step[0].float(), dim=-1)[tok])
                        for step, tok in zip(out.scores, generated_ids[0])]

            if text:
                entries.append({
                    "start": start, "end": end, "speaker": speaker, "text": text,
                    "logprob_sum": round(sum(logprobs), 4), "n_tokens": len(logprobs),
                    "min_logprob": round(min(logprobs), 4) if logprobs else None,
                })
            if i % 10 == 0 or i == total:
                asr._notify(status_callback, f"本地模型：Qwen3-ASR 轉錄中 {i}/{total}...")
    finally:
        asr._free_model(model, processor)
        segment_wav.unlink(missing_ok=True)

    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("audio", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--lang", default="zh-TW", help="同前端 source_lang（預設 zh-TW）")
    parser.add_argument("--vad-audio", type=Path,
                        help="分流實驗：RMS VAD 靜音判定改在此音檔上做（需與輸入等長同時間軸），"
                             "切出的時間段套回輸入音檔拼接純語音檔")
    parser.add_argument("--replay-diarization", type=Path,
                        help="重播模式：沿用該結果資料夾的 diarization.json（不跑 VibeVoice、不做對齊），"
                             "只重跑 Qwen3-ASR 取得自信度，並核對文字是否與原結果一致")
    args = parser.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    log_handler = logging.FileHandler(out_dir / "pipeline.log", mode="w", encoding="utf-8")
    log_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(log_handler)
    logging.getLogger().setLevel(logging.INFO)
    status_log = logging.getLogger("status")

    import torch
    from app.provider.local import asr
    from app.services.converter.service import convert_from_lrc
    from app.services.transcription import flows

    # app 的 logger 各自掛 stdout handler 且不往上傳，補掛檔案 handler
    for name in ("app.provider.local.asr", "app.services.transcription.flows",
                 "app.services.vad.flows", "app.services.vad.service"):
        logging.getLogger(name).addHandler(log_handler)

    diar_calls: list[dict] = []
    asr_calls: list[dict] = []
    vad_info: dict = {}

    orig_diar = asr._run_diarization
    orig_vad = flows.TranscriptionTask._extract_speech_only

    def orig_asr(wav_path, segments, language, status_callback=None, cancel_check=None):
        return scored_transcribe_segments(asr, wav_path, segments, language, status_callback, cancel_check)

    if args.replay_diarization:
        recorded = json.loads((args.replay_diarization / "diarization.json").read_text(encoding="utf-8"))

        def orig_diar(wav_path, cancel_check=None):  # noqa: F811 — 重播取代 VibeVoice
            return recorded[len(diar_calls)]["segments"]

        asr._build_lrc_lines = lambda wav_path, entries, status_callback=None, cancel_check=None: [
            f"{asr._lrc_timestamp(e['start'])}[S{e['speaker']}] {e['text']}" for e in entries]

    if args.vad_audio:
        import numpy as np
        from app.services.vad.preprocess import run_vad_extraction

        def split_vad(self, audio_path):
            """flows._extract_speech_only 的分流版：判定用 vad_audio，拼接用輸入音檔。"""
            res = run_vad_extraction(args.vad_audio, self.temp_dir, self.vad_service)
            self.local_cleanup_list.extend(res.cleanup_files)
            if not res.success:
                return None
            data, sr = sf.read(str(audio_path), dtype="float32")
            pieces = [data[max(0, int(s["start"] * sr)):min(len(data), int(s["end"] * sr))]
                      for s in res.segments]
            speech_path = self.temp_dir / f"{audio_path.stem}_split_speech_only.wav"
            sf.write(str(speech_path), np.concatenate([p for p in pieces if len(p)]), sr)
            return {"speech_only_path": str(speech_path), "segments": res.segments,
                    "speech_ratio": res.speech_ratio, "speech_duration": res.speech_duration}

        orig_vad = split_vad

    def rec_diar(wav_path, cancel_check=None):
        duration = sf.info(str(wav_path)).duration
        started = time.time()
        segments = orig_diar(wav_path, cancel_check)
        diar_calls.append({
            "input_seconds": round(duration, 2),
            "elapsed_seconds": round(time.time() - started, 1),
            "speakers": sorted({int(s.get("Speaker", 0)) for s in segments}),
            "segments": segments,
        })
        return segments

    def rec_asr(wav_path, segments, language, status_callback=None, cancel_check=None):
        started = time.time()
        entries = orig_asr(wav_path, segments, language, status_callback, cancel_check)
        asr_calls.append({
            "elapsed_seconds": round(time.time() - started, 1),
            "entries": [dict(e) for e in entries],
        })
        return entries

    def rec_vad(self, audio_path):
        result = orig_vad(self, audio_path)
        if result:
            vad_info.update({
                "speech_ratio": round(result["speech_ratio"], 4),
                "speech_seconds": round(result["speech_duration"], 2),
                "segment_count": len(result["segments"]),
                "segments": result["segments"],
            })
        return result

    asr._run_diarization = rec_diar
    asr._transcribe_segments = rec_asr
    flows.TranscriptionTask._extract_speech_only = rec_vad

    with tempfile.TemporaryDirectory(prefix="ait_denoise_") as tmp:
        temp_dir = Path(tmp)
        # flows 會把輸入登記進清理清單、asr 會在輸入旁寫暫存檔：一律先複製進暫存目錄
        work_input = temp_dir / args.audio.name
        shutil.copy2(args.audio, work_input)

        task = flows.TranscriptionTask(
            client=None, model="local", prompt="", temp_dir=temp_dir,
            status_callback=lambda text: status_log.info(text),
            provider="local", source_lang=args.lang,
        )
        torch.cuda.reset_peak_memory_stats()
        started = time.time()
        result = task.transcribe_audio(work_input)
        elapsed = time.time() - started

    run = {
        "input": str(args.audio),
        "vad_audio": str(args.vad_audio) if args.vad_audio else None,
        "source_lang": args.lang,
        "backend_dir": str(BACKEND_DIR),
        "success": result.success,
        "elapsed_seconds": round(elapsed, 1),
        "gpu_peak_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 2),
        "vad": {k: v for k, v in vad_info.items() if k != "segments"},
        "vad_skip_threshold": flows.VAD_SPEECH_RATIO_SKIP_THRESHOLD,
        "long_audio_split_threshold": flows.LONG_AUDIO_SPLIT_THRESHOLD_SECONDS,
        "diarization_calls": [
            {k: v for k, v in c.items() if k != "segments"} | {"segment_count": len(c["segments"])}
            for c in diar_calls
        ],
        "asr_entry_count": sum(len(c["entries"]) for c in asr_calls),
    }
    scored = [e for c in asr_calls for e in c["entries"] if e.get("n_tokens")]
    if scored:
        run["asr_confidence"] = {
            "token_mean_logprob": round(sum(e["logprob_sum"] for e in scored)
                                        / sum(e["n_tokens"] for e in scored), 4),
            "segment_mean_logprob": round(sum(e["logprob_sum"] / e["n_tokens"] for e in scored) / len(scored), 4),
            "low_confidence_segments": sum(1 for e in scored if e["logprob_sum"] / e["n_tokens"] < -0.5),
        }
    if args.replay_diarization:
        before = json.loads((args.replay_diarization / "asr_entries.json").read_text(encoding="utf-8"))
        old = [e["text"] for c in before for e in c["entries"]]
        new = [e["text"] for c in asr_calls for e in c["entries"]]
        run["replay_check"] = {"source": str(args.replay_diarization), "entries_before": len(old),
                               "entries_after": len(new), "identical_texts": old == new,
                               "mismatched": sum(1 for a, b in zip(old, new) if a != b)}

    (out_dir / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "diarization.json").write_text(
        json.dumps(diar_calls, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "asr_entries.json").write_text(
        json.dumps(asr_calls, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "vad_segments.json").write_text(
        json.dumps(vad_info.get("segments", []), ensure_ascii=False), encoding="utf-8")

    if not result.success:
        (out_dir / "error.txt").write_text(result.text, encoding="utf-8")
        print(f"[失敗] {result.text}")
        return 1

    formats = convert_from_lrc(result.text)
    (out_dir / "transcript.lrc").write_text(result.text, encoding="utf-8")
    (out_dir / "transcript.srt").write_text(formats.srt, encoding="utf-8")
    (out_dir / "transcript.txt").write_text(formats.txt, encoding="utf-8")
    print(f"[完成] {args.audio.name} → {out_dir}（{elapsed / 60:.1f} 分鐘）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
