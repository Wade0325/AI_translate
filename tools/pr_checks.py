"""PR 的兩項 CI 檢查（#38）：內文有沒有「使用者看得到的變更」，以及依改動的路徑在 PR 上留提醒。

由 .github/workflows/ci.yml 的 pr-body job 與 pr-reminders.yml 呼叫；判斷寫在這裡，才能用 pytest 測。
只用標準函式庫與 runner 上的 ``gh``，不必安裝依賴。

- ``body``：從 GitHub API 讀 PR 現在的內文（不讀觸發事件裡的內文：重新執行時要讀到補上之後的版本），
  找「使用者看得到的變更」這一段。沒有這一段，或只剩範本的註解，就失敗。
- ``paths``：列出 PR 改動的檔案（含改名前的舊路徑），對照單向門清單與 ML 依賴，在 PR 上留一則留言，
  之後每次 push 改同一則。單向門清單直接讀 docs/agents/merging.md 第 4 步，那裡是唯一來源。
  只是提醒，不擋合併。從 fork 開的 PR 拿不到寫入權限，改寫在 job 的摘要。
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MERGING = ROOT / "docs" / "agents" / "merging.md"

USER_VISIBLE = "使用者看得到的變更"
# 留言開頭的隱藏標記：找出上一次留的那一則來改，不另外新增
MARKER = "<!-- ci:pr-paths -->"
# docs/agents/merging.md 第 4 步列出單向門的那一句，從這裡讀到句號
ONE_WAY_DOOR_LEAD = "動到下列路徑的 PR 是單向門"
# CI 不安裝 ML 依賴，動到它們要在本機重建 Docker 確認（merging.md 的例外）
ML_PATHS = ("backend/requirements-ml.txt", "backend/Dockerfile")

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
# 「**使用者看得到的變更**：…」這種粗體開頭的段落（範本上線前的寫法）
_BOLD_LABEL = re.compile(r"^\*\*(.+?)\*\*\s*[:：]?\s*(.*)$")


def user_visible_section(body: str) -> str | None:
    """「使用者看得到的變更」這一段的內容（去掉 HTML 註解與前後空白）；沒有這一段時是 None。

    認兩種寫法：Markdown 標題（內容到下一個同級或更高的標題），以及行首的粗體標籤
    （內容是同一行冒號之後，加上之後到下一個粗體標籤或標題之前的行）。
    """
    lines = _COMMENT.sub("", body.replace("\r\n", "\n")).split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        heading = _HEADING.match(stripped)
        if heading and heading.group(2).strip("* ") == USER_VISIBLE:
            level = len(heading.group(1))
            content = []
            for following in lines[i + 1:]:
                h = _HEADING.match(following.strip())
                if h and len(h.group(1)) <= level:
                    break
                content.append(following)
            return "\n".join(content).strip()
        bold = _BOLD_LABEL.match(stripped)
        if bold and bold.group(1).strip() == USER_VISIBLE:
            content = [bold.group(2)]
            for following in lines[i + 1:]:
                s = following.strip()
                if _HEADING.match(s) or _BOLD_LABEL.match(s):
                    break
                content.append(following)
            return "\n".join(content).strip()
    return None


def body_problem(body: str | None) -> str | None:
    """內文的問題（給人看的訊息）；沒有問題時是 None。"""
    section = user_visible_section(body or "")
    if section is None:
        return (f"PR 內文沒有「{USER_VISIBLE}」這一段。照 .github/pull_request_template.md 補上"
                f"「## {USER_VISIBLE}」；沒有就寫「無」。")
    if not section:
        return f"PR 內文的「{USER_VISIBLE}」是空的：寫出使用者看得到的變更，沒有就寫「無」。"
    return None


def one_way_door_patterns(merging_md: str) -> list[str]:
    """merging.md 第 4 步列出的單向門路徑（反引號裡的字），照原文的順序。

    以 ``/`` 結尾的是資料夾，含 ``*`` 的是萬用字元，其他是完整路徑；都從 repo 根目錄算。
    """
    start = merging_md.find(ONE_WAY_DOOR_LEAD)
    if start < 0:
        raise ValueError(f"docs/agents/merging.md 找不到「{ONE_WAY_DOOR_LEAD}」：單向門清單搬家了，"
                         f"跟著改 tools/pr_checks.py 的 ONE_WAY_DOOR_LEAD")
    end = merging_md.find("。", start)
    patterns = re.findall(r"`([^`]+)`", merging_md[start:end if end >= 0 else None])
    if not patterns:
        raise ValueError("docs/agents/merging.md 的單向門清單是空的")
    return patterns


def matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if "*" in pattern:
        return fnmatch.fnmatchcase(path, pattern)
    return path == pattern


@dataclass(frozen=True)
class Reminder:
    one_way_door: tuple[str, ...]
    ml: tuple[str, ...]

    def __bool__(self) -> bool:
        return bool(self.one_way_door or self.ml)


def reminder_for(paths: Iterable[str], patterns: Sequence[str]) -> Reminder:
    """改動的檔案（含改名前的舊路徑）中，要提醒的那些；重複的只列一次，照路徑排序。"""
    unique = sorted(set(paths))
    return Reminder(
        one_way_door=tuple(p for p in unique if any(matches(p, pat) for pat in patterns)),
        ml=tuple(p for p in unique if p in ML_PATHS))


def comment_body(reminder: Reminder) -> str:
    """留言的內文；開頭是 MARKER，下一次 push 用它找到這一則來改。"""
    out = [MARKER, "### CI 的路徑提醒", ""]
    if not reminder:
        out.append("這個 PR 現在沒有動到單向門的路徑或 ML 依賴（之前提醒的檔案已經不在改動裡）。")
        return "\n".join(out) + "\n"
    if reminder.one_way_door:
        out += ["**單向門**：動到 `docs/agents/merging.md` 第 4 步列出的路徑。PR 內文的「門的類型」"
                "要標明 one-way，並在「證據」寫明怎麼驗證。", ""]
        out += [f"- `{p}`" for p in reminder.one_way_door]
        out.append("")
    if reminder.ml:
        out += ["**要在本機重建 Docker**：CI 不安裝 ML 依賴，動到下列檔案（`backend/Dockerfile` 是改到 "
                "ML 那一段時）要在本機執行 `.\\dc.bat rebuild` 確認，等使用者回報通過再合併"
                "（`docs/agents/merging.md` 的例外）。", ""]
        out += [f"- `{p}`" for p in reminder.ml]
        out.append("")
    out.append("_這則留言由 CI 依改動的路徑產生，之後每次 push 會更新同一則；不擋合併。_")
    return "\n".join(out) + "\n"


# ─── 與 GitHub 溝通（只在 CI 上跑）──────────────────────────────────────


def _gh(*args: str) -> str:
    done = subprocess.run(["gh", *args], capture_output=True, encoding="utf-8", check=False)
    if done.returncode:
        raise RuntimeError(f"gh {' '.join(args)} 失敗（結束碼 {done.returncode}）：{done.stderr.strip()}")
    return done.stdout


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"沒有環境變數 {name}：這個指令由 CI 呼叫，見 .github/workflows/")
    return value


def _is_pull_request() -> bool:
    event = os.environ.get("EVENT_NAME", "")
    if event != "pull_request":
        print(f"事件是 {event or '（沒有）'}，不是 PR：不檢查")
        return False
    return True


def cmd_body() -> int:
    if not _is_pull_request():
        return 0
    pr = json.loads(_gh("api", f"repos/{_env('REPO')}/pulls/{_env('PR_NUMBER')}"))
    problem = body_problem(pr.get("body"))
    if problem:
        print(f"::error::{problem}")
        return 1
    print(f"PR 內文有「{USER_VISIBLE}」")
    return 0


def _changed_paths(repo: str, number: str) -> list[str]:
    out = _gh("api", "--paginate", f"repos/{repo}/pulls/{number}/files?per_page=100",
              "--jq", '.[] | .filename, (.previous_filename // empty)')
    paths = [line for line in out.splitlines() if line]
    # 這個 API 最多列 3000 個檔案；達到上限時清單可能不完整
    if len(paths) >= 3000:
        print("::warning::PR 改動的檔案達到 API 的上限，路徑提醒可能不完整")
    return paths


def _previous_comment(repo: str, number: str) -> str | None:
    jq = (f'.[] | select(.user.login == "github-actions[bot]" and '
          f'(.body | startswith("{MARKER}"))) | .id')
    ids = _gh("api", "--paginate", f"repos/{repo}/issues/{number}/comments?per_page=100",
              "--jq", jq).split()
    return ids[0] if ids else None


def cmd_paths() -> int:
    if not _is_pull_request():
        return 0
    repo, number = _env("REPO"), _env("PR_NUMBER")
    reminder = reminder_for(_changed_paths(repo, number),
                            one_way_door_patterns(MERGING.read_text(encoding="utf-8")))
    body = comment_body(reminder)
    print(body)

    if os.environ.get("HEAD_REPO") != repo:
        # fork 來的 PR：GITHUB_TOKEN 只能讀，留不了言
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary and reminder:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(body)
        print("從 fork 開的 PR 不留言；提醒寫在 job 的摘要")
        return 0

    previous = _previous_comment(repo, number)
    if previous is None and not reminder:
        print("沒有要提醒的路徑，也沒有之前的提醒：不留言")
        return 0
    body_file = Path(os.environ.get("RUNNER_TEMP", ".")) / "pr-paths-comment.md"
    body_file.write_text(body, encoding="utf-8")
    if previous is None:
        _gh("api", f"repos/{repo}/issues/{number}/comments", "-F", f"body=@{body_file}")
        print("已留言")
    else:
        _gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{previous}",
            "-F", f"body=@{body_file}")
        print(f"已更新留言 {previous}")
    return 0


def main(argv: Sequence[str]) -> int:
    commands = {"body": cmd_body, "paths": cmd_paths}
    if len(argv) != 1 or argv[0] not in commands:
        print(f"用法：python tools/pr_checks.py {{{'|'.join(commands)}}}", file=sys.stderr)
        return 2
    try:
        return commands[argv[0]]()
    except RuntimeError as e:
        print(f"::error::{e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
