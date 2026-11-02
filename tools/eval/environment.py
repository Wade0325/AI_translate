"""比對基準與這個 PR 的轉錄環境（#276）。

同一台電腦、同一套環境重跑本機轉錄，輸出逐位元組相同（#84），所以環境相同時，錯字率的差異才是改動
造成的；換了顯卡、驅動、套件版本或模型權重，舊的基準就不能用（docs/adr/0009）。``summary`` 用這裡比對
兩邊的 manifest（``transcribe`` 寫的，環境由 ``backend/app/services/environment_manifest.py`` 記錄），
有一項不能直接比就不下回歸判定，提醒先重建基準。

逐項比對：模型（供應商與模型）、顯卡（名稱與顯存）、驅動、套件版本、模型權重的 revision 與設定。

- 評測集的每個音檔各有一份 manifest，同一邊的每一份也要相同：基準分兩天跑、中間更新了驅動，一樣不能比。
- 沒有記錄或讀不到的項目（例如舊的 manifest 沒有驅動）當成不能比：確認不了相同，就不下判定。
- commit 不比相同：基準是 main 的結果，PR 是自己的 commit。改成檢查兩邊各只有一個 commit、都沒有沒
  commit 的改動，而且基準的 commit 在這個 PR 的歷史裡；PR 落後 main 時，兩邊的差異就不只這個 PR 的改動。
- 語言不比：評測集本來就有中文也有日文的音檔，同一個音檔兩邊的語言不同由 summary 另外排除。
- ``CUDA_VISIBLE_DEVICES`` 不比：它選的是哪一張卡，那張卡的名稱與顯存已經比了。

只輸出版本、名稱、雜湊與設定的數值，可以貼進 PR；從本機檔案安裝的套件只寫檔名，不寫路徑（路徑常帶著
帳號名稱）。
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cli import REPO_ROOT

ENVIRONMENT_REMEDY = ("先在目前的環境用 main 重建基準，再重跑評測。差異如果正是這個 PR 的改動（例如升級套件、"
                      "換模型權重的 revision 或改設定的預設值），重建基準也消不掉，交給使用者決定")
"""環境不同時該怎麼做；commit 的問題各有自己的做法（:attr:`Item.remedy`）。"""

_COMMIT = re.compile(r"[0-9a-f]{7,64}")

IsAncestor = Callable[[str, str], bool | None]


@dataclass(frozen=True)
class _Value:
    """一份 manifest 裡的一項：``key`` 拿來比，``text`` 給人看。``key`` 是 None 時確認不了（沒有記錄或讀不到）。"""

    key: str | None
    text: str


_UNRECORDED = _Value(None, "沒有記錄")
_ABSENT = _Value("\0absent", "沒有")
"""manifest 記了這一類（例如設定），但沒有這一項：多半是一邊的程式新增或拿掉了它。"""


@dataclass(frozen=True)
class Item:
    """環境比對表的一列。

    Attributes:
        result: 比對欄的文字：相同、不同，或不能比的原因。
        ok: 這一項可以直接比。
        remedy: 不能比時該怎麼做；環境的項目共用 :data:`ENVIRONMENT_REMEDY`，這裡是 None。
    """

    name: str
    base: str
    head: str
    result: str
    ok: bool
    remedy: str | None = None


@dataclass(frozen=True)
class Comparison:
    items: list[Item]

    @property
    def problems(self) -> list[Item]:
        return [item for item in self.items if not item.ok]

    @property
    def ok(self) -> bool:
        return not self.problems


def compare(base: Sequence[dict[str, Any]], head: Sequence[dict[str, Any]], *,
            is_ancestor: IsAncestor | None = None) -> Comparison:
    """比對基準的 manifest（``base``）與這個 PR 的（``head``），評測集的每個音檔一份，兩邊都至少一份。

    ``is_ancestor(基準的 commit, 這個 PR 的 commit)`` 回答基準在不在這個 PR 的歷史裡，預設問 git
    （:func:`git_is_ancestor`）。
    """
    if not base or not head:
        raise ValueError("兩邊都要至少一份 manifest")
    items = [_commit(base, head, is_ancestor or git_is_ancestor)]
    base_leaves = [dict(_leaves(m)) for m in base]
    head_leaves = [dict(_leaves(m)) for m in head]
    names = list(dict.fromkeys(name for leaves in (*base_leaves, *head_leaves) for name in leaves))
    for name in names:
        items.append(_item(name, [leaves.get(name, _ABSENT) for leaves in base_leaves],
                           [leaves.get(name, _ABSENT) for leaves in head_leaves]))
    return Comparison(items)


def git_is_ancestor(base: str, head: str, repo: Path = REPO_ROOT) -> bool | None:
    """``base`` 在不在 ``head`` 的歷史裡（同一個 commit 也算）；不像 commit、git 找不到其中一個 commit
    或執行不了時是 None。"""
    if not (_COMMIT.fullmatch(base) and _COMMIT.fullmatch(head)):
        return None
    try:
        done = subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=repo,
                              capture_output=True, check=False)
    except OSError:
        return None
    return {0: True, 1: False}.get(done.returncode)


def render(comparison: Comparison) -> str:
    """環境比對的 Markdown：每一項一列，最後是不能比的項目該怎麼做。"""
    out = ["### 環境比對", "",
           "基準與這個 PR 要在同一台電腦、同一套環境轉錄，錯字率的差異才是改動造成的（docs/adr/0009）；"
           "有一項不能比就不下回歸判定。commit 不比相同，只確認基準在這個 PR 的歷史裡。", "",
           "| 項目 | 基準 | 這個 PR | 比對 |", "|---|---|---|---|"]
    out += [f"| {_cell(i.name)} | {_cell(i.base)} | {_cell(i.head)} | {i.result} |"
            for i in comparison.items]
    out.append("")
    environment = [item.name for item in comparison.problems if item.remedy is None]
    if environment:
        out.append(f"- ⚠ 環境不同（{'、'.join(environment)}）：{ENVIRONMENT_REMEDY}。")
    out += [f"- ⚠ {item.name}：{item.remedy}。" for item in comparison.problems if item.remedy]
    if comparison.ok:
        out.append("- 環境相同，可以直接和基準比。")
    return "\n".join(out) + "\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _item(name: str, base: list[_Value], head: list[_Value]) -> Item:
    base_text, head_text = _texts(base), _texts(head)
    unknown = next((v.text for v in (*base, *head) if v.key is None), None)
    if unknown:
        result = f"{unknown}，確認不了相同"
    elif len({v.key for v in base}) > 1:
        result = "基準的音檔之間就不同"
    elif len({v.key for v in head}) > 1:
        result = "這個 PR 的音檔之間就不同"
    elif base[0].key != head[0].key:
        result = "不同"
    else:
        return Item(name, base_text, "同左", "相同", ok=True)
    return Item(name, base_text, head_text, f"**{result}**", ok=False)


def _texts(values: list[_Value]) -> str:
    return "；".join(dict.fromkeys(v.text for v in values))


def _commit(base: Sequence[dict[str, Any]], head: Sequence[dict[str, Any]],
            is_ancestor: IsAncestor) -> Item:
    base_codes = list(dict.fromkeys(_code(m) for m in base))
    head_codes = list(dict.fromkeys(_code(m) for m in head))
    base_text = "；".join(_commit_text(*code) for code in base_codes)
    head_text = "；".join(_commit_text(*code) for code in head_codes)

    def cannot(result: str, remedy: str) -> Item:
        return Item("commit", base_text, head_text, f"**{result}**", ok=False, remedy=remedy)

    if any(commit is None or dirty is None for commit, dirty in (*base_codes, *head_codes)):
        return cannot("沒有記錄", "確認不了基準是不是 main 的結果、在不在這個 PR 的歷史裡："
                                  "用 python -m tools.eval transcribe 重新轉錄")
    if len(base_codes) > 1:
        return cannot("基準來自不只一個 commit", "基準要整份用 main 的同一個 commit 轉錄：重建基準")
    if len(head_codes) > 1:
        return cannot("這個 PR 來自不只一個 commit", "這個 PR 的每個音檔要用同一個 commit 轉錄：用最新的 commit 全部重跑")
    (base_commit, base_dirty), (head_commit, head_dirty) = base_codes[0], head_codes[0]
    if base_dirty:
        return cannot("基準有沒 commit 的改動", "基準要是 main 的結果：在沒有改動的 main 上重建基準")
    if head_dirty:
        return cannot("這個 PR 有沒 commit 的改動", "數字要對得上這個 PR 的 commit：commit 之後重跑這個 PR 的轉錄")
    assert base_commit is not None and head_commit is not None
    if base_commit == head_commit:
        return Item("commit", base_text, "同左", "同一個 commit", ok=True)
    ancestor = is_ancestor(base_commit, head_commit)
    if ancestor is None:
        return cannot("確認不了", "git 找不到這兩個 commit，確認不了基準在這個 PR 的歷史裡："
                                  "在轉錄用的 repo 執行 summary，或先 git fetch")
    if not ancestor:
        return cannot("基準不在這個 PR 的歷史裡", "這個 PR 落後 main 時，先合併 main 再重跑這個 PR 的轉錄；"
                                              "基準不是 main 的結果時，重建基準")
    return Item("commit", base_text, head_text, "基準在這個 PR 的歷史裡", ok=True)


def _code(manifest: dict[str, Any]) -> tuple[str | None, bool | None]:
    code = manifest.get("code")
    if not isinstance(code, dict):
        return None, None
    commit, dirty = code.get("commit"), code.get("dirty")
    return (str(commit) if commit else None), (dirty if isinstance(dirty, bool) else None)


def _commit_text(commit: str | None, dirty: bool | None) -> str:
    if commit is None:
        return "沒有記錄"
    return f"`{commit[:12]}`" + ("（有沒 commit 的改動）" if dirty else "")


def _leaves(manifest: dict[str, Any]) -> Iterator[tuple[str, _Value]]:
    """一份 manifest 裡要比的每一項（名稱，值），照表格的順序。"""
    request = manifest.get("request")
    if isinstance(request, dict) and request.get("provider") and request.get("model"):
        provider, model = str(request["provider"]), str(request["model"])
        yield "模型", _Value(_key([provider, model]), f"{provider}／{model}")
    else:
        yield "模型", _UNRECORDED

    environment = manifest.get("environment")
    environment = environment if isinstance(environment, dict) else {}
    gpu = environment.get("gpu", _UNRECORDED)
    if gpu is None:
        yield "顯卡", _Value("none", "沒有顯卡")
        yield "驅動", _Value("none", "沒有顯卡")
    elif isinstance(gpu, dict) and gpu.get("name"):
        card = {"name": gpu["name"], "vram_gb": gpu.get("vram_gb")}
        yield "顯卡", _Value(_key(card), f"{gpu['name']}（{gpu.get('vram_gb')} GB）")
        if "driver" not in gpu:
            yield "驅動", _UNRECORDED
        elif not gpu["driver"]:
            yield "驅動", _Value(None, "讀不到")
        else:
            yield "驅動", _Value(_key(gpu["driver"]), str(gpu["driver"]))
    else:
        yield "顯卡", _UNRECORDED
        yield "驅動", _UNRECORDED

    yield from _category(environment, "packages", "套件", _package)
    yield from _category(environment, "model_revisions", "模型權重",
                         lambda revision: _Value(_key(revision), f"`{str(revision)[:12]}`"))
    yield from _category(environment, "settings", "設定",
                         lambda value: _Value(_key(value), json.dumps(value, ensure_ascii=False)))


def _category(environment: dict[str, Any], field: str, label: str,
              value: Callable[[Any], _Value]) -> Iterator[tuple[str, _Value]]:
    """一類有好幾項的環境（套件、模型權重、設定）：每一項一列；這份 manifest 沒記這一類時只給一列「沒有記錄」。"""
    entries = environment.get(field)
    if not isinstance(entries, dict):
        yield label, _UNRECORDED
        return
    for name, entry in entries.items():
        yield f"{label}：{name}", value(entry)


def _package(entry: Any) -> _Value:
    if not isinstance(entry, dict):
        return _UNRECORDED
    version, source = entry.get("version"), entry.get("source")
    text = str(version) if version else "沒有安裝"
    if source:
        # 從本機檔案安裝時只寫檔名：路徑常帶著帳號名稱，摘要要貼進 PR
        shown = str(source).rstrip("/").rsplit("/", 1)[-1] if str(source).startswith("file:") else source
        text += f"（{shown}）"
    return _Value(_key({"version": version, "source": source}), text)


def _key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
