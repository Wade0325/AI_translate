"""``python -m tools.eval`` 的指令：eval（對標準答案計分）、selftest（自我驗證）與 transcribe
（跑正式的轉錄路徑，產生要計分的轉錄結果）。

在 repo 根目錄執行，用法見同一個資料夾的 README.md。eval 與 selftest 離線計分，不呼叫任何 API、
不讀音檔；transcribe 讀音檔、用本機模型轉錄，見 transcribe.py。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from . import reference_set
from .custom_vocabulary import CustomVocabulary, load_custom_vocabulary
from .reference_set import Excerpt

# 計分的 mer 與 selftest 要 opencc、rapidfuzz、pypinyin（requirements-dev.txt），用到時才
# import：只裝了應用程式依賴的 venv 也能跑 transcribe
if TYPE_CHECKING:
    from . import mer

REPO_ROOT = Path(__file__).resolve().parents[2]
LAB_ENV = "AIT_LAB_DIR"


class UsageError(Exception):
    """參數指到不存在或不能用的檔案；訊息直接給人看。"""


def _git(*args: str, cwd: Path) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              encoding="utf-8", check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return done.stdout.strip()


def default_lab_dir(repo_root: Path = REPO_ROOT) -> Path:
    """研究區：環境變數 AIT_LAB_DIR，否則是主 checkout 旁邊的 ``<主 checkout 名稱>-lab``。

    主 checkout 是 ``git rev-parse --path-format=absolute --git-common-dir`` 的上一層，所以
    從 worktree 執行也找到同一個研究區；不在 git 裡時以這份程式所在的 repo 為準。
    """
    env = os.environ.get(LAB_ENV)
    if env:
        return Path(env)
    common = _git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=repo_root)
    main = Path(common).parent if common else repo_root
    return main.parent / f"{main.name}-lab"


def _tool_version() -> str | None:
    """這份工具的 commit；tools/eval 有沒 commit 的改動時加上 +dirty。"""
    commit = _git("rev-parse", "HEAD", cwd=REPO_ROOT)
    if commit is None:
        return None
    dirty = _git("status", "--porcelain", "--", "tools/eval", cwd=REPO_ROOT)
    return commit + ("+dirty" if dirty else "")


def _available(directory: Path, suffix: str) -> str:
    names = sorted(p.name.removesuffix(suffix) for p in directory.glob(f"*{suffix}"))
    if names:
        return f"\n{directory} 底下有：" + "、".join(names)
    return (f"\n{directory} 底下沒有任何 *{suffix}；用參數指定資料夾，"
            f"或用環境變數 {LAB_ENV} 指定研究區。")


def _resolve(names: Sequence[str], directory: Path, suffix: str, what: str) -> list[Path]:
    """存在的檔案照用；否則當成名稱，到資料夾裡找 ``<名稱><suffix>``。"""
    out = []
    for name in names:
        path = Path(name)
        if not path.is_file():
            path = directory / (name if name.endswith(suffix) else f"{name}{suffix}")
        if not path.is_file():
            raise UsageError(f"找不到{what} {name}：{path} 不存在。" + _available(directory, suffix))
        out.append(path)
    return out


def _refuse_writing_references(target: Path, protected_dirs: Sequence[Path],
                               option: str = "--json") -> None:
    resolved = target.resolve()
    for protected in {d.resolve() for d in protected_dirs}:
        if resolved == protected or protected in resolved.parents:
            raise UsageError(f"{option} 不能寫進標準答案的資料夾 {protected}：工具只讀取標準答案，不寫入。")


@dataclass
class _Scored:
    """一份轉錄結果在評測集上的分數。"""

    transcript: Path
    results: list[mer.Result]
    global_map: dict[str, str]
    cp_global: float

    def report(self) -> str:
        from . import mer

        return mer.format_report(self.results, self.transcript.name, self.global_map,
                                 self.cp_global)

    def to_dict(self) -> dict:
        return {
            "transcript": str(self.transcript),
            "per_excerpt": [r.to_dict() for r in self.results],
            "total_mer": round(sum(r.errors for r in self.results)
                               / max(1, sum(r.ref_len for r in self.results)), 4),
        }


def _score(excerpts: Sequence[Excerpt], transcript: Path, vocabulary: CustomVocabulary,
           bootstrap: int) -> _Scored:
    from . import mer

    results = [mer.evaluate(ex, reference_set.clip_transcript(transcript, ex.start, ex.end),
                            vocabulary, bootstrap=bootstrap)
               for ex in excerpts]
    global_map, cp_global = mer.global_mapping(results)
    return _Scored(transcript, results, global_map, cp_global)


def _paired_comparison(a: _Scored, b: _Scored, bootstrap: int) -> str:
    from . import mer

    lens = [n for r in a.results for n in r.line_ref_len]
    errors_a = [e for r in a.results for e in r.line_errors]
    errors_b = [e for r in b.results for e in r.line_errors]
    mean, lo, hi = mer.paired_delta_ci(errors_a, errors_b, lens, n=bootstrap)
    sig = "顯著" if (lo < 0 and hi < 0) or (lo > 0 and hi > 0) else "不顯著（區間跨 0）"
    return (f"成對比較（{b.transcript.name} − {a.transcript.name}）：負值代表後者較好\n"
            f"  ΔMER {mean*100:+.2f} pp   95% CI [{lo*100:+.2f}, {hi*100:+.2f}]   {sig}")


def cmd_eval(args) -> int:
    lab = default_lab_dir()
    lab_references = lab / "data" / "eval"
    reference_dir = Path(args.reference_dir) if args.reference_dir else lab_references
    vocabulary_dir = Path(args.vocabulary_dir) if args.vocabulary_dir else lab / "glossaries"

    paths = _resolve(args.reference, reference_dir, ".txt", "標準答案")
    if args.json:
        _refuse_writing_references(
            Path(args.json), [lab_references, reference_dir, *(p.parent for p in paths)])
    transcripts = [Path(t) for t in (args.transcript, args.vs) if t]
    for t in transcripts:
        if not t.is_file():
            raise UsageError(f"找不到轉錄結果：{t}")
    vpaths = _resolve(args.vocabulary or [], vocabulary_dir, ".json", "術語表")

    excerpts = [reference_set.read_reference(p, allow_draft=args.allow_draft) for p in paths]
    drafts = sum(e.draft_marks for e in excerpts)
    if drafts:
        print(f"⚠ 使用草稿標準答案（{drafts} 處未確認標記），數字只能當工具驗證，"
              f"不能當結論。\n")
    for t in transcripts:
        for warning in reference_set.transcript_warnings(t):
            print(f"⚠ {t.name}：{warning}")

    vocabulary = load_custom_vocabulary(*vpaths)
    scored = [_score(excerpts, t, vocabulary, args.bootstrap) for t in transcripts]
    print(("\n\n" + "=" * 70 + "\n\n").join(s.report() for s in scored))
    if len(scored) == 2:
        print("\n" + "=" * 70)
        print(_paired_comparison(*scored, bootstrap=args.bootstrap))

    if args.json:
        out = Path(args.json)
        payload = {
            "command": "eval",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "tool_version": _tool_version(),
            "reference": [str(p) for p in paths],
            "reference_draft_marks": drafts,
            "vocabulary": [p.name for p in vpaths],
            "bootstrap": args.bootstrap,
            "systems": [s.to_dict() for s in scored],
            "global_mapping": {"mapping": scored[0].global_map,
                               "cp_mer": round(scored[0].cp_global, 4)},
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已寫入：{out}")
    return 0


def cmd_selftest(_) -> int:
    from . import selftest

    return 0 if selftest.run() else 1


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m tools.eval",
        description="評測工具：用正式的轉錄路徑產生轉錄結果，再拿它和標準答案比對。")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("selftest", help="正規化、錯誤分類與同音判斷的自我驗證"
                   ).set_defaults(fn=cmd_selftest)

    p = sub.add_parser("eval", help="對標準答案計分（錯字率／說話者／錯誤預算）")
    p.add_argument("--reference", nargs="+", required=True, metavar="名稱或路徑",
                   help="標準答案；只給名稱時到 --reference-dir 找 <名稱>.txt（例如 demo_A.draft）")
    p.add_argument("--transcript", required=True, help="轉錄結果的 LRC")
    p.add_argument("--vs", help="另一份轉錄結果，和 --transcript 做成對比較")
    p.add_argument("--vocabulary", nargs="*", metavar="名稱或路徑",
                   help="術語表；只給名稱時到 --vocabulary-dir 找 <名稱>.json")
    p.add_argument("--reference-dir",
                   help=f"標準答案的資料夾（預設：研究區的 data/eval；研究區可用 {LAB_ENV} 指定）")
    p.add_argument("--vocabulary-dir", help="術語表的資料夾（預設：研究區的 glossaries）")
    p.add_argument("--bootstrap", type=int, default=1000, help="信賴區間的重抽樣次數")
    p.add_argument("--allow-draft", action="store_true",
                   help="允許標準答案仍有草稿標記（只用來驗證工具本身）")
    p.add_argument("--json", metavar="路徑",
                   help="另外把數字寫成 JSON；不能寫進標準答案的資料夾")
    p.set_defaults(fn=cmd_eval)

    # 在函式裡 import：transcribe.py 從這裡拿共用的函式
    from .transcribe import cmd_transcribe

    p = sub.add_parser("transcribe", help="跑正式的轉錄路徑，輸出轉錄結果（LRC）與 manifest（會用顯卡）")
    p.add_argument("--audio", required=True, help="要轉錄的音檔")
    p.add_argument("--provider", default="local",
                   help="供應商（預設 local）；要 API 金鑰的供應商會拒絕，音檔不離開這台電腦")
    p.add_argument("--model", help="模型（預設：供應商的預設模型）")
    p.add_argument("--language", required=True, help="音檔的語言，和轉錄頁送出的相同，例如 zh-TW")
    p.add_argument("--out", required=True, metavar="資料夾",
                   help="輸出資料夾：寫 <音檔名稱>.lrc 與 <音檔名稱>.manifest.json，已經有時拒絕；"
                        "不能是標準答案的資料夾")
    p.add_argument("--yes", action="store_true", help="不停下來確認已經停掉其他使用顯卡的工作")
    p.set_defaults(fn=cmd_transcribe)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.fn(args)
    except (UsageError, reference_set.ReferenceSetError) as e:
        print(e, file=sys.stderr)
        return 2
