"""
單元測試：Pydantic Schemas 驗證
測試範圍：schemas/schemas.py 中的所有模型
"""
import pytest
from pydantic import ValidationError
from app.schemas.schemas import (
    ProviderConfigRequest,
    ProviderConfigResponse,
    TestProviderRequest,
    TestProviderResponse,
    ModelConfigurationSchema,
    ServiceStatus,
    WebSocketTranscriptionRequest,
    WebSocketBatchRequest,
    BatchFileItem,
    HistoryLogResponse,
    HistoryListResponse,
    HistoryStatsResponse,
)


# ─── ProviderConfigRequest ───────────────────────────────────────────────────

class TestProviderConfigRequest:
    def test_valid_request(self):
        req = ProviderConfigRequest(
            provider="Google",
            apiKeys=["key1", "key2"],
            model="gemini-2.5-flash",
        )
        assert req.provider == "Google"
        assert req.api_keys == ["key1", "key2"]
        assert req.model == "gemini-2.5-flash"

    def test_prompt_is_optional(self):
        req = ProviderConfigRequest(
            provider="Google",
            apiKeys=["key1"],
            model="gemini-2.5-flash",
        )
        assert req.prompt is None

    def test_prompt_accepted(self):
        req = ProviderConfigRequest(
            provider="Google",
            apiKeys=["key1"],
            model="gemini-2.5-flash",
            prompt="Custom prompt",
        )
        assert req.prompt == "Custom prompt"

    def test_missing_provider_raises_validation_error(self):
        with pytest.raises(ValidationError):
            ProviderConfigRequest(apiKeys=["key1"], model="model")

    def test_missing_model_raises_validation_error(self):
        with pytest.raises(ValidationError):
            ProviderConfigRequest(provider="Google", apiKeys=["key1"])

    def test_missing_api_keys_raises_validation_error(self):
        with pytest.raises(ValidationError):
            ProviderConfigRequest(provider="Google", model="model")

    def test_empty_api_keys_list_accepted(self):
        req = ProviderConfigRequest(provider="Google", apiKeys=[], model="model")
        assert req.api_keys == []

    def test_api_keys_alias(self):
        """apiKeys 應該對應 api_keys 欄位"""
        data = {"provider": "Google", "apiKeys": ["k"], "model": "m"}
        req = ProviderConfigRequest.model_validate(data)
        assert req.api_keys == ["k"]


# ─── ProviderConfigResponse ──────────────────────────────────────────────────

class TestProviderConfigResponse:
    def test_serialization_uses_alias(self):
        resp = ProviderConfigResponse(
            provider="Google",
            api_keys=["key1"],
            model="gemini-2.5-flash",
        )
        data = resp.model_dump(by_alias=True)
        assert "apiKeys" in data
        assert data["apiKeys"] == ["key1"]

    def test_model_field_optional(self):
        resp = ProviderConfigResponse(provider="Google", api_keys=[])
        assert resp.model is None


# ─── TestProviderRequest ────────────────────────────────────────────────────

class TestProviderRequestSchema:
    def test_valid_test_provider_request(self):
        req = TestProviderRequest(
            provider="Google",
            apiKeys=["key1"],
            model="gemini-2.5-flash",
        )
        assert req.provider == "Google"
        assert req.api_keys == ["key1"]


# ─── TestProviderResponse ───────────────────────────────────────────────────

class TestProviderResponseSchema:
    def test_valid_success_response(self):
        resp = TestProviderResponse(
            success=True,
            message="連線成功",
            testedInterface="Google",
        )
        assert resp.success is True

    def test_valid_failure_response(self):
        resp = TestProviderResponse(
            success=False,
            message="連線失敗",
            testedInterface="Google",
        )
        assert resp.success is False

    def test_details_optional(self):
        resp = TestProviderResponse(
            success=True,
            message="OK",
            testedInterface="Google",
        )
        assert resp.details is None


# ─── ServiceStatus ───────────────────────────────────────────────────────────

class TestServiceStatus:
    def test_success_true(self):
        s = ServiceStatus(success=True)
        assert s.success is True

    def test_success_false_with_message(self):
        s = ServiceStatus(success=False, message="Error occurred")
        assert s.message == "Error occurred"

    def test_message_optional(self):
        s = ServiceStatus(success=True)
        assert s.message is None


# ─── WebSocketTranscriptionRequest ──────────────────────────────────────────

