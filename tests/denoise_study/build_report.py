"""彙整研究結果：產生 ROOT/README.md，並把實驗 A 各版本轉錄匯出成可讀檔案。

讀取（缺檔的段落自動略過）：
  00_analysis/analysis.json            錄音前置分析
  report/audio_metrics.json            各版本客觀音訊指標
  report/dnsmos.json                   DNSMOS
  report/asr_fixed_metrics.json        實驗 A 指標
  report/blind_A/scores.json           實驗 A 盲評
  asr_context/*.json + report/asr_context_metrics.json   上下文偏置附加實驗
  B_excerpt_*/report/transcript_metrics.json             實驗 B 指標
  --notes NOTES.md                     研究結論敘述（插在表格前）

匯出：A_固定切段轉錄/{id}/transcript.lrc、transcript.txt

用法：
  python tests\\denoise_study\\build_report.py ROOT --notes NOTES.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def ts(seconds: float) -> str:
    return f"[{int(seconds // 60):02d}:{seconds % 60:05.2f}]"


def table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--notes", type=Path)
    args = parser.parse_args()
    root: Path = args.root
    parts: list[str] = []

    if args.notes and args.notes.exists():
        parts.append(args.notes.read_text(encoding="utf-8").strip())

    # --- 附錄：前置分析 ---
    analysis = load(root / "00_analysis" / "analysis.json")
    if analysis:
        lv, g = analysis["levels"], analysis["global"]
        parts.append("## 附錄 1：錄音前置分析（00_analysis/）")
        parts.append(table(["項目", "數值"], [
            ["時長 / 格式", f"{analysis['duration_seconds'] / 60:.1f} 分鐘，{analysis['sample_rate']} Hz mono"],
            ["整體響度", f"{g['integrated_lufs']} LUFS，響度範圍 {g['loudness_range_lu']} LU，峰值 {g['peak_dbfs']} dBFS"],
            ["人聲音量（語音段平均）", f"{lv['speech_active_level_dbfs']} dBFS"],
            ["噪音底（非語音段平均 / 中位數）", f"{lv['noise_floor_mean_dbfs']} / {lv['noise_frame_db_p10_p50_p90'][1]} dBFS"],
            ["SNR（VAD 法 / 百分位法）", f"{lv['snr_vad_db']} dB / {lv['snr_percentile_p95_minus_p10_db']} dB"],
            ["Silero 語音佔比", f"{analysis['vad']['speech_ratio'] * 100:.1f}%"],
            ["噪音頻譜平坦度", analysis["noise_character"]["spectral_flatness_100_8000hz"]],
            ["噪音中的音調峰", ", ".join(f"{p['freq_hz']}Hz(+{p['prominence_db']}dB)"
                                      for p in analysis["noise_character"]["tonal_peaks_in_noise"])],
            ["非語音暫態事件", f"{analysis['transients_in_nonspeech']['event_count']} 次"],
            ["削波樣本", g["clipped_samples"]],
            ["有效頻寬", f"{analysis['effective_bandwidth_hz']:.0f} Hz"],
        ]))
        parts.append(table(["頻帶 Hz", "人聲 dB", "噪音 dB", "頻帶 SNR dB"],
                           [[b["band_hz"], b["speech_db"], b["noise_db"], b["band_snr_db"]]
                            for b in analysis["bands"] if b["band_snr_db"] > -100]))

    # --- 附錄：音訊指標 + DNSMOS ---
    am, dn = load(root / "report" / "audio_metrics.json"), load(root / "report" / "dnsmos.json")
    if am:
        parts.append("## 附錄 2：各降噪版本的音訊指標（denoised/）")
        parts.append("同一批語音/非語音幀比較。ΔSpeech 越接近 0 越不傷人聲；ΔNoise 越負降噪越多；"
                     "「流程 VAD」= 正式流程的 RMS 靜音移除是否因此啟動。DNSMOS 為聽感分數（1–5），不等於辨識率。")
        rows = []
        for vid, m in am.items():
            d = (dn or {}).get(vid, {})
            rows.append([vid, m["delta_speech_db"], m["delta_noise_db"], m["snr_db"],
                         m["band_delta_speech_db"]["4000-8000"],
                         f"{m['pipeline_vad']['speech_ratio'] * 100:.1f}%" + (" ✔" if m["pipeline_vad"]["silence_removal_used"] else ""),
                         d.get("sig_mos"), d.get("bak_mos"), d.get("ovrl_mos")])
        parts.append(table(["版本", "ΔSpeech dB", "ΔNoise dB", "SNR dB", "Δ4–8kHz 人聲", "流程 VAD 語音佔比",
                            "SIG", "BAK", "OVRL"], rows))

    # --- 附錄：實驗 A ---
    fixed, blind = load(root / "report" / "asr_fixed_metrics.json"), load(root / "report" / "blind_A" / "scores.json")
    if fixed:
        parts.append("## 附錄 3：實驗 A — 固定切段 Qwen3-ASR（全長 37 分鐘、所有版本）")
        parts.append(f"{fixed['chunks']} 個相同切塊；對照組 `{fixed['ref']}`。自信度 = token 平均 log 機率；"
                     "Δ 與 95% 信賴區間為同一塊成對比較；盲評為 60 個分歧最大的塊，評審不知版本。")
        rows = []
        for vid, m in fixed["metrics"].items():
            p = m.get("paired_vs_ref", {})
            s = ((blind or {}).get("scores") or {}).get(vid, {})
            rows.append([vid, m["token_mean_logprob"], p.get("delta_mean", "—"),
                         p.get("ci95", "—"), p.get("win_rate", "—"), m["cer_vs_ref"], m["empty_chunks"],
                         s.get("best_rate"), s.get("worst_rate"), s.get("net")])
        rows.sort(key=lambda r: -(r[9] if isinstance(r[9], (int, float)) else -9))
        parts.append(table(["版本", "自信度", "Δ自信度", "95% CI", "勝率", "文字變動率", "空白塊",
                            "盲評最佳率", "盲評最差率", "盲評淨分"], rows))

        export = root / "A_固定切段轉錄"
        for f in sorted((root / "asr_fixed").glob("*.json")):
            if f.name == "chunks.json":
                continue
            data = load(f)
            out = export / f.stem
            out.mkdir(parents=True, exist_ok=True)
            (out / "transcript.lrc").write_text(
                "\n".join(f"{ts(c['start'])} {c['text']}" for c in data["chunks"] if c["text"]), encoding="utf-8")
            (out / "transcript.txt").write_text(
                "\n".join(c["text"] for c in data["chunks"] if c["text"]), encoding="utf-8")

    ctx = load(root / "report" / "asr_context_metrics.json")
    if ctx:
        parts.append("## 附錄 4：附加實驗 — Qwen3-ASR 上下文提示（原始音檔、同一組切塊）")
        rows = [[k, m["token_mean_logprob"], m["cer_vs_ref"], m["glossary_good_total"], m["glossary_suspect_total"],
                 m.get("traditional_ratio")] for k, m in ctx["metrics"].items()]
        parts.append(table(["設定", "自信度", "與 K0 文字變動率", "正確領域詞", "典型誤聽詞(logo/label)", "繁體字比例"], rows))

    for ex_dir in sorted(root.glob("B_excerpt_*")):
        tm = load(ex_dir / "report" / "transcript_metrics.json")
        if not tm:
            continue
        parts.append(f"## 附錄 5：實驗 B — 完整 local 流程（{ex_dir.name}）")
        rows = []
        for vid, m in tm["metrics"].items():
            rows.append([vid, m["elapsed_minutes"], "是" if m["silence_removal_used"] else "否",
                         m["speakers_per_call"], m["diar_segments"], m["lines"], m["han_chars"],
                         m["coverage_speech_windows"], m["glossary_good_total"], m["glossary_suspect_total"],
                         (m.get("asr_confidence") or {}).get("token_mean_logprob"), m["mean_cer_vs_others"]])
        parts.append(table(["版本", "耗時(分)", "靜音移除", "說話者數", "分離段數", "行數", "漢字數",
                            "語音覆蓋率", "正確領域詞", "誤聽詞", "ASR自信度", "與其他版本平均CER"], rows))

    (root / "README.md").write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    print(root / "README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
