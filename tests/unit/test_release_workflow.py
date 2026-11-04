"""release.yml 的結構（#278）：權限最小、先草稿後公開、失敗時不半發布。

workflow 本身要推 tag 才跑得到（#279 實跑），這裡守住改 workflow 時最容易不小心弄壞的幾件事：
- 只有發布的 job 有 contents: write，而且它不執行建置或第三方套件（npm 套件與建置腳本在唯讀的 job 執行）。
- 發布的 job 依序：檢查附件 → 建草稿 → 上傳 → 確認草稿上的附件 → 公開；失敗時刪掉這次建的草稿，tag 不動。
- 建置用的映像、zip 的名稱與附件的檢查，和 ci.yml 的 portable job 每個 PR 跑的相同。
"""
from pathlib import Path

import yaml

from tools import portable_zip

ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


RELEASE = _workflow("release.yml")
CI = _workflow("ci.yml")
JOBS = RELEASE["jobs"]


def _steps(job: str) -> list[dict]:
    return JOBS[job]["steps"]


def _runs(job: str) -> list[str]:
    return [step["run"] for step in _steps(job) if "run" in step]


def test_permissions_are_granted_per_job_and_only_publish_can_write():
    assert RELEASE["permissions"] == {}
    assert JOBS["ci"]["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert JOBS["build"]["permissions"] == {"contents": "read"}
    assert JOBS["publish"]["permissions"] == {"contents": "write"}
    writers = [name for name, job in JOBS.items() if "write" in (job.get("permissions") or {}).values()]
    assert writers == ["publish"]


def test_jobs_run_in_order():
    assert JOBS["build"]["needs"] == "ci"
    assert JOBS["publish"]["needs"] == "build"


def test_publish_runs_no_build_or_third_party_code():
    actions = [step["uses"].split("@")[0] for step in _steps("publish") if "uses" in step]
    assert actions == ["actions/checkout", "actions/download-artifact"]
    for run in _runs("publish"):
        assert "npm" not in run and "build_release" not in run and "pip install" not in run


def test_publish_drafts_verifies_then_publishes_and_cleans_up_on_failure():
    ids = [step.get("id") for step in _steps("publish") if "run" in step]
    assert ids == ["check", "tag-commit", "unique", "draft", "upload", "verify", "publish", "cleanup"]
    steps = {step.get("id"): step for step in _steps("publish")}
    assert "-F draft=true -F prerelease=true" in steps["draft"]["run"]
    assert "verify-release" in steps["verify"]["run"] and "--draft" in steps["verify"]["run"]
    assert "-F draft=false" in steps["publish"]["run"]
    cleanup = steps["cleanup"]
    assert cleanup["if"] == "${{ (failure() || cancelled()) && steps.unique.outcome == 'success' }}"
    # 只刪草稿，不刪 tag（gh release delete --cleanup-tag 之類）
    assert '[ "$draft" = "true" ]' in cleanup["run"]
    assert "--method DELETE \"repos/$GH_REPO/releases/$id\"" in cleanup["run"]
    assert "cleanup-tag" not in cleanup["run"] and "git/refs" not in cleanup["run"]


def test_publish_uses_the_artifact_build_uploaded():
    upload = next(step for step in _steps("build") if step.get("uses", "").startswith("actions/upload-artifact@"))
    download = next(step for step in _steps("publish") if step.get("uses", "").startswith("actions/download-artifact@"))
    assert upload["with"]["name"] == download["with"]["name"]
    assert upload["with"]["path"] == "build/release-assets/"
    assert upload["with"]["if-no-files-found"] == "error"


def test_build_matches_the_portable_job_every_pr_runs():
    portable = CI["jobs"]["portable"]
    assert JOBS["build"]["runs-on"] == portable["runs-on"]
    runs = _runs("build")
    assert '.\\build_release.ps1 -Version "$env:TAG" -SkipFrontend' in runs
    assert f'python tools/portable_zip.py check "build/{portable_zip.PRODUCT}-$env:TAG-win64.zip"' in runs
    assert 'python -m tools.release_assets prepare "$env:TAG" build/release-assets' in runs
    assert 'python -m tools.release_assets check "$env:TAG" build/release-assets' in runs
    portable_runs = [step["run"] for step in portable["steps"] if "run" in step]
    assert "python -m tools.release_assets prepare ci build/release-assets" in portable_runs
    assert "python -m tools.release_assets check ci build/release-assets" in portable_runs


def test_build_checks_the_tag_before_building():
    names = [step.get("name") for step in _steps("build")]
    assert names.index("檢查 tag 的格式") < names.index("Build release package")


def test_checkouts_do_not_keep_credentials():
    for job in ("build", "publish"):
        for step in _steps(job):
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False
