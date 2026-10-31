"""Issue 範本（.github/ISSUE_TEMPLATE）：每份都提醒 Issue 是公開的，送出前要確認（#24）。

回饋只走 GitHub Issues（ADR-0005），而這個 repo 的 Issue 是公開的：附上的轉錄結果或錄音等於公開
私人錄音的內容（#27）。所以每份範本開頭都要提醒不要附這些東西，結尾要勾選確認；新增範本時忘了
寫，這裡就會紅燈。

範本的語法由 GitHub 在 main 上解析，CI 驗不到：改範本時另外用 SchemaStore 的
github-issue-forms.json 驗一次，合併後在範本選單看一次（PR 內文寫明）。
"""
import re
from pathlib import Path

import pytest
import yaml

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / ".github" / "ISSUE_TEMPLATE"
FORMS = sorted(p for p in TEMPLATE_DIR.glob("*.yml") if p.name != "config.yml")

# 開頭的提醒要提到的東西：Issue 是公開的，以及不能附上的三樣
NOTICE_PHRASES = ("公開", "轉錄結果", "私人錄音", "API 金鑰")

# 範本自動加上的標籤。repo 裡沒有的標籤 GitHub 會默默略過，打錯字也不會有人發現；這三個已經
# 存在（docs/agents/triage-labels.md 的 needs-triage，以及 triage 的分類 bug、enhancement）
KNOWN_LABELS = {"bug", "enhancement", "needs-triage"}

# GitHub 對 body 元素 id 的規定：只能用英數字、- 與 _，同一份表單裡不能重複
ELEMENT_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_three_forms_exist():
    assert [p.name for p in FORMS] == ["1-bug.yml", "2-transcription-quality.yml", "3-feature.yml"]


@pytest.mark.parametrize("path", FORMS, ids=lambda p: p.name)
def test_form_opens_with_privacy_notice(path):
    first = load(path)["body"][0]
    assert first["type"] == "markdown"
    for phrase in NOTICE_PHRASES:
        assert phrase in first["attributes"]["value"], f"{path.name} 開頭的提醒沒提到「{phrase}」"


@pytest.mark.parametrize("path", FORMS, ids=lambda p: p.name)
def test_form_ends_with_required_privacy_check(path):
    last = load(path)["body"][-1]
    assert last["type"] == "checkboxes"
    assert last["id"] == "privacy"
    [option] = last["attributes"]["options"]
    assert option["required"] is True
    for phrase in NOTICE_PHRASES[1:]:
        assert phrase in option["label"]


@pytest.mark.parametrize("path", FORMS, ids=lambda p: p.name)
def test_form_fields_are_well_formed(path):
    form = load(path)
    assert form["name"] and form["description"]
    assert set(form["labels"]) <= KNOWN_LABELS
    fields = [element for element in form["body"] if element["type"] != "markdown"]
    ids = [field["id"] for field in fields]
    assert len(ids) == len(set(ids)), f"{path.name} 有重複的 id"
    for field in fields:
        assert ELEMENT_ID.match(field["id"]), field["id"]
        assert field["attributes"]["label"], field["id"]


def test_template_names_are_unique():
    names = [load(p)["name"] for p in FORMS]
    assert len(names) == len(set(names))


def test_blank_issues_are_disabled():
    # 空白 Issue 沒有隱私提醒；維護者仍看得到「Maintainers only」的空白選項
    config = load(TEMPLATE_DIR / "config.yml")
    assert config["blank_issues_enabled"] is False
    for link in config["contact_links"]:
        assert link["url"].startswith("https://github.com/Wade0325/AI_translate")
        assert link["name"] and link["about"]
