"""``python -m tools.eval summary``：把評測整理成 PR 範本的「評測摘要」（#38），並照 ADR 0009 判定回歸（#264）。

讀 ``eval --json`` 寫的檔案（評測集的每個音檔一份），以及每份轉錄結果旁邊、``transcribe`` 寫的 manifest
（``<音檔名稱>.manifest.json``），印出 Markdown：每個音檔一張表（指令、commit、模型與語言、錯字率與
cpMER、ΔMER 與 95% CI、RTF 與峰值顯存、結尾核對），最後是回歸判定。

判定（docs/adr/0009、#15 的 Q2a、Q2b、Q3）：只算沒有草稿標記的標準答案，同一種語言的片段合起來
（錯誤數總和 ÷ token 總和），錯字率或 cpMER 比基準高就是回歸，否則通過。標準答案註明「cpMER 不計」
的片段只算錯字率。95% CI、RTF、峰值顯存與結尾核對只列出，不參與判定。語言看 manifest 的 ``request.language``，只看主要的語言代碼
（``zh-TW`` 與 ``zh-CN`` 都是中文）。

只輸出數字、雜湊、檔名與「cpMER 不計」的理由，不輸出錯誤範例或任何轉錄文字：評測集的原文不進 PR（#15 的 Q4）。
結尾核對只讀 LRC 每一行的時間戳。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import lrc
from .cli import UsageError

PASS = "通過"
REGRESSION = "回歸"
UNDECIDED = "無法判定"

LANGUAGE_NAMES = {"zh": "中文", "ja": "日文"}

# eval 的 JSON 裡，比率都取到小數第四位（mer.Result.to_dict）
_ROUNDING = 0.00005


@dataclass
class _System:
    """一份轉錄結果：eval 的分數、它的 manifest，以及 LRC 最後一行的開始時間。"""

    transcript: Path
    score: dict[str, Any]
    manifest: dict[str, Any] | None
    last_line: float | None


@dataclass
class _Eval:
    """一份 eval --json：評測集裡的一個音檔，和一份（只有轉錄結果）或兩份（基準與這個 PR）轉錄結果。"""

    result: dict[str, Any]
    systems: list[_System]

    @property
    def manifests(self) -> list[dict[str, Any]]:
        return [s.manifest for s in self.systems if s.manifest]

    @property
    def title(self) -> str:
        manifests = self.manifests
        audio = manifests[0].get("audio", {}) if manifests else {}
        return audio.get("file") or self.systems[0].transcript.name

    @property
    def references(self) -> list[str]:
        """標準答案的名稱（檔名去掉 .txt），順序和每份轉錄結果的 per_excerpt 相同。"""
        return [Path(p).name.removesuffix(".txt") for p in self.result.get("reference", [])]

    @property
    def audio_hashes(self) -> set[Any]:
        return {_get(m, "audio", "sha256") for m in self.manifests}

    @property
    def languages(self) -> set[str]:
        """manifest 寫的語言，只留主要的語言代碼（zh-TW → zh）。"""
        codes = (_get(m, "request", "language") for m in self.manifests)
        return {str(code).split("-")[0].lower() for code in codes if code}


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, rest = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{rest:02d}" if hours else f"{minutes}:{rest:02d}"


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def _cp_scored(excerpt: dict[str, Any]) -> bool:
    """這一段的 cpMER 算不算進判定：標準答案註明「cpMER 不計」時不算（舊的 JSON 沒有這一欄，照算）。"""
    return excerpt.get("cp_mer_scored", True) is not False


def _cp_cell(system: _System) -> str:
    excerpts = system.score.get("per_excerpt") or []
    if excerpts and not any(_cp_scored(e) for e in excerpts):
        return "不計"
    return _percent(system.score.get("cp_mer_global"))


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


def _read(path: Path) -> _Eval:
    result = _load(path, "eval 的 JSON")
    if result.get("command") != "eval" or not result.get("systems"):
        raise UsageError(f"{path} 不是 eval --json 寫的檔案")
    return _Eval(result, [_system(score, path.parent) for score in result["systems"]])


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


def render(run: _Eval) -> str:
    """一個音檔的評測摘要（Markdown）；只有數字、雜湊與檔名。"""
    result, systems, manifests = run.result, run.systems, run.manifests
    labels = ["轉錄結果"] if len(systems) == 1 else ["基準（--transcript）", "這個 PR（--vs）"]
    audio = manifests[0].get("audio", {}) if manifests else {}

    rows = [
        ("commit", _commit),
        ("模型與語言", _request),
        ("錯字率（MER）", lambda s: _percent(s.score.get("total_mer"))),
        ("cpMER（全域對應）", _cp_cell),
        ("RTF", _rtf),
        ("峰值顯存", _vram),
        ("結尾核對", _tail),
    ]
    out = [f"### 評測摘要：{run.title}", "",
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
    if len(run.audio_hashes) > 1:
        out.append("- ⚠ 兩邊轉錄的音檔不同（SHA-256 不一樣），比較不成立")
    references = run.references
    drafts = result.get("reference_draft_marks") or 0
    draft_note = f"，草稿標記 {drafts} 處：數字只能當工具驗證，不能當結論" if drafts else ""
    out.append(f"- 標準答案：{'、'.join(references) or '—'}{draft_note}")
    skipped = _cp_skipped(run)
    if skipped:
        out.append(f"- cpMER 不計（只算錯字率，ADR 0009）：{'；'.join(skipped)}")
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
    return "\n".join(out) + "\n"


@dataclass
class _Errors:
    """一份轉錄結果在幾段標準答案上合起來的錯誤數。

    錯字率的錯誤數是確切的（替換、刪除、插入的總和）。cpMER 在 eval 的 JSON 裡只有比率，取到小數
    第四位；它的分母和錯字率一樣是標準答案的 token 數（mer.evaluate），乘回去只能還原出一個範圍，
    誤差最多 0.00005 × token 數。一段少於 10000 個 token 時範圍只有一個整數，就是確切的錯誤數。
    """

    mer: int = 0
    cp_low: int = 0
    cp_high: int = 0

    def add(self, excerpt: dict[str, Any], *, cp: bool = True) -> None:
        self.mer += excerpt["subs"] + excerpt["dels"] + excerpt["ins"]
        if not cp:
            return
        tokens = max(excerpt["ref_len"], 1)  # mer.evaluate：沒有 token 時分母是 1
        cp = excerpt["cp_mer_global"]
        # 1e-9 吸收浮點數的誤差：還原出的範圍寧可寬一點，也不能漏掉真正的錯誤數
        self.cp_low += max(0, math.ceil((cp - _ROUNDING) * tokens - 1e-9))
        self.cp_high += math.floor((cp + _ROUNDING) * tokens + 1e-9)


def _rate(low: int, high: int, tokens: int) -> str:
    count = f"{low}" if low == high else f"{low}～{high}"
    return f"{_percent((low + high) / 2 / max(tokens, 1))}（{count} 個錯）"


@dataclass
class _Language:
    """一種語言：用到的標準答案、它們的 token 數，以及基準與這個 PR 合起來的錯誤數。"""

    code: str
    references: list[str] = field(default_factory=list)
    tokens: int = 0
    cp_tokens: int = 0  # 算 cpMER 的片段的 token 數（不含註明「cpMER 不計」的）
    base: _Errors = field(default_factory=_Errors)
    head: _Errors = field(default_factory=_Errors)

    @property
    def name(self) -> str:
        return LANGUAGE_NAMES.get(self.code, self.code)

    @property
    def verdict(self) -> str:
        """兩邊的分母相同（同一組標準答案），比錯誤數就是比錯字率與 cpMER。"""
        if self.head.mer > self.base.mer or self.head.cp_low > self.base.cp_high:
            return REGRESSION
        if self.head.cp_high <= self.base.cp_low:
            return PASS
        return UNDECIDED

    def row(self) -> str:
        base, head, tokens, cp_tokens = self.base, self.head, self.tokens, self.cp_tokens
        cp = (f"{_rate(base.cp_low, base.cp_high, cp_tokens)} → {_rate(head.cp_low, head.cp_high, cp_tokens)}"
              if cp_tokens else "不計")
        return (f"| {self.name} | {'、'.join(self.references)} | {tokens} "
                f"| {_rate(base.mer, base.mer, tokens)} → {_rate(head.mer, head.mer, tokens)} "
                f"| {cp} | {self.verdict} |")


def _cp_skipped(run: _Eval) -> list[str]:
    """標準答案註明「cpMER 不計」的片段與理由。"""
    skipped: dict[str, str] = {}
    for system in run.systems:
        for excerpt in system.score.get("per_excerpt") or []:
            if not _cp_scored(excerpt):
                skipped.setdefault(excerpt.get("name", "?"), excerpt.get("cp_mer_skip") or "")
    return [f"{name}（{reason}）" if reason else name for name, reason in skipped.items()]


def _excluded(run: _Eval) -> str | None:
    """這份 JSON 不能算進判定的原因；能算時回傳 None。"""
    if len(run.systems) != 2:
        return "只有一份轉錄結果，沒有基準可比"
    drafts = run.result.get("reference_draft_marks") or 0
    if drafts:
        return f"標準答案還有 {drafts} 處草稿標記"
    if len(run.audio_hashes) > 1:
        return "兩邊轉錄的音檔不同"
    if not run.languages:
        return "找不到 manifest，不知道是哪種語言"
    if len(run.languages) > 1:
        return "兩邊的語言不同"
    return None


def _overall(languages: list[_Language]) -> str:
    if not languages:
        return f"{UNDECIDED}：沒有已確認的標準答案可以和基準比（有草稿標記的不算）"
    by_verdict: dict[str, list[str]] = {}
    for language in languages:
        by_verdict.setdefault(language.verdict, []).append(language.name)
    if REGRESSION in by_verdict:
        return (f"{REGRESSION}（{'、'.join(by_verdict[REGRESSION])}）：代理不合併，"
                f"等使用者明確接受並在 PR 上記下理由")
    if UNDECIDED in by_verdict:
        return (f"{UNDECIDED}（{'、'.join(by_verdict[UNDECIDED])}）：JSON 裡的 cpMER 只到小數第四位，"
                f"分不出有沒有比基準高；代理不合併，交給使用者")
    return f"{PASS}（{'、'.join(by_verdict[PASS])}）"


def render_verdict(runs: list[_Eval]) -> str:
    """所有音檔合起來，每種語言一個判定（Markdown）。"""
    languages: dict[str, _Language] = {}
    excluded: list[str] = []
    for run in runs:
        reason = _excluded(run)
        if reason:
            excluded.append(f"{run.title}（{reason}）")
            continue
        (code,) = run.languages
        language = languages.setdefault(code, _Language(code))
        language.references += run.references
        base, head = (s.score["per_excerpt"] for s in run.systems)
        for b, h in zip(base, head, strict=True):
            cp = _cp_scored(b) and _cp_scored(h)
            language.tokens += b["ref_len"]
            language.cp_tokens += b["ref_len"] if cp else 0
            language.base.add(b, cp=cp)
            language.head.add(h, cp=cp)

    out = ["### 回歸判定", "",
           "只算沒有草稿標記的標準答案。同一種語言的片段合起來，錯字率或 cpMER 比基準高就是回歸"
           "（docs/adr/0009）；註明「cpMER 不計」的片段只算錯字率；95% CI 只列出，不參與判定。", ""]
    if languages:
        out += ["| 語言 | 標準答案 | token | 錯字率：基準 → 這個 PR | cpMER：基準 → 這個 PR | 判定 |",
                "|---|---|---|---|---|---|"]
        out += [language.row() for language in languages.values()]
        out.append("")
    if excluded:
        out.append(f"- 沒算進判定：{'；'.join(excluded)}")
    out.append(f"- 判定：{_overall(list(languages.values()))}")
    return "\n".join(out) + "\n"


def cmd_summary(args) -> int:
    runs = [_read(Path(p)) for p in args.eval_json]
    print("\n".join(render(run) for run in runs) + "\n" + render_verdict(runs), end="")
    return 0
