"""錄音前置分析：噪音底、人聲音量、SNR、頻譜、嗡聲/嘶聲、削波、頻寬、時間變化、各說話者音量。

語音/非語音的切分用 Silero VAD（與正式流程同一個模型）：
  speech 幀 = 位於 VAD 語音段內；noise 幀 = 離任何語音段邊界 > 0.3s 的非語音區
（避開語音起訖的殘響與漏切，讓噪音估計不被人聲污染）。

輸出（OUT_DIR）：
  analysis.json         全部數值
  level_timeline.csv    每 10 秒的噪音底 / 人聲音量 / SNR
  band_spectrum.csv     各頻帶人聲與噪音功率、頻帶 SNR
  spectrum_*.png        ffmpeg showspectrumpic 頻譜圖（全檔、局部放大）

用法：
  backend\\.venv\\Scripts\\python.exe tests\\denoise_study\\analyze_audio.py AUDIO OUT_DIR [--lrc 轉錄.lrc]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.ndimage import median_filter

FRAME_SECONDS = 0.02
NOISE_GUARD_SECONDS = 0.3
BAND_EDGES = [20, 80, 150, 300, 500, 1000, 2000, 3000, 4000, 6000, 8000, 11000, 16000, 22050]


def db(power):
    return 10 * np.log10(np.maximum(power, 1e-20))


def probe_sample_rate(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=sample_rate", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout
    return int(out.strip())


def decode(path: Path, sr: int) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def ebur128(path: Path) -> dict:
    log = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(path), "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    summary = log[log.rfind("Summary:"):]
    get = lambda key: float(re.search(key + r":\s+(-?[\d.]+)", summary).group(1))
    return {"integrated_lufs": get("I"), "loudness_range_lu": get("LRA"),
            "lra_low_lufs": get("LRA low"), "lra_high_lufs": get("LRA high")}


def vad_segments(path: Path) -> list[tuple[float, float]]:
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad
    wav = torch.from_numpy(decode(path, 16000))
    model = load_silero_vad()
    stamps = get_speech_timestamps(wav, model, sampling_rate=16000, return_seconds=True)
    return [(float(s["start"]), float(s["end"])) for s in stamps]


def interval_mask(times: np.ndarray, intervals, pad: float = 0.0) -> np.ndarray:
    mask = np.zeros(len(times), dtype=bool)
    for start, end in intervals:
        lo, hi = np.searchsorted(times, [start - pad, end + pad])
        mask[lo:hi] = True
    return mask


def parse_lrc_speakers(lrc: Path, total: float) -> list[tuple[float, float, str]]:
    rows = []
    for line in lrc.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\]\[(S\d+)\]", line)
        if m:
            rows.append((int(m.group(1)) * 60 + float(m.group(2)), m.group(3)))
    regions = []
    for i, (start, spk) in enumerate(rows):
        nxt = rows[i + 1][0] if i + 1 < len(rows) else total
        regions.append((start, min(nxt, start + 15.0), spk))
    return regions


def tonal_peaks(freqs, psd_db, max_freq=8000, top=12):
    sel = freqs <= max_freq
    f, p = freqs[sel], psd_db[sel]
    baseline = median_filter(p, size=41, mode="nearest")
    prominence = p - baseline
    idx, _ = signal.find_peaks(prominence, height=6.0, distance=3)
    idx = idx[np.argsort(prominence[idx])[::-1][:top]]
    return [{"freq_hz": round(float(f[i]), 1), "prominence_db": round(float(prominence[i]), 1),
             "level_db": round(float(p[i]), 1)} for i in sorted(idx)]


def hum_check(freqs, psd_db):
    result = {}
    df = freqs[1] - freqs[0]
    for f0 in (50, 60):
        proms = []
        for k in range(1, 7):
            target = f0 * k
            near = (np.abs(freqs - target) <= df * 0.75)
            ring = (np.abs(freqs - target) > df * 2.5) & (np.abs(freqs - target) <= df * 8)
            proms.append(round(float(psd_db[near].max() - np.median(psd_db[ring])), 1))
        result[f"{f0}hz_harmonics_prominence_db"] = proms
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--lrc", type=Path, help="含 [Sn] 說話者標籤的 LRC，用於各說話者音量")
    args = parser.parse_args()
    out: Path = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    sr = probe_sample_rate(args.audio)
    x = decode(args.audio, sr)
    total = len(x) / sr
    print(f"decoded {total:.1f}s @ {sr}Hz")

    report: dict = {"input": str(args.audio), "sample_rate": sr, "duration_seconds": round(total, 2)}

    # --- 全檔統計 ---
    peak = float(np.max(np.abs(x)))
    clipped = np.abs(x) >= 0.999
    runs = np.diff(np.flatnonzero(np.diff(np.concatenate([[0], clipped.view(np.int8), [0]]))))[::2]
    report["global"] = {
        "peak_dbfs": round(float(20 * np.log10(max(peak, 1e-9))), 2),
        "rms_dbfs": round(float(db(np.mean(x.astype(np.float64) ** 2))), 2),
        "dc_offset": float(np.mean(x)),
        "clipped_samples": int(clipped.sum()),
        "clip_runs_ge3": int(np.sum(runs >= 3)) if len(runs) else 0,
        **ebur128(args.audio),
    }

    # --- VAD 切分 ---
    speech = vad_segments(args.audio)
    speech_seconds = sum(e - s for s, e in speech)
    report["vad"] = {"segments": len(speech), "speech_seconds": round(speech_seconds, 1),
                     "speech_ratio": round(speech_seconds / total, 4)}

    # --- 幀能量 ---
    flen = int(FRAME_SECONDS * sr)
    nfr = len(x) // flen
    frames = x[:nfr * flen].reshape(nfr, flen)
    fpow = np.concatenate([np.einsum("ij,ij->i", c, c, dtype=np.float64) / flen
                           for c in np.array_split(frames, max(1, nfr // 20000))])
    fdb = db(fpow)
    ftime = (np.arange(nfr) + 0.5) * FRAME_SECONDS
    is_speech = interval_mask(ftime, speech)
    is_noise = ~interval_mask(ftime, speech, pad=NOISE_GUARD_SECONDS)

    ps, pn = fpow[is_speech].mean(), fpow[is_noise].mean()
    pct = lambda arr, q: round(float(np.percentile(arr, q)), 2)
    report["levels"] = {
        "speech_active_level_dbfs": round(float(db(ps)), 2),
        "speech_frame_db_p10_p50_p90": [pct(fdb[is_speech], q) for q in (10, 50, 90)],
        "noise_floor_mean_dbfs": round(float(db(pn)), 2),
        "noise_frame_db_p10_p50_p90": [pct(fdb[is_noise], q) for q in (10, 50, 90)],
        "all_frame_db_p5_p10_p50_p95_p99": [pct(fdb, q) for q in (5, 10, 50, 95, 99)],
        "snr_vad_db": round(float(db(max(ps - pn, 1e-20) / pn)), 2),
        "snr_percentile_p95_minus_p10_db": round(pct(fdb, 95) - pct(fdb, 10), 2),
        "noise_frames_seconds": round(float(is_noise.sum() * FRAME_SECONDS), 1),
    }

    # --- 非語音區暫態事件（鍵盤、碰撞、關門等）---
    noise_median = np.median(fdb[is_noise])
    spikes = is_noise & (fdb > noise_median + 15)
    spike_times = ftime[spikes]
    events = []
    for t in spike_times:
        if not events or t - events[-1][1] > 0.1:
            events.append([t, t])
        else:
            events[-1][1] = t
    loudest = sorted(events, key=lambda e: -fdb[int(e[0] / FRAME_SECONDS)])[:10]
    report["transients_in_nonspeech"] = {
        "threshold_db_above_noise_median": 15,
        "event_count": len(events),
        "events_per_minute_of_nonspeech": round(len(events) / max(report["levels"]["noise_frames_seconds"] / 60, 1e-9), 2),
        "loudest_at_seconds": [round(float(e[0]), 2) for e in loudest],
    }

    # --- 時間變化（每 10 秒）---
    rows = []
    win = int(10 / FRAME_SECONDS)
    for i in range(0, nfr, win):
        sl = slice(i, i + win)
        sp, nz = is_speech[sl], is_noise[sl]
        s_level = float(db(fpow[sl][sp].mean())) if sp.sum() > 25 else None
        n_level = float(db(fpow[sl][nz].mean())) if nz.sum() > 25 else None
        rows.append((i * FRAME_SECONDS, float(np.percentile(fdb[sl], 10)), n_level, s_level))
    with open(out / "level_timeline.csv", "w", encoding="utf-8") as fh:
        fh.write("start_s,frame_db_p10,noise_mean_db,speech_mean_db\n")
        for r in rows:
            fh.write(",".join("" if v is None else f"{v:.2f}" for v in r) + "\n")
    p10s = np.array([r[1] for r in rows])
    s_levels = np.array([r[3] for r in rows if r[3] is not None])
    report["stationarity"] = {
        "window_seconds": 10,
        "noise_floor_p10_db_min_median_max": [round(float(p10s.min()), 1), round(float(np.median(p10s)), 1), round(float(p10s.max()), 1)],
        "noise_floor_p10_db_std": round(float(p10s.std()), 2),
        "speech_level_db_min_median_max": [round(float(s_levels.min()), 1), round(float(np.median(s_levels)), 1), round(float(s_levels.max()), 1)],
        "speech_level_db_std": round(float(s_levels.std()), 2),
    }

    # --- 頻譜：分塊 STFT，依幀中心時間歸入 speech / noise ---
    nper = 4096 if sr > 24000 else 2048
    hop = nper // 2
    freqs = np.fft.rfftfreq(nper, 1 / sr)
    window = signal.get_window("hann", nper)
    acc = {"speech": np.zeros(len(freqs)), "noise": np.zeros(len(freqs)), "all": np.zeros(len(freqs))}
    cnt = {"speech": 0, "noise": 0, "all": 0}
    chunk = sr * 60
    for c0 in range(0, len(x) - nper, chunk):
        seg = x[c0:c0 + chunk + nper].astype(np.float64)
        n_frames = (len(seg) - nper) // hop + 1
        idx = np.arange(nper)[None, :] + hop * np.arange(n_frames)[:, None]
        spec = np.abs(np.fft.rfft(seg[idx] * window, axis=1)) ** 2
        centers = (c0 + hop * np.arange(n_frames) + nper / 2) / sr
        keep = centers < (c0 + chunk) / sr  # 下一塊負責重疊區，避免重複計數
        spec, centers = spec[keep], centers[keep]
        sm = interval_mask(centers, speech)
        nm = ~interval_mask(centers, speech, pad=NOISE_GUARD_SECONDS)
        for key, m in (("speech", sm), ("noise", nm), ("all", np.ones(len(centers), bool))):
            acc[key] += spec[m].sum(axis=0)
            cnt[key] += int(m.sum())
    psd = {k: acc[k] / max(cnt[k], 1) for k in acc}
    psd_db = {k: db(v) for k, v in psd.items()}

    bands = []
    for lo, hi in zip(BAND_EDGES[:-1], BAND_EDGES[1:]):
        if lo >= sr / 2:
            break
        sel = (freqs >= lo) & (freqs < hi)
        s_pow, n_pow = psd["speech"][sel].sum(), psd["noise"][sel].sum()
        bands.append({"band_hz": f"{lo}-{hi}", "speech_db": round(float(db(s_pow)), 1),
                      "noise_db": round(float(db(n_pow)), 1),
                      "band_snr_db": round(float(db(max(s_pow - n_pow, 1e-20) / n_pow)), 1)})
    with open(out / "band_spectrum.csv", "w", encoding="utf-8") as fh:
        fh.write("band_hz,speech_db,noise_db,band_snr_db\n")
        for b in bands:
            fh.write(f"{b['band_hz']},{b['speech_db']},{b['noise_db']},{b['band_snr_db']}\n")
    report["bands"] = bands

    voiced = (freqs >= 100) & (freqs <= 8000)
    nv = psd["noise"][voiced]
    report["noise_character"] = {
        "spectral_flatness_100_8000hz": round(float(np.exp(np.mean(np.log(nv))) / np.mean(nv)), 4),
        "tonal_peaks_in_noise": tonal_peaks(freqs, psd_db["noise"]),
        **hum_check(freqs, psd_db["noise"]),
    }

    # 有效頻寬：長時平均頻譜在 4kHz 以上首次跌破「4-8kHz 中位數 − 30dB」的頻率（AAC 低通截止）
    ref = np.median(psd_db["all"][(freqs >= 4000) & (freqs <= 8000)])
    above = np.flatnonzero((freqs > 4000) & (median_filter(psd_db["all"], 9) < ref - 30))
    report["effective_bandwidth_hz"] = round(float(freqs[above[0]]), 0) if len(above) else round(sr / 2, 0)

    # --- 各說話者音量 ---
    if args.lrc and args.lrc.exists():
        spk_stats = {}
        for start, end, spk in parse_lrc_speakers(args.lrc, total):
            m = is_speech & (ftime >= start) & (ftime < end)
            spk_stats.setdefault(spk, []).append(fpow[m])
        report["speakers_from_lrc"] = {
            spk: {
                "speech_seconds": round(float(sum(len(a) for a in arrs) * FRAME_SECONDS), 1),
                "active_level_dbfs": round(float(db(np.concatenate(arrs).mean())), 2),
                "snr_vs_noise_floor_db": round(float(db(max(np.concatenate(arrs).mean() - pn, 1e-20) / pn)), 2),
                "frame_db_p10_p50_p90": [pct(db(np.concatenate(arrs)), q) for q in (10, 50, 90)],
            }
            for spk, arrs in sorted(spk_stats.items()) if sum(len(a) for a in arrs)
        }

    # --- 頻譜圖 ---
    pics = [
        ("spectrum_full.png", [], "s=2400x900:legend=1:scale=log:fscale=lin:color=viridis"),
        ("spectrum_excerpt_00m00s_60s.png", ["-t", "60"], "s=2400x900:legend=1:scale=log:fscale=lin:color=viridis"),
        ("spectrum_excerpt_05m00s_60s.png", ["-ss", "300", "-t", "60"], "s=2400x900:legend=1:scale=log:fscale=lin:color=viridis"),
        ("spectrum_lowfreq_0_1000hz_60s.png", ["-t", "60"], "s=2400x900:legend=1:scale=log:fscale=lin:color=viridis:start=0:stop=1000"),
    ]
    for name, cut, opts in pics:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *cut, "-i", str(args.audio),
                        "-lavfi", f"showspectrumpic={opts}", str(out / name)], check=False)

    (out / "analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("bands",)}, ensure_ascii=False, indent=2))
    print("bands:")
    for b in bands:
        print(f"  {b['band_hz']:>12}  speech {b['speech_db']:7.1f}  noise {b['noise_db']:7.1f}  snr {b['band_snr_db']:6.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
