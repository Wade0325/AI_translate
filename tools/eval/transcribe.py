"""``python -m tools.eval transcribe``：跑正式的轉錄路徑，輸出轉錄結果（LRC）與 manifest。

和 eval、selftest 不同，這條指令會讀音檔、用顯卡：直接呼叫轉錄任務用的
``app.tasks.transcribe_core.transcribe_audio``（去靜音、分段轉錄、所選的供應商轉接器），
不經 API、任務佇列與資料庫，所以不必啟動 Docker 或前端。設定和應用程式讀同一份。

只跑不需要 API 金鑰的供應商（本機），音檔不離開這台電腦。manifest 只記數字與環境
（commit、套件版本、顯卡、模型權重的 revision、設定、耗時），不記任何轉錄文字，可以貼進 PR；
轉錄結果的 LRC 交給 ``python -m tools.eval eval`` 計分。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .cli import REPO_ROOT, UsageError, _git, _refuse_writing_references, default_lab_dir

FIRST_STAGE = "建立供應商轉接器"
"""第一則進度訊息之前的階段：轉錄任務從建立供應商轉接器開始，本機轉接器在這裡確認權重。"""

_COUNTER = re.compile(r"\d+(?:\.\d+)?")
"""進度訊息裡的計數（「MOSS 轉錄中 3/38 分鐘...」），換成 # 後同一個階段的訊息才併得起來。"""

_GPU_NOTICE = """\
這次用本機模型在顯卡上轉錄，一次只用一張顯卡（CUDA_VISIBLE_DEVICES={devices}）。
開始前請先停掉其他使用顯卡的工作：local_worker、Docker 裡的 GPU 任務、正在轉錄的應用程式；
和它們搶顯存會讓這次的耗時與峰值顯存不準，也可能顯存不足而失敗。"""


