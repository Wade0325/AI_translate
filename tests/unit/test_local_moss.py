"""Local provider 的 MOSS 路徑：輸出解析、長度預算、權重對照、模型分流、切段門檻。

torch 在 conftest 已被 mock，這裡只測純邏輯；模型推論與 Windows 注意力的數值
正確性在 lab/src/moss.py（attn-check、E7）以真實 GPU 驗證過。
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.exceptions import TranscriptionCancelledError
from app.provider.local import asr, moss, weights
from app.services.transcription import flows


# ─── 輸出解析 ────────────────────────────────────────────────────────────

class TestParseOutput:
    def test_segments_and_zero_based_speakers(self):
        text = "[0.48][S01]こんにちは[1.66][12.26][S02]元気？[13.81]"
        assert moss.parse_output(text) == [
            {"Start": 0.48, "End": 1.66, "Speaker": 0, "Content": "こんにちは"},
            {"Start": 12.26, "End": 13.81, "Speaker": 1, "Content": "元気？"},
        ]

    def test_drops_empty_and_reversed_segments(self):
        text = "[1.0][S01]  [2.0][5.0][S01]倒過來[4.0][6.0][S01]保留[7.0]"
        assert [s["Content"] for s in moss.parse_output(text)] == ["保留"]

    def test_keeps_non_numeric_brackets_in_text(self):
        segs = moss.parse_output("[3.5][S01]あはは[笑]、そうだね[6.25]")
        assert segs[0]["Content"] == "あはは[笑]、そうだね"

    def test_numeric_brackets_inside_text_do_not_end_segment(self):
        # 文字裡的 [3] 後面不是下一段開頭，不能當成結束時間戳
        text = "[10.0][S01]請看第[3]章的內容[15.2][16.0][S02]好[17.5]"
        assert moss.parse_output(text) == [
            {"Start": 10.0, "End": 15.2, "Speaker": 0, "Content": "請看第[3]章的內容"},
            {"Start": 16.0, "End": 17.5, "Speaker": 1, "Content": "好"},
        ]

    def test_truncated_last_segment_is_dropped(self):
        # 生成被截斷：最後一段沒有結束時間戳，不能憑空補上
        segs = moss.parse_output("[0.0][S01]完整[1.0][2.0][S01]被截斷的")
        assert [s["Content"] for s in segs] == ["完整"]

    def test_empty_or_garbage(self):
        assert moss.parse_output("") == []
        assert moss.parse_output("no timestamps here") == []


# ─── 長度預算 ────────────────────────────────────────────────────────────

class TestMaxNewTokens:
    def test_short_audio_keeps_floor(self):
        assert moss.max_new_tokens_for(10) == 2048

    def test_scales_with_duration(self):
        # 51.8 分鐘：12 token/秒 + 1024
        assert moss.max_new_tokens_for(3105) == 3105 * 12 + 1024


class TestGenerationBudget:
    def test_uses_length_budget_when_context_has_room(self):
        # 實測 51.8 分鐘的 prompt 為 41168 token
        assert moss.generation_budget(41168, 3105) == 3105 * 12 + 1024

    def test_clamped_to_remaining_context(self):
        assert moss.generation_budget(125000, 9000) == moss.MAX_LENGTH - 125000

    def test_no_room_raises_instead_of_truncating(self):
        with pytest.raises(ValueError, match="音檔過長"):
            moss.generation_budget(moss.MAX_LENGTH - 500, 9000)


class TestLatestSegmentStart:
    def test_ignores_numbers_in_text(self):
        text = "[10.0][S01]西暦[2024]年のこと[15.0][16.5][S02]はい"
        assert moss.latest_segment_start(text) == 16.5

    def test_no_segment_start(self):
        assert moss.latest_segment_start("西暦[2024]年") is None


class TestMaxSinglePassSeconds:
    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        monkeypatch.setattr(moss, "get_settings",
                            lambda: SimpleNamespace(local_moss_single_pass_max_seconds=4200.0))

    def test_16gb_card_uses_setting_cap(self, monkeypatch):
        monkeypatch.setattr(moss, "_total_vram_gib", lambda: 15.99)
        assert moss.max_single_pass_seconds() == 4200.0

    def test_smaller_card_is_limited_by_vram(self, monkeypatch):
        monkeypatch.setattr(moss, "_total_vram_gib", lambda: 8.0)
        seconds = moss.max_single_pass_seconds()
        assert 1500 < seconds < 2000

    def test_tiny_card_keeps_floor(self, monkeypatch):
        monkeypatch.setattr(moss, "_total_vram_gib", lambda: 4.0)
        assert moss.max_single_pass_seconds() == 300.0

    def test_no_gpu_falls_back_to_setting(self, monkeypatch):
        monkeypatch.setattr(moss, "_total_vram_gib", lambda: None)
        assert moss.max_single_pass_seconds() == 4200.0

    def test_user_setting_below_vram_floor_is_honored(self, monkeypatch):
        # 300 秒下限只套用在顯存估算，使用者明確設的值照用
        monkeypatch.setattr(moss, "get_settings",
                            lambda: SimpleNamespace(local_moss_single_pass_max_seconds=180.0))
        monkeypatch.setattr(moss, "_total_vram_gib", lambda: 4.0)
        assert moss.max_single_pass_seconds() == 180.0

    def test_zero_setting_disables_splitting(self, monkeypatch):
        monkeypatch.setattr(moss, "get_settings",
                            lambda: SimpleNamespace(local_moss_single_pass_max_seconds=0.0))
        monkeypatch.setattr(moss, "_total_vram_gib", lambda: 15.99)
        assert moss.max_single_pass_seconds() == 0.0

    def test_context_budget_caps_large_settings(self, monkeypatch):
        # 大顯卡＋調高設定時，上下文（prompt＋預留生成 ≤ 131072 token）才是上限
        monkeypatch.setattr(moss, "get_settings",
                            lambda: SimpleNamespace(local_moss_single_pass_max_seconds=20000.0))
        monkeypatch.setattr(moss, "_total_vram_gib", lambda: 80.0)
        seconds = moss.max_single_pass_seconds()
        prompt = seconds * (moss.AUDIO_TOKENS_PER_SECOND + moss.MARKER_TOKENS_PER_SECOND)
        assert 5000 < seconds < 6000
        assert prompt + seconds * 8 <= moss.MAX_LENGTH


# ─── 權重對照 ────────────────────────────────────────────────────────────

class TestWeights:
    def test_default_model_needs_only_moss_and_aligner(self):
        assert weights.DEFAULT_LOCAL_MODEL == weights.MOSS_ALIGN
        assert weights.REQUIRED_REPOS == (weights.MOSS_MODEL_ID, weights.ALIGNER_MODEL_ID)

    def test_repos_per_model(self):
        assert weights.ASR_MODEL_ID in weights.repos_for_model(weights.MOSS_QWEN)
        assert weights.DIARIZATION_MODEL_ID in weights.repos_for_model(weights.VIBEVOICE_QWEN)
        assert weights.repos_for_model("unknown") == weights.REQUIRED_REPOS
        assert weights.repos_for_model(None) == weights.REQUIRED_REPOS

    def test_all_repos_is_deduplicated_union(self):
        assert len(weights.ALL_REPOS) == len(set(weights.ALL_REPOS)) == 4

    def test_is_moss_model(self):
        assert weights.is_moss_model(weights.MOSS_ALIGN)
        assert weights.is_moss_model(weights.MOSS_QWEN)
        assert not weights.is_moss_model(weights.VIBEVOICE_QWEN)

    @pytest.mark.parametrize("model", [None, "", "vibevoice", "no-such-model"])
    def test_unknown_names_normalize_to_default(self, model):
        # 分流、切段門檻、權重檢查都要對同一個模型做決定
        assert weights.normalize_model(model) == weights.DEFAULT_LOCAL_MODEL
        assert weights.is_moss_model(model)

    def test_ensure_local_ready_reports_missing_for_selected_model(self, monkeypatch):
        monkeypatch.setattr(weights, "cuda_status", lambda: (True, "GPU"))
        monkeypatch.setattr(weights, "repo_is_ready",
                            lambda repo: repo != weights.ASR_MODEL_ID)
        weights.ensure_local_ready(weights.MOSS_ALIGN)  # 預設模型不需要 Qwen3-ASR
        with pytest.raises(ValueError, match="Qwen3-ASR-1.7B"):
            weights.ensure_local_ready(weights.MOSS_QWEN)

    @staticmethod
    def _snapshot(folder, present=None):
        shards = ("model-1.safetensors", "model-2.safetensors")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.json").write_text("{}")
        (folder / "model.safetensors.index.json").write_text(
            json.dumps({"weight_map": {str(i): s for i, s in enumerate(shards)}}))
        for name in (shards if present is None else present):
            (folder / name).write_bytes(b"x")
        return folder

    @staticmethod
    def _fake_hub(monkeypatch, local, online=None):
        """離線查詢回傳 local（None＝沒快取），線上下載回傳 online（None＝連不上）。"""
        import huggingface_hub
        calls = []

        def fake(repo_id, revision=None, local_files_only=False, **kwargs):
            calls.append((repo_id, revision, local_files_only))
            if local_files_only:
                if local is None:
                    raise FileNotFoundError("not cached")
                return str(local)
            if online is None:
                raise OSError("offline")
            return str(online)

        monkeypatch.setattr(huggingface_hub, "snapshot_download", fake)
        return calls

    def test_complete_local_snapshot_stays_offline(self, monkeypatch, tmp_path):
        snap = self._snapshot(tmp_path / "snap")
        calls = self._fake_hub(monkeypatch, snap, online=None)
        assert weights.repo_is_ready(weights.MOSS_MODEL_ID)
        assert weights.resolve_repo(weights.MOSS_MODEL_ID) == str(snap)
        # 只做離線查詢，且帶釘住的 revision
        assert calls and all(local_only for _, _, local_only in calls)
        assert calls[0][1] == weights.REPO_REVISIONS[weights.MOSS_MODEL_ID]

    def test_partial_snapshot_is_completed_online(self, monkeypatch, tmp_path):
        # 中斷的下載：config 與索引在，但缺一個權重分片
        partial = self._snapshot(tmp_path / "partial", present=["model-1.safetensors"])
        done = self._snapshot(tmp_path / "done")
        calls = self._fake_hub(monkeypatch, partial, online=done)
        assert not weights.repo_is_ready(weights.ALIGNER_MODEL_ID)
        assert weights.resolve_repo(weights.ALIGNER_MODEL_ID) == str(done)
        assert calls[-1] == (weights.ALIGNER_MODEL_ID,
                             weights.REPO_REVISIONS[weights.ALIGNER_MODEL_ID], False)

    def test_missing_and_offline_raises_instead_of_unpinned_fallback(self, monkeypatch):
        # 不退回 from_pretrained(repo_id)——那會載入未釘住的最新版
        self._fake_hub(monkeypatch, None, online=None)
        with pytest.raises(OSError):
            weights.resolve_repo(weights.ALIGNER_MODEL_ID)

    def test_load_pretrained_repairs_missing_small_files(self, monkeypatch, tmp_path):
        # 權重齊全但缺 tokenizer：本機路徑載入失敗 → 線上補齊後重試
        snap = self._snapshot(tmp_path / "snap")
        repaired = self._snapshot(tmp_path / "repaired")
        self._fake_hub(monkeypatch, snap, online=repaired)
        tried = []

        def loader(path):
            tried.append(path)
            if path == str(snap):
                raise OSError("tokenizer.json not found")
            return "loaded"

        assert weights.load_pretrained(weights.ALIGNER_MODEL_ID, loader) == "loaded"
        assert tried == [str(snap), str(repaired)]

    def test_load_pretrained_keeps_original_error_when_repair_fails(self, monkeypatch, tmp_path):
        # 離線時補齊失敗：拋出原本的載入錯誤，不讓網路錯誤蓋掉真正的原因
        snap = self._snapshot(tmp_path / "snap")
        self._fake_hub(monkeypatch, snap, online=None)

        def loader(path):
            raise OSError("[WinError 1455] paging file is too small")

        with pytest.raises(OSError, match="WinError 1455"):
            weights.load_pretrained(weights.ALIGNER_MODEL_ID, loader)

    def test_notice_only_when_weights_missing(self, monkeypatch):
        messages = []
        monkeypatch.setattr(weights, "repo_is_ready", lambda repo: repo == weights.MOSS_MODEL_ID)
        weights.notice_if_missing(weights.MOSS_MODEL_ID, "MOSS", messages.append)
        weights.notice_if_missing(weights.ALIGNER_MODEL_ID, "Qwen3-ForcedAligner", messages.append)
        assert messages == ["本地模型：首次使用，下載 Qwen3-ForcedAligner 權重（約 1.9 GB）..."]

    def test_load_pretrained_does_not_retry_other_errors(self, monkeypatch, tmp_path):
        snap = self._snapshot(tmp_path / "snap")
        calls = self._fake_hub(monkeypatch, snap, online=snap)

        def loader(path):
            raise RuntimeError("CUDA out of memory")

        with pytest.raises(RuntimeError):
            weights.load_pretrained(weights.ALIGNER_MODEL_ID, loader)
        assert all(local_only for _, _, local_only in calls)

    def test_snapshot_without_weights_is_not_ready(self, monkeypatch, tmp_path):
        folder = tmp_path / "s"
        folder.mkdir()
        (folder / "config.json").write_text("{}")
        self._fake_hub(monkeypatch, folder)
        assert not weights.repo_is_ready(weights.ALIGNER_MODEL_ID)

    def test_single_file_weights_are_ready(self, monkeypatch, tmp_path):
        folder = tmp_path / "s"
        folder.mkdir()
        (folder / "config.json").write_text("{}")
        (folder / "model.safetensors").write_bytes(b"x")
        self._fake_hub(monkeypatch, folder)
        assert weights.repo_is_ready(weights.ALIGNER_MODEL_ID)

    def test_ensure_local_ready_requires_gpu(self, monkeypatch):
        monkeypatch.setattr(weights, "cuda_status", lambda: (False, None))
        with pytest.raises(ValueError, match="NVIDIA GPU"):
            weights.ensure_local_ready()


# ─── 模型分流 ────────────────────────────────────────────────────────────

MOSS_SEGMENTS = [
    {"Start": 0.5, "End": 2.0, "Speaker": 0, "Content": "おはよう。"},
    {"Start": 3.0, "End": 4.5, "Speaker": 1, "Content": "  "},
]


@pytest.fixture
def pipeline(monkeypatch):
    """把各階段換成記錄呼叫的假函式，回傳呼叫紀錄。"""
    calls = {}

    def to_mono(path, sample_rate):
        calls["sample_rate"] = sample_rate
        return Path("does-not-exist_mono.wav")

    def run_moss(wav, cancel_check=None, status_callback=None):
        calls["moss"] = True
        return [dict(s) for s in MOSS_SEGMENTS]

    def run_diarization(wav, cancel_check=None, status_callback=None):
        calls["vibevoice"] = True
        return [{"Start": 0.5, "End": 2.0, "Speaker": 0, "Content": "vv"}]

    def transcribe_segments(wav, segments, language, status_callback=None, cancel_check=None):
        calls["qwen_segments"] = segments
        return [{"start": 0.5, "end": 2.0, "speaker": 0, "text": "qwen 文字",
                 "text_alt": segments[0]["Content"]}]

    def build_lrc_lines(wav, entries, status_callback=None, cancel_check=None):
        calls["entries"] = entries
        return [f"[00:00.50][S{e['speaker']}] {e['text']}" for e in entries]

    monkeypatch.setattr(asr, "_to_mono", to_mono)
    monkeypatch.setattr(asr, "_run_moss", run_moss)
    monkeypatch.setattr(asr, "_run_diarization", run_diarization)
    monkeypatch.setattr(asr, "_transcribe_segments", transcribe_segments)
    monkeypatch.setattr(asr, "_build_lrc_lines", build_lrc_lines)
    return calls


class TestModelDispatch:
    def test_moss_align_uses_moss_text_without_qwen(self, pipeline):
        result = asr.transcribe_with_local_models(Path("in.wav"), "ja", model="moss-align")
        assert pipeline["sample_rate"] == asr.MOSS_SAMPLE_RATE
        assert pipeline.get("moss") and "qwen_segments" not in pipeline
        assert "vibevoice" not in pipeline
        # 空白片段不送對齊器；text_alt 為空（沒有第二份假設）
        assert pipeline["entries"] == [
            {"start": 0.5, "end": 2.0, "speaker": 0, "text": "おはよう。", "text_alt": None}]
        assert result["success"] and result["text"] == "[00:00.50][S0] おはよう。"
        assert result["segments"][0]["source"] == "moss"

    def test_moss_qwen_feeds_moss_segments_to_qwen(self, pipeline):
        result = asr.transcribe_with_local_models(Path("in.wav"), "ja", model="moss-qwen3-asr")
        assert pipeline["sample_rate"] == asr.MOSS_SAMPLE_RATE
        assert pipeline["qwen_segments"][0]["Content"] == "おはよう。"
        assert result["segments"][0]["source"] == "qwen"
        assert result["segments"][0]["text_alt"] == "おはよう。"

    def test_vibevoice_keeps_legacy_path(self, pipeline):
        asr.transcribe_with_local_models(Path("in.wav"), "ja", model="vibevoice-qwen3-asr")
        assert pipeline["sample_rate"] == asr.DIARIZATION_SAMPLE_RATE
        assert pipeline.get("vibevoice") and "moss" not in pipeline

    @pytest.mark.parametrize("model", [None, "", "no-such-model"])
    def test_missing_or_unknown_model_defaults_to_moss_align(self, pipeline, model):
        asr.transcribe_with_local_models(Path("in.wav"), "ja", model=model)
        assert pipeline.get("moss") and "qwen_segments" not in pipeline


class TestRunMoss:
    @pytest.fixture(autouse=True)
    def _no_transformers(self, monkeypatch):
        # 真的 StoppingCriteria 需要匯入 transformers（torch 已被 mock）；這裡只測取消檢查
        monkeypatch.setattr(asr, "_make_cancel_stopping_criteria", lambda cancel_check: None)

    def test_cancel_after_generate_raises(self, monkeypatch):
        monkeypatch.setattr(moss, "transcribe",
                            lambda wav, stopping_criteria=None, status_callback=None:
                            (list(MOSS_SEGMENTS), "raw"))
        with pytest.raises(TranscriptionCancelledError):
            asr._run_moss(Path("x.wav"), cancel_check=lambda: True)

    def test_returns_segments(self, monkeypatch):
        monkeypatch.setattr(moss, "transcribe",
                            lambda wav, stopping_criteria=None, status_callback=None:
                            (list(MOSS_SEGMENTS), "raw"))
        assert asr._run_moss(Path("x.wav")) == MOSS_SEGMENTS


# ─── 切段門檻 ────────────────────────────────────────────────────────────

class TestSplitThreshold:
    @pytest.fixture(autouse=True)
    def _no_vad(self, monkeypatch):
        monkeypatch.setattr(flows, "get_vad_service", lambda: None)
        monkeypatch.setattr(moss, "max_single_pass_seconds", lambda: 4200.0)

    def _task(self, provider, model):
        return flows.TranscriptionTask(
            client=None, model=model, prompt="", temp_dir=Path("."), provider=provider)

    def test_local_moss_models_use_single_pass_limit(self):
        assert self._task("local", "moss-align").split_threshold_seconds == 4200.0
        assert self._task("local", "moss-qwen3-asr").split_threshold_seconds == 4200.0

    def test_unknown_local_model_matches_what_asr_runs(self):
        # asr 會把不認得的名稱當成 moss-align 執行，門檻也要跟著用 MOSS 的
        assert self._task("local", "no-such-model").split_threshold_seconds == 4200.0

    def test_vibevoice_and_gemini_keep_global_setting(self):
        expected = flows.LONG_AUDIO_SPLIT_THRESHOLD_SECONDS
        assert self._task("local", "vibevoice-qwen3-asr").split_threshold_seconds == expected
        assert self._task("google", "gemini-2.5-flash").split_threshold_seconds == expected

    def test_audio_within_threshold_is_not_split(self, monkeypatch):
        task = self._task("local", "moss-align")
        sentinel = object()
        monkeypatch.setattr(task, "_attempt_transcription", lambda path: sentinel)
        # 51.8 分鐘（舊門檻 900 秒會切成 4 段）在 MOSS 門檻內一次處理
        assert task._transcribe_halved(Path("a.wav"), 3105.0, None) is sentinel
