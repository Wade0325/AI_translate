"""缺模型權重時的下載指引：錯誤訊息指向使用者做得到的地方，下載指令補齊缺的權重（#123）。

免安裝模式的設定頁有權重卡；Docker 模式在主機的 GPU worker 轉錄，設定頁沒有權重卡，
訊息改指向在主機執行的下載指令。
"""
import importlib.util
import re

import pytest

from app.core.config import get_settings
from app.provider.local import download_weights, weights


@pytest.fixture
def hub(monkeypatch):
    """有顯卡；``ready`` 裡的權重已下載，下載只記錄 repo 並把它標成已下載。"""
    ready: set[str] = set()
    downloaded: list[str] = []

    def fake_download(repo_id, **kwargs):
        downloaded.append(repo_id)
        ready.add(repo_id)
        return f"/cache/{repo_id}"

    monkeypatch.setattr(weights, "detect_gpu", lambda: weights.Gpu("Test GPU", 16.0, True))
    monkeypatch.setattr(weights, "repo_is_ready", lambda repo: repo in ready)
    monkeypatch.setattr(weights, "download_snapshot", fake_download)
    return ready, downloaded


def _missing_weights_message(model: str) -> str:
    with pytest.raises(ValueError) as error:
        weights.ensure_local_ready(model)
    return str(error.value)


# ─── 錯誤訊息 ────────────────────────────────────────────────────────────

def test_standalone_points_to_the_settings_page(monkeypatch, hub):
    monkeypatch.setattr(get_settings(), "app_mode", "standalone")
    message = _missing_weights_message(weights.MOSS_ALIGN)
    assert "請至 Settings 頁面下載" in message
    assert weights.MOSS_MODEL_ID in message and weights.ALIGNER_MODEL_ID in message


def test_docker_mode_points_to_a_command_that_downloads_the_missing_weights(monkeypatch, hub):
    monkeypatch.setattr(get_settings(), "app_mode", "docker")
    ready, downloaded = hub
    ready.add(weights.MOSS_MODEL_ID)

    message = _missing_weights_message(weights.MOSS_QWEN)
    # Docker 模式的設定頁沒有權重卡
    assert "Settings" not in message
    assert weights.ASR_MODEL_ID in message and weights.ALIGNER_MODEL_ID in message

    # 訊息裡的指令照著執行，就補齊這個模型缺的權重，任務的前置檢查跟著通過
    command = re.search(r"python\.exe -m (\S+) (\S+)", message)
    assert command, message
    module, model = command.groups()
    assert importlib.util.find_spec(module) is not None
    assert module == download_weights.__name__
    assert download_weights.main([model]) == 0
    assert downloaded == [weights.ASR_MODEL_ID, weights.ALIGNER_MODEL_ID]
    weights.ensure_local_ready(weights.MOSS_QWEN)


# ─── 下載指令 ────────────────────────────────────────────────────────────

def test_without_a_model_downloads_what_the_default_model_needs(hub, capsys):
    ready, downloaded = hub
    ready.add(weights.MOSS_MODEL_ID)
    assert download_weights.main([]) == 0
    assert downloaded == [weights.ALIGNER_MODEL_ID]
    assert weights.ALIGNER_MODEL_ID in capsys.readouterr().out


def test_all_downloads_every_missing_repo_once(hub):
    ready, downloaded = hub
    ready.add(weights.ALIGNER_MODEL_ID)
    assert download_weights.main(["all"]) == 0
    assert downloaded == [r for r in weights.ALL_REPOS if r != weights.ALIGNER_MODEL_ID]


def test_nothing_to_download_when_everything_is_ready(hub, capsys):
    ready, downloaded = hub
    ready.update(weights.REQUIRED_REPOS)
    assert download_weights.main([]) == 0
    assert downloaded == []
    assert "都已下載" in capsys.readouterr().out


def test_unknown_model_is_rejected(hub, capsys):
    _, downloaded = hub
    with pytest.raises(SystemExit) as exited:
        download_weights.main(["no-such-model"])
    assert exited.value.code == 2
    assert downloaded == []
    assert "no-such-model" in capsys.readouterr().err


def test_failed_download_stops_and_exits_nonzero(hub, monkeypatch, capsys):
    _, downloaded = hub

    def offline(repo_id, **kwargs):
        downloaded.append(repo_id)
        raise OSError("network unreachable")

    monkeypatch.setattr(weights, "download_snapshot", offline)
    assert download_weights.main([]) == 1
    # 第一個就失敗，不接著下載下一個
    assert downloaded == [weights.REQUIRED_REPOS[0]]
    err = capsys.readouterr().err
    assert "network unreachable" in err
    assert "再執行一次" in err
