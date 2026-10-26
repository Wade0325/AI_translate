"""tools/pr_checks.py：PR 內文的檢查與依路徑的提醒留言（#38）。

CI 上的部分（呼叫 gh）用假的 gh 代替：測的是要不要留言、留在哪一則，以及留言寫了什麼。
"""
import json
from pathlib import Path

import pytest

from tools import pr_checks

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / ".github" / "pull_request_template.md"


def _filled(template: str, answer: str) -> str:
    """把範本「使用者看得到的變更」那一段的註解後面填上 answer。"""
    heading = f"## {pr_checks.USER_VISIBLE}\n"
    assert heading in template
    head, tail = template.split(heading, 1)
    comment_end = tail.index("-->") + len("-->")
    return head + heading + tail[:comment_end] + f"\n\n{answer}\n" + tail[comment_end:]


class TestBody:
    def test_unfilled_template_fails_until_the_section_is_written(self):
        # 範本那一段只有註解：照原樣送出的 PR 會紅燈，寫上「無」就轉綠
        template = TEMPLATE.read_text(encoding="utf-8")

        assert "是空的" in pr_checks.body_problem(template)
        assert pr_checks.body_problem(_filled(template, "無")) is None

    @pytest.mark.parametrize("body", [
        None,
        "",
        "## Summary\n\n改了一些東西\n",
        "使用者看得到的變更：無\n",  # 不是標題，也不是粗體標籤
    ])
    def test_missing_section_fails(self, body):
        assert "沒有「使用者看得到的變更」" in pr_checks.body_problem(body)

    @pytest.mark.parametrize("body", [
        "## 使用者看得到的變更\n\n無\n\n## 證據\n",
        "### 使用者看得到的變更 ###\r\n\r\n- 轉錄頁多一個按鈕\r\n",
        "## **使用者看得到的變更**\n\n無\n",
        # 範本上線前的粗體標籤寫法
        "Closes #1\n\n**使用者看得到的變更**：無。只改名。\n\n**畫面**：無畫面變更。\n",
        "**使用者看得到的變更**：\n\n- 按鈕不見了\n- 錯誤訊息改了\n\n**畫面**：無\n",
        # 子標題也算內容
        "## 使用者看得到的變更\n\n### 轉錄頁\n\n## 證據\n",
    ])
    def test_written_section_passes(self, body):
        assert pr_checks.body_problem(body) is None

    @pytest.mark.parametrize("body", [
        "## 使用者看得到的變更\n\n<!-- 必填，沒有就寫「無」 -->\n\n## 證據\n\n- Before：x\n",
        "## 使用者看得到的變更\n\n## 證據\n\n- Before：x\n",
        "**使用者看得到的變更**：\n\n**畫面**：無畫面變更\n",
        "# 使用者看得到的變更\n   \n",
    ])
    def test_empty_section_fails(self, body):
        assert "是空的" in pr_checks.body_problem(body)


class TestOneWayDoorList:
    @pytest.fixture(scope="class")
    def patterns(self):
        return pr_checks.one_way_door_patterns(
            (ROOT / "docs" / "agents" / "merging.md").read_text(encoding="utf-8"))

    def test_reads_the_list_in_merging_md(self, patterns):
        assert {"CLAUDE.md", "docs/agents/", ".github/", ".gitignore", "tools/check.py",
                "backend/requirements*.txt", "frontend/package-lock.json", "migrations/",
                "build_release.ps1"} <= set(patterns)

    def test_every_entry_still_points_at_something(self, patterns):
        # 改名或搬家之後清單沒跟著改，提醒就會悄悄失效
        stale = [p for p in patterns
                 if not (any(ROOT.glob(p)) if "*" in p else (ROOT / p).exists())]
        assert stale == [], f"merging.md 的單向門清單有不存在的路徑：{stale}"

    def test_refuses_when_the_list_moved(self):
        with pytest.raises(ValueError, match="ONE_WAY_DOOR_LEAD"):
            pr_checks.one_way_door_patterns("# 從開工到合併\n\n沒有清單\n")


class TestReminder:
    PATTERNS = ["CLAUDE.md", "docs/agents/", ".github/", "backend/requirements*.txt"]

    def test_lists_one_way_door_and_ml_files(self):
        reminder = pr_checks.reminder_for([
            "backend/app/main.py",
            "frontend/src/CLAUDE.md",           # 只有根目錄的 CLAUDE.md
            "CLAUDE.md",
            "docs/agents/merging.md",
            "docs/adr/0001-transcription-is-the-core.md",
            "backend/requirements-ml.txt",      # 兩邊都算
            "backend/Dockerfile",
            "docs/agents/merging.md",           # 改名前後都列出時只算一次
        ], self.PATTERNS)

        assert reminder.one_way_door == (
            "CLAUDE.md", "backend/requirements-ml.txt", "docs/agents/merging.md")
        assert reminder.ml == ("backend/Dockerfile", "backend/requirements-ml.txt")

    def test_nothing_to_remind(self):
        assert not pr_checks.reminder_for(["backend/app/main.py", "README.md"], self.PATTERNS)

    def test_comment_names_the_files_and_what_to_do(self):
        body = pr_checks.comment_body(pr_checks.Reminder(
            one_way_door=(".github/workflows/ci.yml",), ml=("backend/Dockerfile",)))

        assert body.startswith(pr_checks.MARKER)
        assert "- `.github/workflows/ci.yml`" in body
        assert "one-way" in body
        assert "- `backend/Dockerfile`" in body
        assert ".\\dc.bat rebuild" in body

    def test_comment_without_ml_files_does_not_mention_docker(self):
        body = pr_checks.comment_body(pr_checks.Reminder(one_way_door=("CLAUDE.md",), ml=()))

        assert "dc.bat" not in body

    def test_comment_when_nothing_is_left(self):
        body = pr_checks.comment_body(pr_checks.Reminder(one_way_door=(), ml=()))

        assert body.startswith(pr_checks.MARKER)
        assert "沒有動到單向門的路徑或 ML 依賴" in body


