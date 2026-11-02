"""比對基準與這個 PR 的轉錄環境（#276）：環境有一項不同，錯字率的差異就可能來自環境而不是改動，
不能拿來判定回歸（docs/adr/0009）。

manifest 的形狀和 ``python -m tools.eval transcribe`` 寫的相同（環境由
``backend/app/services/environment_manifest.py`` 記錄）。
"""
import copy
import subprocess

import pytest

from tools.eval import environment

MOSS = "OpenMOSS-Team/MOSS-Transcribe-Diarize"
ALIGNER = "Qwen/Qwen3-ForcedAligner-0.6B-hf"
BASE_COMMIT = "1" * 40
HEAD_COMMIT = "2" * 40


def manifest(commit=BASE_COMMIT, *, dirty=False, driver="576.02", **changes):
    """一份 transcribe 寫的 manifest；``changes`` 用「environment.gpu.name」這樣的路徑改其中一項。"""
    result = {
        "command": "transcribe",
        "request": {"provider": "local", "model": "moss-align", "language": "zh-TW"},
        "audio": {"file": "demo.wav", "sha256": "ab" * 32, "duration_seconds": 30.0},
        "code": {"commit": commit, "dirty": dirty},
        "environment": {
            "packages": {
                "torch": {"version": "2.8.0+cu128", "source": None},
                "transformers": {"version": "4.57.1", "source": None},
                "moss-transcribe-diarize": {
                    "version": "0.1.0",
                    "source": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize/archive/e3bdd93.zip"},
            },
            "gpu": {"name": "NVIDIA GeForce RTX 4080 SUPER", "vram_gb": 16.0, "driver": driver,
                    "cuda_visible_devices": "0"},
            "model_revisions": {MOSS: "704aa4a9c304e8520be88901e0d1960158ef5b15",
                                ALIGNER: "c07281df297b9905d24a508279258cccf987a064"},
            "settings": {"remove_silence": False, "speech_ratio_skip_threshold": 0.3,
                         "single_pass_seconds": 3600, "long_audio_split_threshold_seconds": 600},
        },
        "run": {"success": True, "rtf": 0.1, "peak_vram_gb": 10.5},
    }
    for path, value in changes.items():
        *parents, last = path.split(".")
        target = result
        for key in parents:
            target = target[key]
        if value is DELETE:
            del target[last]
        else:
            target[last] = value
    return result


DELETE = object()


def _ancestor(base, head):
    return True


def compare(base, head, *, is_ancestor=_ancestor):
    """``base``、``head`` 是一份 manifest 或一串（評測集的每個音檔一份）。"""
    as_list = lambda m: m if isinstance(m, list) else [m]  # noqa: E731
    return environment.compare(as_list(base), as_list(head), is_ancestor=is_ancestor)


def item(comparison, name):
    [found] = [i for i in comparison.items if i.name == name]
    return found


def problems(comparison):
    return {i.name: i.result for i in comparison.problems}


def test_same_environment_can_be_compared():
    comparison = compare(manifest(BASE_COMMIT), manifest(HEAD_COMMIT))

    assert comparison.ok
    assert [i.name for i in comparison.items] == [
        "commit", "模型", "顯卡", "驅動",
        "套件：torch", "套件：transformers", "套件：moss-transcribe-diarize",
        f"模型權重：{MOSS}", f"模型權重：{ALIGNER}",
        "設定：remove_silence", "設定：speech_ratio_skip_threshold", "設定：single_pass_seconds",
        "設定：long_audio_split_threshold_seconds",
    ]
    assert item(comparison, "commit").result == "基準在這個 PR 的歷史裡"
    assert item(comparison, "驅動") == environment.Item("驅動", "576.02", "同左", "相同", ok=True)
    assert item(comparison, "顯卡").base == "NVIDIA GeForce RTX 4080 SUPER（16.0 GB）"
    assert item(comparison, f"模型權重：{MOSS}").base == "`704aa4a9c304`"
    assert item(comparison, "設定：remove_silence").base == "false"


def test_a_different_driver_cannot_be_compared():
    comparison = compare(manifest(BASE_COMMIT, driver="576.02"), manifest(HEAD_COMMIT, driver="581.57"))

    assert not comparison.ok
    assert problems(comparison) == {"驅動": "**不同**"}
    assert item(comparison, "驅動") == environment.Item("驅動", "576.02", "581.57", "**不同**", ok=False)


def test_a_different_weight_revision_cannot_be_compared():
    head = manifest(HEAD_COMMIT, **{f"environment.model_revisions.{MOSS}": "f" * 40})

    comparison = compare(manifest(BASE_COMMIT), head)

    assert problems(comparison) == {f"模型權重：{MOSS}": "**不同**"}
    assert item(comparison, f"模型權重：{MOSS}").head == "`ffffffffffff`"


@pytest.mark.parametrize(("path", "value", "name"), [
    ("environment.gpu.name", "NVIDIA GeForce RTX 4090", "顯卡"),
    ("environment.gpu.vram_gb", 24.0, "顯卡"),
    ("environment.packages.torch", {"version": "2.9.0+cu128", "source": None}, "套件：torch"),
    ("environment.packages.moss-transcribe-diarize",
     {"version": "0.1.0", "source": "https://github.com/OpenMOSS/MOSS-Transcribe-Diarize/archive/0a1b2c3.zip"},
     "套件：moss-transcribe-diarize"),
    ("environment.settings.long_audio_split_threshold_seconds", 900, "設定：long_audio_split_threshold_seconds"),
    ("request.model", "moss-qwen3-asr", "模型"),
], ids=["gpu", "vram", "package version", "package source", "setting", "model"])
def test_any_other_difference_cannot_be_compared(path, value, name):
    comparison = compare(manifest(BASE_COMMIT), manifest(HEAD_COMMIT, **{path: value}))

    assert problems(comparison) == {name: "**不同**"}


def test_not_compared_language_and_visible_devices():
    # 評測集本來就有中文也有日文；CUDA_VISIBLE_DEVICES 選的那張卡，名稱與顯存已經比了
    head = manifest(HEAD_COMMIT, **{"request.language": "ja", "environment.gpu.cuda_visible_devices": "1"})

    assert compare(manifest(BASE_COMMIT), head).ok


def test_a_setting_only_one_side_has_cannot_be_compared():
    # 例如 PR 新增了一項設定：基準的程式還沒有它
    head = manifest(HEAD_COMMIT, **{"environment.settings.new_threshold": 5})

    comparison = compare(manifest(BASE_COMMIT), head)

    assert problems(comparison) == {"設定：new_threshold": "**不同**"}
    assert (item(comparison, "設定：new_threshold").base, item(comparison, "設定：new_threshold").head) == (
        "沒有", "5")


def test_a_manifest_without_the_driver_cannot_be_confirmed():
    # #276 之前寫的 manifest 沒有驅動：兩邊都沒有也不能算相同
    old = manifest(BASE_COMMIT, **{"environment.gpu.driver": DELETE})

    assert problems(compare(old, manifest(HEAD_COMMIT))) == {"驅動": "**沒有記錄，確認不了相同**"}
    assert problems(compare(old, copy.deepcopy(old))) == {"驅動": "**沒有記錄，確認不了相同**"}


def test_an_unreadable_driver_cannot_be_confirmed():
    # nvidia-smi 問不到驅動時記成 None
    comparison = compare(manifest(BASE_COMMIT, driver=None), manifest(HEAD_COMMIT, driver=None))

    assert problems(comparison) == {"驅動": "**讀不到，確認不了相同**"}


def test_a_manifest_without_the_environment_cannot_be_confirmed():
    old = manifest(BASE_COMMIT, environment=DELETE)

    assert problems(compare(old, copy.deepcopy(old))) == {
        name: "**沒有記錄，確認不了相同**" for name in ("顯卡", "驅動", "套件", "模型權重", "設定")}


def test_both_without_a_gpu_is_the_same():
    no_gpu = {"environment.gpu": None}

    comparison = compare(manifest(BASE_COMMIT, **no_gpu), manifest(HEAD_COMMIT, **no_gpu))

    assert comparison.ok
    assert item(comparison, "驅動").base == "沒有顯卡"


def test_every_audio_file_on_one_side_must_share_the_environment():
    # 基準分兩天跑，中間更新了驅動：就算 PR 和其中一天相同也不能比
    base = [manifest(BASE_COMMIT, driver="576.02"), manifest(BASE_COMMIT, driver="581.57")]
    head = [manifest(HEAD_COMMIT, driver="581.57"), manifest(HEAD_COMMIT, driver="581.57")]

    comparison = compare(base, head)

    assert problems(comparison) == {"驅動": "**基準的音檔之間就不同**"}
    assert item(comparison, "驅動").base == "576.02；581.57"
    assert problems(compare(head, base)) == {"驅動": "**這個 PR 的音檔之間就不同**"}


def test_the_same_commit_needs_no_git():
    def no_git(base, head):
        raise AssertionError("同一個 commit 不必問 git")

    comparison = compare(manifest(BASE_COMMIT), manifest(BASE_COMMIT), is_ancestor=no_git)

    assert item(comparison, "commit") == environment.Item(
        "commit", f"`{'1' * 12}`", "同左", "同一個 commit", ok=True)


@pytest.mark.parametrize(("base", "head", "ancestor", "result"), [
    (manifest(BASE_COMMIT), manifest(HEAD_COMMIT), False, "基準不在這個 PR 的歷史裡"),
    (manifest(BASE_COMMIT), manifest(HEAD_COMMIT), None, "確認不了"),
    (manifest(BASE_COMMIT, dirty=True), manifest(HEAD_COMMIT), True, "基準有沒 commit 的改動"),
    (manifest(BASE_COMMIT), manifest(HEAD_COMMIT, dirty=True), True, "這個 PR 有沒 commit 的改動"),
    (manifest(None), manifest(HEAD_COMMIT), True, "沒有記錄"),
    (manifest(BASE_COMMIT, **{"code": DELETE}), manifest(HEAD_COMMIT), True, "沒有記錄"),
    ([manifest(BASE_COMMIT), manifest("3" * 40)], manifest(HEAD_COMMIT), True, "基準來自不只一個 commit"),
    (manifest(BASE_COMMIT), [manifest(HEAD_COMMIT), manifest("3" * 40)], True, "這個 PR 來自不只一個 commit"),
], ids=["not an ancestor", "git cannot tell", "dirty baseline", "dirty PR", "no commit", "no code",
        "baseline from two commits", "PR from two commits"])
def test_commit_problems(base, head, ancestor, result):
    comparison = compare(base, head, is_ancestor=lambda b, h: ancestor)

    [problem] = comparison.problems
    assert (problem.name, problem.result) == ("commit", f"**{result}**")
    assert problem.remedy


def test_render_lists_every_item_and_what_to_do():
    head = manifest(HEAD_COMMIT, driver="581.57", **{f"environment.model_revisions.{MOSS}": "f" * 40})

    out = environment.render(compare(manifest(BASE_COMMIT), head, is_ancestor=lambda b, h: False))

    assert out.startswith("### 環境比對\n")
    assert "| 驅動 | 576.02 | 581.57 | **不同** |" in out
    assert "| 套件：torch | 2.8.0+cu128 | 同左 | 相同 |" in out
    assert (f"- ⚠ 環境不同（驅動、模型權重：{MOSS}）：先在目前的環境用 main 重建基準，再重跑評測。"
            in out)
    assert "- ⚠ commit：這個 PR 落後 main 時，先合併 main 再重跑這個 PR 的轉錄" in out
    assert "環境相同" not in out


def test_render_says_when_the_environment_is_the_same():
    out = environment.render(compare(manifest(BASE_COMMIT), manifest(HEAD_COMMIT)))

    assert out.rstrip().endswith("- 環境相同，可以直接和基準比。")
    assert "⚠" not in out


def test_a_package_from_a_local_file_shows_only_the_file_name():
    # 路徑常帶著帳號名稱，摘要要貼進 PR
    local = {"version": "0.1.0", "source": "file:///C:/Users/someone/wheels/moss_transcribe_diarize-0.1.0.zip"}
    changes = {"environment.packages.moss-transcribe-diarize": local}

    out = environment.render(compare(manifest(BASE_COMMIT, **changes), manifest(HEAD_COMMIT, **changes)))

    assert "| 套件：moss-transcribe-diarize | 0.1.0（moss_transcribe_diarize-0.1.0.zip） | 同左 | 相同 |" in out
    assert "someone" not in out


def _git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                           "-c", "commit.gpgsign=false", *args],
                          cwd=repo, capture_output=True, encoding="utf-8", check=True).stdout.strip()


def test_git_is_ancestor(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "main")
    main = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "pr")
    pr = _git(tmp_path, "rev-parse", "HEAD")

    assert environment.git_is_ancestor(main, pr, repo=tmp_path) is True
    assert environment.git_is_ancestor(pr, main, repo=tmp_path) is False
    assert environment.git_is_ancestor(main, main, repo=tmp_path) is True
    assert environment.git_is_ancestor("a" * 40, pr, repo=tmp_path) is None  # git 找不到
    assert environment.git_is_ancestor("--help", pr, repo=tmp_path) is None  # 不像 commit
