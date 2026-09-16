"""附加實驗：Qwen3-ASR 的 system prompt（語言提示 / 領域詞彙上下文）對轉錄的影響。

實驗 A 發現最大宗的系統性錯誤（logger→logo、level→label）在所有降噪版本都一樣多，
屬詞彙/口音問題而非噪音問題。Qwen3-ASR 官方用法把使用者上下文放在 system prompt，
並以 assistant 前綴 "language Chinese<asr_text>" 強制語言；transformers 版的
apply_transcription_request(language=...) 則是把語言名稱當作 system 文字（正式流程現況）。

設定（同實驗 A 的固定切塊、同一音檔）：
  K0_prod           system="Chinese"（正式流程現況，應與 asr_fixed 結果一致）
  K1_forced         system=""，前綴強制 language Chinese
  K2_glossary       system=領域詞彙表，前綴強制 language Chinese
  K3_zh_tw_context  system=繁體中文情境說明＋詞彙，前綴強制 language Chinese

輸出 ROOT/asr_context/{K}.json（格式同 asr_fixed）。

用法（backend venv）：
  backend\\.venv\\Scripts\\python.exe tests\\denoise_study\\asr_context_bias.py ROOT AUDIO_WAV [--only K2_glossary ...]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_local_pipeline as rlp  # noqa: E402,F401 — 把 backend 放進 sys.path

import soundfile as sf  # noqa: E402

GLOSSARY = "log4j2, Logger, LoggerContext, Appender, ConsoleAppender, RollingFile, FileAppender, " \
           "Level, info, debug, warn, error, trace, Marker, Filter, Layout, PatternLayout, log4j2.xml"
ZH_TW_CONTEXT = ("這是台灣工程師用繁體中文討論 Java 日誌框架 log4j2 的對話，會提到 Logger、Appender、"
                 "Level（info、debug、warn、error）、Marker、Filter、Layout、ConsoleAppender、RollingFile、"
                 "設定檔、實作層、呼叫、輸出、過濾、層級。")

CONFIGS = {
    "K0_prod": {"system": "Chinese", "prefix": None},
    "K1_forced": {"system": "", "prefix": "language Chinese<asr_text>"},
    "K2_glossary": {"system": GLOSSARY, "prefix": "language Chinese<asr_text>"},
    "K3_zh_tw_context": {"system": ZH_TW_CONTEXT, "prefix": "language Chinese<asr_text>"},
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--suffix", default="", help="輸出檔名後綴（換音檔重跑同一設定時用，避免覆蓋）")
    args = parser.parse_args()
    root: Path = args.root

    import torch
    from transformers import AutoProcessor, Qwen3ASRForConditionalGeneration
    from app.provider.local import asr
    from app.utils.binaries import ffmpeg_bin

    chunks = json.loads((root / "asr_fixed" / "chunks.json").read_text(encoding="utf-8"))
    out_dir = root / "asr_context"
    out_dir.mkdir(exist_ok=True)
    configs = {k: v for k, v in CONFIGS.items() if not args.only or k in args.only}

    processor = AutoProcessor.from_pretrained(asr.ASR_MODEL_ID)
    model = Qwen3ASRForConditionalGeneration.from_pretrained(asr.ASR_MODEL_ID, device_map="auto", dtype=torch.bfloat16)
    model.eval()

    with tempfile.TemporaryDirectory(prefix="ait_ctx_") as tmp:
        wav24 = Path(tmp) / "input_24k.wav"
        subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(args.audio), "-ac", "1",
                        "-ar", str(asr.DIARIZATION_SAMPLE_RATE), str(wav24)], check=True)
        audio_data, sr = sf.read(str(wav24), dtype="float32")
        seg_wav = Path(tmp) / "seg.wav"

        for name, cfg in configs.items():
            name = f"{name}{args.suffix}"
            target = out_dir / f"{name}.json"
            if target.exists():
                print(f"[略過] {name}", flush=True)
                continue
            started = time.time()
            rows = []
            for i, c in enumerate(chunks):
                asr._write_segment_wav(audio_data, sr, c["Start"], c["End"], seg_wav)
                # 與 apply_transcription_request 相同的組裝路徑（K0 應逐字重現正式流程），
                # 只在需要時把強制語言前綴接到 input_ids 尾端
                messages = [{"role": "system", "content": [{"type": "text", "text": cfg["system"]}]},
                            {"role": "user", "content": [{"type": "audio", "path": str(seg_wav)}]}]
                inputs = processor.apply_chat_template([messages], tokenize=True, add_generation_prompt=True,
                                                       return_dict=True)
                if cfg["prefix"]:
                    prefix_ids = processor.tokenizer(cfg["prefix"], add_special_tokens=False,
                                                     return_tensors="pt").input_ids
                    inputs["input_ids"] = torch.cat([inputs["input_ids"], prefix_ids], dim=1)
                    inputs["attention_mask"] = torch.cat(
                        [inputs["attention_mask"], torch.ones_like(prefix_ids)], dim=1)
                inputs = inputs.to(model.device).to(torch.bfloat16)
                with torch.inference_mode():
                    out = model.generate(**inputs, max_new_tokens=512, output_scores=True,
                                         return_dict_in_generate=True)
                gen = out.sequences[:, inputs["input_ids"].shape[1]:]
                if cfg["prefix"]:
                    text = processor.decode(gen[0], skip_special_tokens=True).strip()
                else:
                    text = processor.decode(gen, return_format="transcription_only")[0].strip()
                logprobs = [float(torch.log_softmax(s[0].float(), dim=-1)[t]) for s, t in zip(out.scores, gen[0])]
                rows.append({"i": i, "start": c["Start"], "end": c["End"], "text": text,
                             "logprob_sum": round(sum(logprobs), 4), "n_tokens": len(logprobs),
                             "min_logprob": round(min(logprobs), 4) if logprobs else None})
            scored = [r for r in rows if r["n_tokens"]]
            summary = {"elapsed_seconds": round(time.time() - started, 1),
                       "empty_chunks": sum(1 for r in rows if not r["text"]),
                       "token_mean_logprob": round(sum(r["logprob_sum"] for r in scored)
                                                   / sum(r["n_tokens"] for r in scored), 4),
                       "chunk_mean_logprob": round(sum(r["logprob_sum"] / r["n_tokens"] for r in scored)
                                                   / len(scored), 4),
                       "config": cfg}
            target.write_text(json.dumps({"variant": name, "summary": summary, "chunks": rows},
                                         ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"[完成] {name} {summary}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