class FakeGh:
    """代替 gh：照 API 路徑回答，記下每一次呼叫。"""

    def __init__(self, files=(), comments=(), body=""):
        self.files = list(files)
        self.comments = list(comments)
        self.body = body
        self.calls: list[tuple[str, ...]] = []
        self.sent: list[str] = []

    def __call__(self, *args):
        self.calls.append(args)
        for arg in args:
            if arg.startswith("body=@"):
                self.sent.append(Path(arg.removeprefix("body=@")).read_text(encoding="utf-8"))
        endpoint = next(a for a in args if a.startswith("repos/"))
        if endpoint.endswith("/files?per_page=100"):
            return "\n".join(self.files) + "\n"
        if endpoint.endswith("/comments?per_page=100"):
            return "\n".join(self.comments) + "\n"
        if endpoint.endswith("/pulls/7"):
            return json.dumps({"number": 7, "body": self.body})
        return "{}"

    def writes(self):
        return [c for c in self.calls if "-F" in c]


@pytest.fixture
def pr(monkeypatch, tmp_path):
    monkeypatch.setenv("EVENT_NAME", "pull_request")
    monkeypatch.setenv("REPO", "owner/repo")
    monkeypatch.setenv("HEAD_REPO", "owner/repo")
    monkeypatch.setenv("PR_NUMBER", "7")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))

    def install(gh):
        monkeypatch.setattr(pr_checks, "_gh", gh)
        return gh
    return install


class TestBodyCommand:
    def test_reads_the_current_body_from_the_api(self, pr, capsys):
        pr(FakeGh(body="## 使用者看得到的變更\n\n無\n"))

        assert pr_checks.main(["body"]) == 0

    def test_fails_with_an_annotation(self, pr, capsys):
        pr(FakeGh(body="## Summary\n"))

        assert pr_checks.main(["body"]) == 1
        assert "::error::PR 內文沒有「使用者看得到的變更」" in capsys.readouterr().out

    def test_other_events_are_not_checked(self, pr, monkeypatch):
        gh = pr(FakeGh())
        monkeypatch.setenv("EVENT_NAME", "push")

        assert pr_checks.main(["body"]) == 0
        assert gh.calls == []


class TestPathsCommand:
    def test_first_reminder_is_a_new_comment(self, pr):
        gh = pr(FakeGh(files=["backend/app/main.py", ".github/workflows/ci.yml"]))

        assert pr_checks.main(["paths"]) == 0
        [write] = gh.writes()
        assert write[1] == "repos/owner/repo/issues/7/comments"
        assert "- `.github/workflows/ci.yml`" in gh.sent[0]

    def test_later_pushes_edit_the_same_comment(self, pr):
        gh = pr(FakeGh(files=["CLAUDE.md"], comments=["555"]))

        assert pr_checks.main(["paths"]) == 0
        [write] = gh.writes()
        assert write[:3] == ("api", "-X", "PATCH")
        assert write[3] == "repos/owner/repo/issues/comments/555"

    def test_previous_reminder_is_cleared_when_nothing_is_left(self, pr):
        gh = pr(FakeGh(files=["backend/app/main.py"], comments=["555"]))

        assert pr_checks.main(["paths"]) == 0
        assert len(gh.writes()) == 1
        assert "沒有動到單向門的路徑或 ML 依賴" in gh.sent[0]

    def test_no_comment_when_there_was_never_anything_to_remind(self, pr):
        gh = pr(FakeGh(files=["backend/app/main.py"]))

        assert pr_checks.main(["paths"]) == 0
        assert gh.writes() == []

    def test_renamed_file_counts_by_its_old_path(self, pr):
        # API 把改名前的舊路徑放在同一筆；_changed_paths 的 jq 把兩個都列成一行一個
        gh = pr(FakeGh(files=["docs/agents/renamed.md", "docs/agents/merging.md"]))

        assert pr_checks.main(["paths"]) == 0
        assert "- `docs/agents/merging.md`" in gh.sent[0]

    def test_looks_for_its_own_comment_only(self, pr):
        gh = pr(FakeGh(files=["CLAUDE.md"]))

        pr_checks.main(["paths"])
        [lookup] = [c for c in gh.calls if any(a.endswith("/comments?per_page=100") for a in c)]
        jq = lookup[lookup.index("--jq") + 1]
        assert '"github-actions[bot]"' in jq
        assert pr_checks.MARKER in jq

    def test_fork_pull_requests_get_the_job_summary_instead(self, pr, monkeypatch, tmp_path):
        gh = pr(FakeGh(files=["CLAUDE.md"]))
        monkeypatch.setenv("HEAD_REPO", "someone/fork")

        assert pr_checks.main(["paths"]) == 0
        assert gh.writes() == []
        assert "- `CLAUDE.md`" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_unknown_command():
    assert pr_checks.main(["merge"]) == 2
