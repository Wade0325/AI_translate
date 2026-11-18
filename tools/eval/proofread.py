"""``python -m tools.eval proofread``：逐句校對，起草標準答案（ADR 0009）。

沒有底稿可以三方對照、或使用者要每一句都聽過時用（``three-way`` 只列不一致的地方）：

* ``draft``：把一個模型的轉錄結果（預設模型 moss-align）逐行寫成標準答案的草稿，連同一個本機的
  校對頁（HTML）。校對頁一句一列：播放這一句、改說話者與文字、插入兩個模型都漏掉的句子、刪掉多出來
  的句子；另一個模型（第二假設）在同一段時間的寫法列在下面當參考。聽過、改好的句子打勾，下載的
  標準答案裡沒打勾的句子帶草稿標記 ``A?:``，評測不會拿它判定（``reference_set``）。
* ``finalize``：讀校對頁下載的標準答案，確認沒有草稿標記、讀得進來，記下確認者與日期，寫成
  ``<名稱>.txt``；確認後自己複製到研究區的 ``data/eval``。

說話者代號：轉錄結果的 ``S0``、``S1``… 依第一次出現的順序換成 ``A``、``B``…；沒有說話者標記的行也算
一位。第二假設的寫法依時間對到草稿的句子：開始時間落在這一句與下一句的開始時間之間的行，都列在這一句
底下；比計分的正規化（:func:`.mer.tokenize`）不同時，校對頁會標出來。

終端機只印數量；轉錄結果的文字只寫進 ``--out`` 的 JSON、草稿與校對頁，不寫進標準答案的資料夾
（``data/eval``）。``draft`` 只讀 WAV 的檔頭取得長度，不解碼音訊。
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
import string
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import lrc, mer, reference_set
from .cli import UsageError, _refuse_writing_references, _tool_version, default_lab_dir
from .reference_set import HEADER_RE, UTT_RE
from .three_way import _label, _sha256, audio_src

PAGE_TEMPLATE = Path(__file__).with_name("proofread_page.html")
NAME_RE = re.compile(r"^[\w.-]+$")
RANGE_RE = re.compile(r"^\s*(?P<start>\d+:\d+(?:\.\d+)?)\s*-\s*(?P<end>\d+:\d+(?:\.\d+)?)\s*$")
CONFIRMED_RE = re.compile(r"^#\s*確認\s*[:：]")
SECONDS_PER_CHAR_CAP = 0.4   # 估一行多長時每字最多算幾秒（和 three_way 定位播放時相同）
MIN_SPAN = 1.0


@dataclass
class Row:
    """草稿的一句：第一個模型的一行，連同第二假設在同一段時間的寫法。"""

    id: int
    seconds: float
    speaker: str          # 標準答案的代號（A、B…）
    text: str
    alt: str | None       # 第二假設在這一段時間的寫法；沒給第二假設時是 None
    alt_differs: bool     # 計分的正規化之後和 text 不同

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "seconds": round(self.seconds, 2), "speaker": self.speaker,
                "text": self.text, "alt": self.alt, "alt_differs": self.alt_differs}


@dataclass
class Draft:
    name: str
    start: float
    end: float
    private: bool
    rows: list[Row]
    speakers: dict[str, str]   # 標準答案的代號 → 轉錄結果的標記（沒有標記時是「無標記」）


def clock(seconds: float) -> str:
    """秒換成 mm:ss.xx（分鐘可以超過 59，和表頭、LRC 相同）；捨去到百分之一秒。"""
    centis = int(round(seconds * 1000)) // 10
    minutes, centis = divmod(centis, 6000)
    return f"{minutes:02d}:{centis // 100:02d}.{centis % 100:02d}"


def parse_range(text: str) -> tuple[float, float]:
    m = RANGE_RE.match(text)
    if not m:
        raise UsageError(f"--range 要寫成 mm:ss.xx-mm:ss.xx，例如 00:00.00-30:36.47：{text!r}")
    start, end = (reference_set._ts_to_sec(m.group(k)) for k in ("start", "end"))
    if end <= start:
        raise UsageError(f"--range 的結束要比開始晚：{text!r}")
    return start, end


def wav_seconds(path: Path) -> float:
    """WAV 的長度（秒），只讀檔頭；捨去到百分之一秒，表頭的範圍不會超過音檔。"""
    try:
        with wave.open(str(path), "rb") as w:
            frames, rate = w.getnframes(), w.getframerate()
    except (wave.Error, EOFError) as e:
        raise UsageError(f"讀不了 {path.name} 的 WAV 檔頭（{e}）：用 --range 直接給範圍。") from e
    return int(frames * 100 // rate) / 100


def speaker_codes(labels: Sequence[str | None]) -> dict[str | None, str]:
    """轉錄結果的說話者標記依第一次出現的順序換成 A、B…（超過 26 位後是 S27、S28…）。"""
    codes: dict[str | None, str] = {}
    for label in labels:
        if label not in codes:
            n = len(codes)
            codes[label] = string.ascii_uppercase[n] if n < 26 else f"S{n + 1}"
    return codes


def _spans(lines: Sequence[lrc.Line], end: float) -> list[tuple[float, float]]:
    """LRC 只有開始時間：每一行算到下一行開始，但最多照字數估（每字 0.4 秒、至少 1 秒），最後一行也是；
    不然後面接著一長段沒有字的地方時，一行會被算得很長。"""
    out = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1].seconds if i + 1 < len(lines) else end
        chars = len("".join(line.text.split()))
        out.append((line.seconds, max(line.seconds, min(nxt, line.seconds + max(MIN_SPAN, chars * SECONDS_PER_CHAR_CAP)))))
    return out


def _alt_texts(main: Sequence[lrc.Line], second: Sequence[lrc.Line], end: float) -> list[str]:
    """第二假設的每一行歸到時間重疊最多的草稿句子。兩個模型切行的地方不同、開始時間也會差一點
    （例如第二假設早 0.1 秒開始），只看開始時間落在哪一句會歸錯；和每一句都不重疊（落在兩句之間的
    空檔、比第一句早或比最後一句晚）時歸最近的一句。"""
    starts = [line.seconds for line in main]
    rows = _spans(main, end)
    out: list[list[str]] = [[] for _ in main]
    for (t0, t1), line in zip(_spans(second, end), second, strict=True):
        first = max(0, bisect.bisect_right(starts, t0) - 1)
        best, best_overlap = None, 0.0
        for i in range(first, len(rows)):
            s0, s1 = rows[i]
            if s0 >= t1:
                break
            overlap = min(s1, t1) - max(s0, t0)
            if overlap > best_overlap:
                best, best_overlap = i, overlap
        if best is None:
            near = [i for i in (first, first + 1) if i < len(rows)]
            best = min(near, key=lambda i: max(rows[i][0] - t1, t0 - rows[i][1], 0.0))
        out[best].append(line.text.strip())
    return [" ".join(t for t in texts if t) for texts in out]


def build_draft(name: str, start: float, end: float, main: lrc.LrcText,
                second: lrc.LrcText | None = None, *, private: bool = False) -> Draft:
    if not NAME_RE.match(name):
        raise UsageError(f"--name 只能用英數字、底線、句點與連字號（標準答案表頭的規則）：{name!r}")
    lines = sorted((ln for ln in main.lines if start <= ln.seconds < end), key=lambda ln: ln.seconds)
    if not lines:
        raise UsageError(f"轉錄結果在 {clock(start)}-{clock(end)} 之間沒有任何一行。")
    codes = speaker_codes([ln.speaker for ln in lines])
    alts: list[str] | None = None
    if second is not None:
        others = sorted((ln for ln in second.lines if start <= ln.seconds < end),
                        key=lambda ln: ln.seconds)
        alts = _alt_texts(lines, others, end)
    rows = []
    for i, line in enumerate(lines):
        text = " ".join(line.text.split())
        alt = None if alts is None else alts[i]
        differs = alt is not None and mer.tokenize(alt) != mer.tokenize(text)
        rows.append(Row(id=i, seconds=line.seconds, speaker=codes[line.speaker], text=text,
                        alt=alt, alt_differs=differs))
    speakers = {code: (label or "無標記") for label, code in codes.items()}
    return Draft(name=name, start=start, end=end, private=private, rows=rows, speakers=speakers)


def draft_text(draft: Draft, systems: Sequence[dict[str, Any]]) -> str:
    """草稿本身也是一份標準答案：每一句都帶草稿標記，評測不會拿它判定。不想用校對頁時，可以直接
    用文字編輯器改這一份，改好的句子刪掉代號後面的「?」。"""
    out = [f"# {draft.name}  {clock(draft.start)}-{clock(draft.end)}"]
    if draft.private:
        out.append("# 不公開")
    out.append(f"# 逐句校對：{_provenance(systems)}；共 {len(draft.rows)} 句，還沒有確認")
    out.append("")
    out.extend(f"[{clock(row.seconds)}] {row.speaker}?: {row.text}" for row in draft.rows)
    return "\n".join(out) + "\n"


def _provenance(systems: Sequence[dict[str, Any]]) -> str:
    roles = ["草稿", "對照"]
    return "、".join(f"{roles[i]} {s['label']}（SHA-256 {s['sha256'][:12]}）" for i, s in enumerate(systems))


def _digest(draft: Draft, systems: Sequence[dict[str, Any]]) -> str:
    """校對頁把進度存在瀏覽器時用的指紋：換了轉錄結果，就不會讀到另一份草稿的進度。"""
    blob = json.dumps({"name": draft.name, "rows": [r.to_dict() for r in draft.rows],
                       "systems": [s["sha256"] for s in systems]}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def to_payload(draft: Draft, systems: Sequence[dict[str, Any]], audio: Path | None,
               out_dir: Path) -> dict[str, Any]:
    return {
        "command": "proofread draft",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "tool_version": _tool_version(),
        "name": draft.name,
        "window": [draft.start, draft.end],
        "header": f"# {draft.name}  {clock(draft.start)}-{clock(draft.end)}",
        "private": draft.private,
        "digest": _digest(draft, systems),
        "systems": list(systems),
        "provenance": _provenance(systems),
        "audio": None if audio is None else {"path": str(audio), "src": audio_src(audio, out_dir)},
        "speakers": draft.speakers,
        "rows": [r.to_dict() for r in draft.rows],
    }


def render_page(payload: dict[str, Any]) -> str:
    """把資料嵌進校對頁。``</`` 換成 ``<\\/``，文字裡有 ``</script>`` 也不會提早結束。"""
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    template = PAGE_TEMPLATE.read_text(encoding="utf-8")
    title = payload["name"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return template.replace("__TITLE__", title).replace("__DATA__", data)


def _system(path: Path) -> dict[str, Any]:
    """一份轉錄結果：模型名稱（讀 transcribe 寫在旁邊的 manifest，沒有時用資料夾名稱）、路徑與 SHA-256。"""
    return {"label": _label(path), "path": str(path), "sha256": _sha256(path)}


def cmd_draft(args) -> int:
    lab_references = default_lab_dir() / "data" / "eval"
    out_dir = Path(args.out)
    _refuse_writing_references(out_dir, [lab_references], option="--out")
    transcript = Path(args.transcript)
    second = Path(args.second_hypothesis) if args.second_hypothesis else None
    for p in (transcript, second):
        if p is not None and not p.is_file():
            raise UsageError(f"找不到 {p}")
    audio = Path(args.audio) if args.audio else None
    if audio is not None and not audio.is_file():
        raise UsageError(f"找不到音檔：{audio}")
    if args.range:
        start, end = parse_range(args.range)
    elif audio is not None and audio.suffix.lower() == ".wav":
        start, end = 0.0, wav_seconds(audio)
    else:
        raise UsageError("沒有 WAV 音檔可以讀長度：用 --range 給標準答案的時間範圍（mm:ss.xx-mm:ss.xx）。")

    paths = {suffix: out_dir / f"{args.name}{suffix}"
             for suffix in (".proofread.json", ".proofread.html", ".draft.txt")}
    existing = [p.name for p in paths.values() if p.exists()]
    if existing:
        raise UsageError(f"{out_dir} 已經有 {'、'.join(existing)}：不覆寫，換一個 --out 或先移走它們。")

    draft = build_draft(args.name, start, end, lrc.read(transcript),
                        None if second is None else lrc.read(second), private=args.private)
    systems = [_system(transcript)] + ([] if second is None else [_system(second)])
    payload = to_payload(draft, systems, audio, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths[".proofread.json"].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    paths[".proofread.html"].write_text(render_page(payload), encoding="utf-8")
    paths[".draft.txt"].write_text(draft_text(draft, systems), encoding="utf-8", newline="")

    differs = sum(r.alt_differs for r in draft.rows)
    print(f"逐句校對：{draft.name}（{clock(draft.start)}-{clock(draft.end)}，{len(draft.rows)} 句、"
          f"{len(draft.speakers)} 位說話者）")
    if second is not None:
        print(f"和 {systems[1]['label']} 寫法不同的句子：{differs}")
    print(f"\n校對頁：{paths['.proofread.html']}\n草稿：{paths['.draft.txt']}")
    return 0


# ------------------------------------------------------------------ 確認
def finalize(text: str, path_name: str, confirmed_by: str, on: date | None = None) -> str:
    """在校對完的標準答案記下確認者與日期，插在第一句的前面。"""
    if not confirmed_by.strip():
        raise UsageError("--confirmed-by 不能是空的。")
    lines = text.splitlines()
    if any(CONFIRMED_RE.match(line.strip()) for line in lines):
        raise UsageError(f"{path_name} 已經有「# 確認」那一行：不重複確認。")
    first = next((i for i, line in enumerate(lines)
                  if line.strip() and not line.strip().startswith("#") and UTT_RE.match(line.strip())),
                 None)
    if first is None:
        raise UsageError(f"{path_name} 沒有任何一句。")
    insert_at = first
    while insert_at > 0 and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines[insert_at:insert_at] = [f"# 確認：{confirmed_by.strip()}，{(on or date.today()).isoformat()}"]
    return "\n".join(lines) + "\n"


def cmd_finalize(args) -> int:
    lab_references = default_lab_dir() / "data" / "eval"
    out_dir = Path(args.out)
    _refuse_writing_references(out_dir, [lab_references], option="--out")
    src = Path(args.draft)
    if not src.is_file():
        raise UsageError(f"找不到 {src}")
    # 照評測讀標準答案的規則讀一次：還有草稿標記、表頭或某一行讀不進來時，訊息說明哪裡要改
    excerpt = reference_set.read_reference(src)
    text = src.read_text(encoding="utf-8")
    if not any(HEADER_RE.match(line.strip()) for line in text.splitlines()):
        raise UsageError(f"{src.name} 缺少表頭。")
    target = out_dir / f"{excerpt.name}.txt"
    if target.exists():
        raise UsageError(f"{target} 已經存在：不覆寫，換一個 --out 或先移走它。")
    out_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(finalize(text, src.name, args.confirmed_by), encoding="utf-8", newline="")
    print(f"已確認：{excerpt.name}（{len(excerpt.utterances)} 句）")
    print(f"標準答案：{target}")
    print("複製到研究區的 data/eval 之後，評測就會拿它判定。")
    return 0