class TestWebSocketTranscriptionRequest:
    def _valid_payload(self):
        return {
            "filename": "audio.m4a",
            "original_filename": "my_audio.m4a",
            "provider": "Google",
            "model": "gemini-2.5-flash",
            "api_keys": "key123",
            "source_lang": "ja-JP",
        }

    def test_valid_request(self):
        req = WebSocketTranscriptionRequest(**self._valid_payload())
        assert req.filename == "audio.m4a"
        assert req.provider == "Google"

    def test_target_lang_optional(self):
        req = WebSocketTranscriptionRequest(**self._valid_payload())
        assert req.target_lang is None

    def test_multi_speaker_default_false(self):
        req = WebSocketTranscriptionRequest(**self._valid_payload())
        assert req.multi_speaker is False

    def test_multi_speaker_can_be_true(self):
        payload = self._valid_payload()
        payload["multi_speaker"] = True
        req = WebSocketTranscriptionRequest(**payload)
        assert req.multi_speaker is True

    def test_prompt_optional(self):
        req = WebSocketTranscriptionRequest(**self._valid_payload())
        assert req.prompt is None

    def test_original_text_optional(self):
        req = WebSocketTranscriptionRequest(**self._valid_payload())
        assert req.original_text is None

    def test_missing_required_field_raises_error(self):
        payload = self._valid_payload()
        del payload["filename"]
        with pytest.raises(ValidationError):
            WebSocketTranscriptionRequest(**payload)


# ─── WebSocketBatchRequest ───────────────────────────────────────────────────

class TestWebSocketBatchRequest:
    def _valid_payload(self):
        return {
            "files": [
                {"filename": "a.m4a", "original_filename": "audio_a.m4a", "file_uid": "uid-001"},
                {"filename": "b.m4a", "original_filename": "audio_b.m4a", "file_uid": "uid-002"},
            ],
            "provider": "Google",
            "model": "gemini-2.5-flash",
            "api_keys": "key123",
            "source_lang": "ja-JP",
        }

    def test_valid_batch_request(self):
        req = WebSocketBatchRequest(**self._valid_payload())
        assert len(req.files) == 2
        assert req.files[0].file_uid == "uid-001"

    def test_empty_files_list_accepted(self):
        payload = self._valid_payload()
        payload["files"] = []
        req = WebSocketBatchRequest(**payload)
        assert req.files == []

    def test_target_lang_optional(self):
        req = WebSocketBatchRequest(**self._valid_payload())
        assert req.target_lang is None


# ─── BatchFileItem ───────────────────────────────────────────────────────────

class TestBatchFileItem:
    def test_valid_item(self):
        item = BatchFileItem(
            filename="audio.m4a",
            original_filename="my_audio.m4a",
            file_uid="uid-123",
        )
        assert item.file_uid == "uid-123"

    def test_missing_file_uid_raises_error(self):
        with pytest.raises(ValidationError):
            BatchFileItem(filename="a.m4a", original_filename="a.m4a")


# ─── HistoryLogResponse ──────────────────────────────────────────────────────

class TestHistoryLogResponse:
    def test_minimal_valid_response(self):
        resp = HistoryLogResponse(task_uuid="abc-123")
        assert resp.task_uuid == "abc-123"
        assert resp.status is None

    def test_full_response(self):
        resp = HistoryLogResponse(
            task_uuid="abc-123",
            status="COMPLETED",
            original_filename="audio.m4a",
            audio_duration_seconds=120.5,
            processing_time_seconds=30.2,
            model_used="gemini-2.5-flash",
            provider="Google",
            total_tokens=5000,
            cost=0.001234,
            is_batch=False,
        )
        assert resp.status == "COMPLETED"
        assert resp.audio_duration_seconds == 120.5


# ─── HistoryStatsResponse ────────────────────────────────────────────────────

class TestHistoryStatsResponse:
    def test_valid_stats(self):
        stats = HistoryStatsResponse(
            total_tasks=100,
            completed_tasks=90,
            failed_tasks=10,
            success_rate=90.0,
            total_cost=1.234567,
            total_tokens=1000000,
            total_audio_duration_seconds=3600.0,
            avg_processing_time_seconds=15.5,
        )
        assert stats.total_tasks == 100
        assert stats.success_rate == 90.0

    def test_missing_required_field_raises_error(self):
        with pytest.raises(ValidationError):
            HistoryStatsResponse(
                total_tasks=100,
                # completed_tasks 缺失
            )


# ─── HistoryListResponse ─────────────────────────────────────────────────────

class TestHistoryListResponse:
    def test_valid_list_response(self):
        resp = HistoryListResponse(
            items=[HistoryLogResponse(task_uuid="abc")],
            total=1,
            page=1,
            page_size=20,
            total_pages=1,
        )
        assert resp.total == 1
        assert len(resp.items) == 1

    def test_empty_items(self):
        resp = HistoryListResponse(
            items=[],
            total=0,
            page=1,
            page_size=20,
            total_pages=0,
        )
        assert resp.items == []