def cmd_transcribe(args) -> int:
    audio = Path(args.audio)
    if not audio.is_file():
        raise UsageError(f"找不到音檔：{audio}")
    out = Path(args.out)
    _refuse_writing_references(out, [default_lab_dir() / "data" / "eval"], option="--out")
    transcript = out / f"{audio.stem}.lrc"
    manifest_path = out / f"{audio.stem}.manifest.json"
    existing = [p.name for p in (transcript, manifest_path) if p.exists()]
    if existing:
        raise UsageError(f"{out} 已經有 {'、'.join(existing)}：不覆寫上一次的結果，"
                         f"換一個 --out 或先移走它們。")

    _import_backend()
    from app.provider.base import LOCAL_QUEUE

    provider, model, capabilities = _resolve_model(args.provider, args.model)
    if capabilities.queue == LOCAL_QUEUE:
        devices = os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
        if "," in devices:
            raise UsageError(f"CUDA_VISIBLE_DEVICES={devices} 指定了不只一張顯卡；"
                             f"評測一次只用一張，例如設成 0。")
        print(_GPU_NOTICE.format(devices=devices))
        if not args.yes:
            try:
                input("確認後按 Enter 開始（Ctrl+C 取消）：")
            except (EOFError, KeyboardInterrupt):
                print("\n已取消，沒有轉錄。")
                return 1

    code = {"commit": _git("rev-parse", "HEAD", cwd=REPO_ROOT),
            "dirty": _dirty()}
    out.mkdir(parents=True, exist_ok=True)
    run, lines = _run(audio, provider, model, args.language, transcript)
    duration = run.pop("audio_duration_seconds")

    from app.services import environment_manifest

    manifest = {
        "command": "transcribe",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "request": {"provider": provider, "model": model, "language": args.language},
        "audio": {"file": audio.name, "sha256": _sha256(audio), "duration_seconds": duration},
        "code": code,
        "environment": environment_manifest.describe(provider, model),
        "run": run,
        "outputs": {"transcript": transcript.name if run["success"] else None},
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if not run["success"]:
        print(f"\n轉錄失敗：{run['error']}\nmanifest：{manifest_path}", file=sys.stderr)
        return 1
    vram = "（沒有用到顯卡）" if run["peak_vram_gb"] is None else f"{run['peak_vram_gb']} GB"
    print(f"\n轉錄結果：{transcript}（{lines} 行）\nmanifest：{manifest_path}\n"
          f"耗時 {run['seconds']} 秒，RTF {run['rtf']}，峰值顯存 {vram}\n"
          f"計分：python -m tools.eval eval --reference <名稱> --transcript {transcript}")
    return 0


def _import_backend() -> None:
    """``app`` 在 backend/ 底下；從 repo 根目錄執行時它不在 import 路徑上。"""
    backend = str(REPO_ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)


def _resolve_model(provider: str, model: str | None):
    """驗證供應商與模型，回傳供應商清單上的名稱、模型（沒指定時是預設模型）與模型能力。"""
    from app.provider import registry

    listed = {p.provider: p for p in registry.providers()}
    entry = listed.get(provider.lower())
    if entry is None:
        raise UsageError(f"沒有供應商 {provider}；可以用的有：{'、'.join(listed)}")
    if entry.requires_api_key:
        raise UsageError(f"供應商 {entry.provider} 要 API 金鑰，會把音檔送出這台電腦；"
                         f"這個指令只跑不需要 API 金鑰的供應商，例如 local。")
    models = [m.model for m in entry.models]
    model = model or models[0]
    if model not in models:
        raise UsageError(f"模型 {model} 不屬於供應商 {entry.provider}；可以用的有：{'、'.join(models)}")
    return entry.provider, model, registry.model_capabilities(entry.provider, model)


def _run(audio: Path, provider: str, model: str, language: str,
         transcript: Path) -> tuple[dict[str, Any], int]:
    """轉錄一次，成功時寫出 LRC；回傳 manifest 的 run 區塊（另帶音檔長度）與 LRC 的行數。"""
    from app.celery.models import TranscriptionTaskParams
    from app.provider.base import ProgressAndCancel
    from app.services import output_format
    from app.tasks.transcribe_core import transcribe_audio
    from app.utils.audio import get_audio_duration

    task_id = f"eval-{uuid.uuid4().hex[:12]}"
    params = TranscriptionTaskParams(
        file_path=str(audio), provider=provider, model=model, api_keys="",
        source_lang=language, original_filename=audio.name,
        client_id="tools.eval", file_uid=task_id)
    start = time.perf_counter()
    reports: list[tuple[float, str | None]] = [(0.0, None)]
    progress = ProgressAndCancel(
        report=lambda text: reports.append((time.perf_counter() - start, text)),
        cancel_requested=lambda: False)

    error = None
    lines = 0
    segments = 0
    try:
        result = transcribe_audio(params, task_id, audio, progress)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    else:
        if result.success and result.segments:
            segments = len(result.segments)
            lrc = output_format.for_result(result).lrc
            transcript.write_text(lrc, encoding="utf-8")
            lines = len(lrc.splitlines())
        else:
            error = result.text or "沒有轉錄出任何片段"
    seconds = time.perf_counter() - start

    duration = get_audio_duration(audio)
    return {
        "success": error is None,
        "error": error,
        "segments": segments,
        "seconds": round(seconds, 3),
        "rtf": round(seconds / duration, 4) if duration else None,
        "peak_vram_gb": _peak_vram_gb(),
        "stages": _stages(reports, end=seconds),
        "audio_duration_seconds": duration,
    }, lines


def _stages(reports: list[tuple[float, str | None]], end: float) -> list[dict[str, Any]]:
    """依進度訊息把整段耗時切成各階段：每則訊息到下一則（最後一則到 ``end``）算它的階段。

    ``reports`` 是（從開始算起的秒數，進度訊息）；第一筆是開始，訊息是 None。訊息裡的計數換成
    #，連續的同一個階段併成一筆。
    """
    stages: list[dict[str, Any]] = []
    for (at, text), (until, _) in zip(reports, [*reports[1:], (end, None)], strict=True):
        name = FIRST_STAGE if text is None else _COUNTER.sub("#", text)
        if stages and stages[-1]["stage"] == name:
            stages[-1]["seconds"] += until - at
        else:
            stages.append({"stage": name, "seconds": until - at})
    for stage in stages:
        stage["seconds"] = round(stage["seconds"], 3)
    return stages


def _peak_vram_gb() -> float | None:
    """這次轉錄 PyTorch 向顯卡要過的最大顯存（``max_memory_reserved``，不含 CUDA 本身佔用的部分）；
    沒有用到顯卡時是 None。"""
    torch = sys.modules.get("torch")
    if torch is None:
        return None
    try:
        # is True：測試環境裡 torch 是 mock，回傳的不是 bool
        if torch.cuda.is_available() is not True:
            return None
        return round(torch.cuda.max_memory_reserved() / 1024 ** 3, 2)
    except Exception:
        return None


def _dirty() -> bool | None:
    status = _git("status", "--porcelain", cwd=REPO_ROOT)
    return None if status is None else bool(status)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
