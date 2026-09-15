"""產生各種降噪版本，每個方法一個資料夾：denoised/{id}/{id}.wav + params.json。

輸出一律為 WAV：正式流程的 convert_to_wav 對 .wav 直接放行、其他格式轉 16kHz，
若輸出成壓縮格式會把「取樣率差異」混進比較。01_original_wav 是不做任何處理的
無損解碼對照組，用來把「取樣率路徑」與「降噪效果」分開。

方法（--only 指定 id，可多個；預設全部）：
  01_original_wav        無處理對照（原生 44.1kHz 無損解碼）
  02_hpf_notch           高通 100Hz（24dB/oct）+ 120Hz / 75Hz 陷波：只砍低頻隆隆聲與嗡聲
  03_afftdn              02 + ffmpeg afftdn（FFT 頻譜減法，追蹤噪音底、增益平滑）
  04_rnnoise_mix50       02 + ffmpeg arnndn（RNNoise std 模型），濾波/原訊號各半
  05_dfn3                DeepFilterNet3 全力降噪（失真代價對照組）
  06_dfn3_lim12          DeepFilterNet3，衰減上限 12dB（= 混回 25% 原訊號）
  07_noisereduce         02 + noisereduce 非穩態頻譜閘控（prop_decrease 0.6）
  08_mossformer2_48k     ClearerVoice MossFormer2_SE_48K 全力降噪
  09_frcrn_16k           ClearerVoice FRCRN_SE_16K 全力降噪（16kHz）
  10_mossformer2_oa50    0.5×08 + 0.5×02（observation adding ω=0.5）
  11_hpf_dfn3_lim6       02 + DeepFilterNet3 衰減上限 6dB（= ω=0.5）
  12_frcrn_oa50          0.5×09 + 0.5×02（16kHz）
  13_splitvad_dfn3       分流：VAD 靜音判定用 05（乾淨噪音底才切得出靜音），
                         分離/轉錄吃 02 的音訊（音檔為 02 的硬連結，vad_source.txt 指向 05）

observation adding / 衰減上限的依據：Iwamoto et al. Interspeech 2022 等研究指出增強失真
（artifact）比殘留噪音更傷 ASR，把增強結果與原訊號按比例混合可抵銷，ω≈0.5 常為最佳。

需要的工具：ffmpeg（PATH）、deep-filter.exe 與 rnnoise 模型（--tools 目錄），
07~10 需在裝有 noisereduce / clearvoice 的 venv 執行。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

HPF_NOTCH = ("highpass=f=100:poles=2,highpass=f=100:poles=2,"
             "bandreject=f=120:width_type=h:w=10,bandreject=f=75:width_type=h:w=8")


def run(cmd: list[str], cwd: Path | None = None) -> None:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} 失敗: {proc.stderr[-800:]}")


def ffmpeg_filter(src: Path, dst: Path, af: str | None, sr: int | None = None, cwd: Path | None = None) -> None:
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src)]
    if af:
        cmd += ["-af", af]
    cmd += ["-ac", "1"]
    if sr:
        cmd += ["-ar", str(sr)]
    cmd += ["-c:a", "pcm_s16le", str(dst)]
    run(cmd, cwd=cwd)


def estimate_lag(ref: np.ndarray, test: np.ndarray, sr: int, max_ms: float = 200) -> int:
    """以 60~90s 片段互相關估計 test 相對 ref 的延遲（樣本數，正值 = test 較晚）。"""
    a = ref[60 * sr:90 * sr].astype(np.float64)
    b = test[60 * sr:90 * sr].astype(np.float64)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    max_lag = int(max_ms / 1000 * sr)
    spec = np.fft.rfft(b) * np.conj(np.fft.rfft(a))
    xcorr = np.fft.irfft(spec / (np.abs(spec) + 1e-12), n)
    lags = np.concatenate([xcorr[:max_lag + 1], xcorr[-max_lag:]])
    idx = int(np.argmax(lags))
    return idx if idx <= max_lag else idx - (2 * max_lag + 1)


def load_mono(path: Path, sr: int) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def align_to(ref: np.ndarray, test: np.ndarray, sr: int) -> tuple[np.ndarray, int]:
    lag = estimate_lag(ref, test, sr)
    if lag > 0:
        test = test[lag:]
    elif lag < 0:
        test = np.concatenate([np.zeros(-lag, dtype=test.dtype), test])
    out = np.zeros(len(ref), dtype=np.float32)
    out[:min(len(ref), len(test))] = test[:len(ref)]
    return out, lag


class Ctx:
    def __init__(self, source: Path, root: Path, tools: Path):
        self.source = source
        self.root = root
        self.tools = tools
        self.work = root / "denoised" / "_work"
        self.work.mkdir(parents=True, exist_ok=True)

    def wav48(self) -> Path:
        path = self.work / "original_48k.wav"
        if not path.exists():
            ffmpeg_filter(self.source, path, None, sr=48000)
        return path

    def wav16(self) -> Path:
        path = self.work / "original_16k.wav"
        if not path.exists():
            ffmpeg_filter(self.source, path, None, sr=16000)
        return path

    def variant(self, vid: str) -> Path:
        return self.root / "denoised" / vid / f"{vid}.wav"


# ---------------------------------------------------------------- 方法實作

def m_original_wav(ctx: Ctx, out: Path) -> dict:
    ffmpeg_filter(ctx.source, out, None)
    return {"desc": "無處理，原生取樣率無損解碼（對照組）"}


def m_hpf_notch(ctx: Ctx, out: Path) -> dict:
    ffmpeg_filter(ctx.source, out, HPF_NOTCH)
    return {"desc": "高通 100Hz 兩級（約 24dB/oct）+ 120Hz（市電二次諧波）/ 75Hz 陷波；"
                    "分析顯示 150Hz 以下頻帶 SNR 為負、兩處嗡聲峰", "ffmpeg_af": HPF_NOTCH}


def m_afftdn(ctx: Ctx, out: Path) -> dict:
    # 5 分鐘片段實測校準：nf 不是 dBFS，本檔 −42 以下或開 tn=1（噪音追蹤）時 nr 設多少都
    # 等於沒作用；nf −20 噪音 −4.5dB 但人聲 −2.3dB，−30 噪音 −2.9dB / 人聲 −0.8dB，取中間值
    af = HPF_NOTCH + ",afftdn=nr=20:nf=-25"
    ffmpeg_filter(ctx.source, out, af)
    return {"desc": "02 + afftdn 頻譜減法：降噪量 20dB、噪音底 −25（ffmpeg 內部刻度，片段實測校準；"
                    "開啟噪音追蹤 tn=1 在本檔會使降噪失效故不用）", "ffmpeg_af": af}


def m_rnnoise_mix50(ctx: Ctx, out: Path) -> dict:
    af = HPF_NOTCH + ",arnndn=m=std.rnnn:mix=0.5"
    ffmpeg_filter(ctx.source, out, af, sr=48000, cwd=ctx.tools / "rnnoise")
    return {"desc": "02 + RNNoise（ffmpeg arnndn，Xiph 原版 std.rnnn，48kHz），mix=0.5 濾波/原訊號各半",
            "ffmpeg_af": af}


def _deep_filter(ctx: Ctx, out: Path, atten_lim: float | None, src: Path) -> dict:
    tmp_dir = ctx.work / f"dfn_{out.stem}"
    tmp_dir.mkdir(exist_ok=True)
    cmd = [str(ctx.tools / "deep-filter.exe"), "-D", "-o", str(tmp_dir)]
    if atten_lim is not None:
        cmd += ["-a", str(atten_lim)]
    run(cmd + [str(src)])
    shutil.move(str(tmp_dir / src.name), out)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    lim = atten_lim if atten_lim is not None else 100
    return {"desc": "DeepFilterNet3（deep-filter 0.5.6 CLI，48kHz，-D 延遲補償）",
            "input": src.name, "atten_lim_db": lim, "equivalent_oa_weight": round(10 ** (-lim / 20), 4)}


def m_dfn3(ctx: Ctx, out: Path) -> dict:
    return _deep_filter(ctx, out, None, ctx.wav48())


def m_dfn3_lim12(ctx: Ctx, out: Path) -> dict:
    return _deep_filter(ctx, out, 12, ctx.wav48())


def m_hpf_dfn3_lim6(ctx: Ctx, out: Path) -> dict:
    src = ctx.work / "hpf_notch_48k.wav"
    if not src.exists():
        ffmpeg_filter(ctx.source, src, HPF_NOTCH, sr=48000)
    return _deep_filter(ctx, out, 6, src) | {"prefilter": HPF_NOTCH}


def m_noisereduce(ctx: Ctx, out: Path) -> dict:
    import noisereduce as nr
    params = dict(stationary=False, prop_decrease=0.6, time_constant_s=2.0,
                  freq_mask_smooth_hz=500, time_mask_smooth_ms=50, n_fft=2048, chunk_size=600000)
    src = ctx.work / "hpf_notch_48k.wav"
    if not src.exists():
        ffmpeg_filter(ctx.source, src, HPF_NOTCH, sr=48000)
    data, sr = sf.read(str(src), dtype="float32")
    reduced = nr.reduce_noise(y=data, sr=sr, **params)
    sf.write(str(out), reduced, sr, subtype="PCM_16")
    return {"desc": "02 + noisereduce 非穩態頻譜閘控（噪音統計隨時間更新，適合噪音底會飄的錄音）",
            "prefilter": HPF_NOTCH, **params}


_CLEARVOICE_CACHE: dict = {}


def _clearvoice(ctx: Ctx, out: Path, model: str, src: Path) -> dict:
    from clearvoice import ClearVoice
    if model not in _CLEARVOICE_CACHE:
        _CLEARVOICE_CACHE.clear()
        _CLEARVOICE_CACHE[model] = ClearVoice(task="speech_enhancement", model_names=[model])
    cv = _CLEARVOICE_CACHE[model]
    enhanced = cv(input_path=str(src), online_write=False)
    tmp = ctx.work / f"{out.stem}_raw.wav"
    cv.write(enhanced, output_path=str(tmp))
    # 對齊檢查：與原檔互相關，非零延遲則補償（混音 variant 需要逐樣本對齊）
    info = sf.info(str(tmp))
    ref = load_mono(src, info.samplerate)
    test, _ = sf.read(str(tmp), dtype="float32")
    if test.ndim > 1:
        test = test.mean(axis=1)
    aligned, lag = align_to(ref, test, info.samplerate)
    sf.write(str(out), aligned, info.samplerate, subtype="PCM_16")
    tmp.unlink(missing_ok=True)
    return {"desc": f"ClearerVoice-Studio {model}", "sample_rate": info.samplerate, "detected_lag_samples": lag}


def m_mossformer2(ctx: Ctx, out: Path) -> dict:
    return _clearvoice(ctx, out, "MossFormer2_SE_48K", ctx.wav48())


def m_frcrn(ctx: Ctx, out: Path) -> dict:
    return _clearvoice(ctx, out, "FRCRN_SE_16K", ctx.wav16())


def _observation_adding(ctx: Ctx, out: Path, enh_vid: str, noisy_vid: str, weight: float) -> dict:
    """out = (1-ω)·enhanced + ω·noisy，noisy 以互相關對齊到 enhanced。"""
    enh_path, noisy_path = ctx.variant(enh_vid), ctx.variant(noisy_vid)
    for p in (enh_path, noisy_path):
        if not p.exists():
            raise RuntimeError(f"需要先產生 {p.parent.name}")
    enh, sr = sf.read(str(enh_path), dtype="float32")
    noisy_aligned, lag = align_to(enh, load_mono(noisy_path, sr), sr)
    mixed = (1 - weight) * enh + weight * noisy_aligned
    peak = float(np.max(np.abs(mixed)))
    if peak > 0.999:
        mixed *= 0.999 / peak
    sf.write(str(out), mixed, sr, subtype="PCM_16")
    return {"desc": f"observation adding：(1-ω)×{enh_vid} + ω×{noisy_vid}，ω={weight}；"
                    "以殘留部分原噪音換取掩蓋增強失真", "enhanced": enh_vid, "noisy": noisy_vid,
            "weight": weight, "detected_lag_samples": lag}


def m_mossformer2_oa50(ctx: Ctx, out: Path) -> dict:
    return _observation_adding(ctx, out, "08_mossformer2_48k", "02_hpf_notch", 0.5)


def m_frcrn_oa50(ctx: Ctx, out: Path) -> dict:
    return _observation_adding(ctx, out, "09_frcrn_16k", "02_hpf_notch", 0.5)


def m_splitvad_dfn3(ctx: Ctx, out: Path) -> dict:
    asr_src, vad_src = ctx.variant("02_hpf_notch"), ctx.variant("05_dfn3")
    for p in (asr_src, vad_src):
        if not p.exists():
            raise RuntimeError(f"需要先產生 {p.parent.name}")
    out.unlink(missing_ok=True)
    try:
        out.hardlink_to(asr_src)
    except OSError:
        shutil.copy2(asr_src, out)
    (out.parent / "vad_source.txt").write_text(str(vad_src), encoding="utf-8")
    return {"desc": "分流（DIHARD II 做法）：正式流程的 RMS VAD 靜音判定改在 05_dfn3 上做，"
                    "切出的時間段套回 02_hpf_notch 音訊再送分離/轉錄；需 run_local_pipeline --vad-audio",
            "asr_audio": asr_src.parent.name, "vad_audio": vad_src.parent.name}


METHODS = {
    "01_original_wav": m_original_wav,
    "02_hpf_notch": m_hpf_notch,
    "03_afftdn": m_afftdn,
    "04_rnnoise_mix50": m_rnnoise_mix50,
    "05_dfn3": m_dfn3,
    "06_dfn3_lim12": m_dfn3_lim12,
    "07_noisereduce": m_noisereduce,
    "08_mossformer2_48k": m_mossformer2,
    "09_frcrn_16k": m_frcrn,
    "10_mossformer2_oa50": m_mossformer2_oa50,
    "11_hpf_dfn3_lim6": m_hpf_dfn3_lim6,
    "12_frcrn_oa50": m_frcrn_oa50,
    "13_splitvad_dfn3": m_splitvad_dfn3,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("root", type=Path, help="研究輸出根目錄（其下建立 denoised/{id}/）")
    parser.add_argument("--tools", type=Path, default=Path(r"D:\AI_translate\models\denoise_tools"))
    parser.add_argument("--only", nargs="*", help="只跑指定 id")
    parser.add_argument("--force", action="store_true", help="已存在也重做")
    args = parser.parse_args()

    ctx = Ctx(args.source, args.root, args.tools)
    selected = args.only or list(METHODS)
    failed = 0
    for vid in selected:
        out = ctx.variant(vid)
        if out.exists() and not args.force:
            print(f"[略過] {vid} 已存在")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        print(f"[執行] {vid} ...", flush=True)
        started = time.time()
        try:
            params = METHODS[vid](ctx, out)
        except Exception as e:
            failed += 1
            print(f"[失敗] {vid}: {e}", flush=True)
            continue
        info = sf.info(str(out))
        params.update({"id": vid, "source": str(args.source), "output": out.name,
                       "output_sample_rate": info.samplerate, "output_seconds": round(info.duration, 2),
                       "elapsed_seconds": round(time.time() - started, 1)})
        (out.parent / "params.json").write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[完成] {vid}（{params['elapsed_seconds']}s）", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
