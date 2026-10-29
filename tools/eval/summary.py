"""``python -m tools.eval summary``：把一次評測整理成 PR 範本的「評測摘要」（#38）。

讀 ``eval --json`` 寫的檔案，以及每份轉錄結果旁邊、``transcribe`` 寫的 manifest
（``<音檔名稱>.manifest.json``），印出一段 Markdown：指令、commit、模型與語言、錯字率與 cpMER、
ΔMER 與 95% CI、RTF 與峰值顯存、結尾核對，以及判定。

只輸出數字、雜湊與檔名，不輸出錯誤範例或任何轉錄文字：評測集的原文不進 PR（#15 的 Q4）。
結尾核對只讀 LRC 每一行的時間戳。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import lrc
from .cli import UsageError

VERDICT = "待回歸判定"
"""判定規則（docs/adr/0009）還沒做進來，先一律這樣寫。"""


@dataclass
class _System:
    """一份轉錄結果：eval 的分數、它的 manifest，以及 LRC 最後一行的開始時間。"""

    transcript: Path
    score: dict[str, Any]
    manifest: dict[str, Any] | None
    last_line: float | None


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, rest = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{rest:02d}" if hours else f"{minutes}:{rest:02d}"


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def _load(path: Path, what: str) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise UsageError(f"找不到 {what}：{path}") from None
    except json.JSONDecodeError as e:
        raise UsageError(f"{what} 不是 JSON：{path}（{e}）") from None


def _system(score: dict[str, Any], eval_dir: Path) -> _System:
    """找出轉錄結果與它旁邊的 manifest；eval 存的是相對路徑時，先照目前目錄找，再照 JSON 所在的資料夾找。"""
    transcript = Path(score["transcript"])
    if not transcript.is_file() and not transcript.is_absolute():
        transcript = eval_dir / transcript
    manifest_path = transcript.with_name(f"{transcript.stem}.manifest.json")
    manifest = _load(manifest_path, "manifest") if manifest_path.is_file() else None
    last_line = None
    if transcript.is_file():
        lines = lrc.read(transcript).lines
        last_line = max((line.seconds for line in lines), default=None)
    return _System(transcript, score, manifest, last_line)


def _get(manifest: dict[str, Any] | None, *keys: str) -> Any:
    value: Any = manifest
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _commit(system: _System) -> str:
    commit = _get(system.manifest, "code", "commit")
    if not commit:
        return "—"
    dirty = "（有沒 commit 的改動）" if _get(system.manifest, "code", "dirty") else ""
    return f"`{commit[:12]}`{dirty}"


def _request(system: _System) -> str:
    request = _get(system.manifest, "request") or {}
    parts = [request.get(k) for k in ("provider", "model", "language")]
    return "／".join(p for p in parts if p) or "—"


def _rtf(system: _System) -> str:
    rtf = _get(system.manifest, "run", "rtf")
    return "—" if rtf is None else f"{rtf:.3f}"


def _vram(system: _System) -> str:
    if system.manifest is None:
        return "—"
    vram = _get(system.manifest, "run", "peak_vram_gb")
    return "沒有用到顯卡" if vram is None else f"{vram} GB"


def _tail(system: _System) -> str:
    """LRC 最後一行開始的時間，和音檔長度比：之後還剩多久沒有字。"""
    duration = _get(system.manifest, "audio", "duration_seconds")
    if system.last_line is None:
        return "—"
    if duration is None:
        return f"最後一行 {_clock(system.last_line)}"
    gap = duration - system.last_line
    return f"最後一行 {_clock(system.last_line)}，音檔 {_clock(duration)}，之後 {gap:.0f} 秒沒有字"


def _transcribe_command(manifest: dict[str, Any]) -> str:
    request = manifest.get("request") or {}
    audio = _get(manifest, "audio", "file") or "<音檔>"
    return (f"python -m tools.eval transcribe --audio {audio} --provider {request.get('provider')} "
            f"--model {request.get('model')} --language {request.get('language')}")


def render(result: dict[str, Any], systems: list[_System]) -> str:
    """評測摘要的 Markdown；只有數字、雜湊與檔名。"""
    labels = ["轉錄結果"] if len(systems) == 1 else ["基準（--transcript）", "這個 PR（--vs）"]
    manifests = [s.manifest for s in systems if s.manifest]
    audio = manifests[0].get("audio", {}) if manifests else {}
    title = audio.get("file") or systems[0].transcript.name

    rows = [
        ("commit", _commit),
        ("模型與語言", _request),
        ("錯字率（MER）", lambda s: _percent(s.score.get("total_mer"))),
        ("cpMER（全域對應）", lambda s: _percent(s.score.get("cp_mer_global"))),
        ("RTF", _rtf),
        ("峰值顯存", _vram),
        ("結尾核對", _tail),
    ]
    out = [f"### 評測摘要：{title}", "",
           "| | " + " | ".join(labels) + " |",
           "|---|" + "---|" * len(labels)]
    out += [f"| {name} | " + " | ".join(cell(s) for s in systems) + " |" for name, cell in rows]
    out.append("")

    paired = result.get("paired")
    if paired:
        low, high = paired["ci"]
        sig = "顯著" if paired["significant"] else "不顯著（區間跨 0）"
        out.append(f"- ΔMER（這個 PR − 基準）：{paired['delta_mer'] * 100:+.2f} pp，"
                   f"95% CI [{low * 100:+.2f}, {high * 100:+.2f}]，{sig}")
    if audio:
        out.append(f"- 音檔：`{audio.get('file')}`（SHA-256 `{str(audio.get('sha256'))[:16]}…`，"
                   f"長度 {_clock(audio.get('duration_seconds'))}）")
    hashes = {_get(m, "audio", "sha256") for m in manifests}
    if len(hashes) > 1:
        out.append("- ⚠ 兩邊轉錄的音檔不同（SHA-256 不一樣），比較不成立")
    references = [Path(p).name.removesuffix(".txt") for p in result.get("reference", [])]
    drafts = result.get("reference_draft_marks") or 0
    draft_note = f"，草稿標記 {drafts} 處：數字只能當工具驗證，不能當結論" if drafts else ""
    out.append(f"- 標準答案：{'、'.join(references) or '—'}{draft_note}")
    commands = sorted({_transcribe_command(m) for m in manifests})
    vs = " --vs <這個 PR 的 LRC>" if len(systems) == 2 else ""
    commands.append(f"python -m tools.eval eval --reference {' '.join(references)} "
                    f"--transcript <基準的 LRC>{vs} --bootstrap {result.get('bootstrap')}")
    out.append("- 指令：" + "；".join(f"`{c}`" for c in commands))
    if result.get("tool_version"):
        out.append(f"- 計分工具：tools/eval @ `{result['tool_version'][:12]}`"
                   + ("（有沒 commit 的改動）" if result["tool_version"].endswith("+dirty") else ""))
    missing = [s.transcript.name for s in systems if s.manifest is None]
    if missing:
        out.append(f"- 找不到 manifest（轉錄結果旁邊的 <音檔名稱>.manifest.json）：{'、'.join(missing)}")
    out.append(f"- 判定：{VERDICT}")
    return "\n".join(out) + "\n"


def cmd_summary(args) -> int:
    path = Path(args.eval_json)
    result = _load(path, "eval 的 JSON")
    if result.get("command") != "eval" or not result.get("systems"):
        raise UsageError(f"{path} 不是 eval --json 寫的檔案")
    systems = [_system(score, path.parent) for score in result["systems"]]
    print(render(result, systems), end="")
    return 0
