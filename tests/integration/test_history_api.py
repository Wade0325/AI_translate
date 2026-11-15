"""
整合測試：歷史紀錄 API
測試範圍：
  GET    /api/v1/history/stats
  GET    /api/v1/history
  GET    /api/v1/history/{task_uuid}
  DELETE /api/v1/history/{task_uuid}
"""
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database.models import BatchJob, TranscriptionLog
from app.repositories.correction_repository import Correction, CorrectionField, CorrectionRepository
from app.repositories.transcript_segment_repository import TranscriptSegmentRepository


# ─── 測試資料輔助函數 ─────────────────────────────────────────────────────────

def _create_log(db: Session, **kwargs) -> TranscriptionLog:
    """在資料庫中建立一筆測試用的 TranscriptionLog。"""
    defaults = {
        "task_uuid": uuid.uuid4(),
        "status": "COMPLETED",
        "original_filename": "test_audio.m4a",
        "audio_duration_seconds": 60.0,
        "processing_time_seconds": 10.0,
        "model_used": "gemini-2.5-flash",
        "provider": "Google",
        "source_language": "ja-JP",
        "target_language": None,
        "total_tokens": 5000,
        "cost": 0.005,
        "is_batch": False,
    }
    defaults.update(kwargs)
    log = TranscriptionLog(**defaults)
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def _noon_days_ago(days: int) -> datetime:
    """幾天前的中午，本地時間（和 request_timestamp 一樣）。"""
    return datetime.now().replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=days)


# ─── 統計 API ─────────────────────────────────────────────────────────────────

class TestHistoryStats:
    def test_stats_returns_200(self, client: TestClient):
        response = client.get("/api/v1/history/stats")
        assert response.status_code == 200

    def test_stats_has_required_fields(self, client: TestClient):
        response = client.get("/api/v1/history/stats")
        data = response.json()
        required_fields = [
            "total_tasks", "completed_tasks", "failed_tasks",
            "success_rate", "total_cost", "total_tokens",
            "total_audio_duration_seconds", "avg_processing_time_seconds",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_stats_numeric_fields_non_negative(self, client: TestClient):
        response = client.get("/api/v1/history/stats")
        data = response.json()
        assert data["total_tasks"] >= 0
        assert data["completed_tasks"] >= 0
        assert data["failed_tasks"] >= 0
        assert data["success_rate"] >= 0
        assert data["total_cost"] >= 0


# ─── 分頁查詢 API ─────────────────────────────────────────────────────────────

class TestHistoryList:
    def test_empty_history_returns_200(self, client: TestClient):
        response = client.get("/api/v1/history")
        assert response.status_code == 200

    def test_history_response_structure(self, client: TestClient):
        response = client.get("/api/v1/history")
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data

    def test_default_pagination(self, client: TestClient):
        """預設應回傳第 1 頁，每頁 20 筆"""
        response = client.get("/api/v1/history")
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 20

    def test_custom_pagination(self, client: TestClient):
        response = client.get("/api/v1/history?page=2&page_size=5")
        data = response.json()
        assert data["page"] == 2
        assert data["page_size"] == 5

    def test_page_size_must_be_at_least_1(self, client: TestClient):
        response = client.get("/api/v1/history?page_size=0")
        assert response.status_code == 422

    def test_page_must_be_at_least_1(self, client: TestClient):
        response = client.get("/api/v1/history?page=0")
        assert response.status_code == 422

    def test_page_size_max_100(self, client: TestClient):
        response = client.get("/api/v1/history?page_size=101")
        assert response.status_code == 422

    def test_filter_by_status_completed(self, client: TestClient, db_session: Session):
        """status 篩選應只回傳指定狀態的紀錄"""
        _create_log(db_session, status="COMPLETED", original_filename="completed.mp3")
        _create_log(db_session, status="FAILED", original_filename="failed.mp3")

        response = client.get("/api/v1/history?status=COMPLETED")
        data = response.json()
        for item in data["items"]:
            assert item["status"] == "COMPLETED"

    def test_filter_by_status_failed(self, client: TestClient, db_session: Session):
        _create_log(db_session, status="FAILED", original_filename="err.mp3")
        response = client.get("/api/v1/history?status=FAILED")
        data = response.json()
        for item in data["items"]:
            assert item["status"] == "FAILED"

    def test_filter_by_is_batch_false(self, client: TestClient, db_session: Session):
        _create_log(db_session, is_batch=False, original_filename="single.mp3")
        _create_log(db_session, is_batch=True, original_filename="batch.mp3",
                    batch_id="batch-001")
        response = client.get("/api/v1/history?is_batch=false")
        data = response.json()
        for item in data["items"]:
            assert item.get("is_batch") is False or item.get("is_batch") is None

    def test_keyword_search_by_filename(self, client: TestClient, db_session: Session):
        _create_log(db_session, original_filename="unique_keyword_xyzabc.mp3")
        response = client.get("/api/v1/history?keyword=unique_keyword_xyzabc")
        data = response.json()
        assert data["total"] >= 1
        filenames = [item["original_filename"] for item in data["items"]]
        assert any("unique_keyword_xyzabc" in fn for fn in filenames)

    def test_keyword_no_match_returns_empty(self, client: TestClient):
        response = client.get("/api/v1/history?keyword=IMPOSSIBLE_MATCH_ZZZZZ9999")
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_items_is_list(self, client: TestClient):
        response = client.get("/api/v1/history")
        data = response.json()
        assert isinstance(data["items"], list)

    def test_total_pages_calculation(self, client: TestClient, db_session: Session):
        """建立 5 筆紀錄，每頁 2 筆，應有 3 頁"""
        for i in range(5):
            _create_log(db_session, original_filename=f"pages_test_{i}.mp3",
                       task_uuid=uuid.uuid4())

        response = client.get("/api/v1/history?page_size=2")
        data = response.json()
        assert data["total_pages"] >= 3


# ─── 查詢單筆紀錄 ─────────────────────────────────────────────────────────────

class TestHistoryDetail:
    def test_get_existing_log(self, client: TestClient, db_session: Session):
        """取得已存在的紀錄應回傳完整資料"""
        log = _create_log(db_session, original_filename="detail_test.mp3")
        task_uuid = str(log.task_uuid)

        response = client.get(f"/api/v1/history/{task_uuid}")
        assert response.status_code == 200
        data = response.json()
        assert data["task_uuid"] == task_uuid
        assert data["original_filename"] == "detail_test.mp3"
        assert data["status"] == "COMPLETED"

    def test_get_nonexistent_log_returns_404(self, client: TestClient):
        """取得不存在的紀錄應回傳 404"""
        fake_uuid = str(uuid.uuid4())
        response = client.get(f"/api/v1/history/{fake_uuid}")
        assert response.status_code == 404

    def test_response_contains_model_used(self, client: TestClient, db_session: Session):
        log = _create_log(db_session, model_used="gemini-2.5-flash")
        response = client.get(f"/api/v1/history/{log.task_uuid}")
        data = response.json()
        assert data["model_used"] == "gemini-2.5-flash"

    def test_response_contains_cost(self, client: TestClient, db_session: Session):
        log = _create_log(db_session, cost=0.00123)
        response = client.get(f"/api/v1/history/{log.task_uuid}")
        data = response.json()
        assert abs(data["cost"] - 0.00123) < 1e-6

    def test_response_contains_audio_duration(self, client: TestClient, db_session: Session):
        log = _create_log(db_session, audio_duration_seconds=180.5)
        response = client.get(f"/api/v1/history/{log.task_uuid}")
        data = response.json()
        assert abs(data["audio_duration_seconds"] - 180.5) < 0.01


# ─── 刪除紀錄 ─────────────────────────────────────────────────────────────────

class TestHistoryDelete:
    def test_delete_existing_log(self, client: TestClient, db_session: Session):
        """刪除已存在的紀錄應回傳 success=True"""
        log = _create_log(db_session, original_filename="to_delete.mp3")
        task_uuid = str(log.task_uuid)

        response = client.delete(f"/api/v1/history/{task_uuid}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_delete_nonexistent_log_returns_404(self, client: TestClient):
        """刪除不存在的紀錄應回傳 404"""
        fake_uuid = str(uuid.uuid4())
        response = client.delete(f"/api/v1/history/{fake_uuid}")
        assert response.status_code == 404

    def test_delete_then_get_returns_404(self, client: TestClient, db_session: Session):
        """刪除後再查詢應回傳 404"""
        log = _create_log(db_session, original_filename="delete_then_get.mp3")
        task_uuid = str(log.task_uuid)

        client.delete(f"/api/v1/history/{task_uuid}")
        response = client.get(f"/api/v1/history/{task_uuid}")
        assert response.status_code == 404

    def test_delete_reduces_total_count(self, client: TestClient, db_session: Session):
        """刪除後統計數量應減少"""
        log = _create_log(db_session, original_filename="count_test.mp3")
        task_uuid = str(log.task_uuid)

        before = client.get("/api/v1/history").json()["total"]
        client.delete(f"/api/v1/history/{task_uuid}")
        after = client.get("/api/v1/history").json()["total"]
        assert after == before - 1


# ─── 字幕下載 ─────────────────────────────────────────────────────────────────

class TestHistoryDownload:
    _SAMPLE_LRC = "[00:01.00]Hello\n[00:03.00]World"

    def test_download_without_lrc_returns_404(self, client: TestClient, db_session: Session):
        log = _create_log(db_session, status="COMPLETED", lrc_content=None)
        response = client.get(f"/api/v1/history/{log.task_uuid}/download/lrc")
        assert response.status_code == 404

    def test_download_failed_task_returns_400(self, client: TestClient, db_session: Session):
        log = _create_log(
            db_session,
            status="FAILED",
            lrc_content=self._SAMPLE_LRC,
        )
        response = client.get(f"/api/v1/history/{log.task_uuid}/download/lrc")
        assert response.status_code == 400

    def test_download_invalid_format_returns_400(self, client: TestClient, db_session: Session):
        log = _create_log(
            db_session,
            status="COMPLETED",
            lrc_content=self._SAMPLE_LRC,
        )
        response = client.get(f"/api/v1/history/{log.task_uuid}/download/xyz")
        assert response.status_code == 400


# ─── 輸出格式的資料來源 ───────────────────────────────────────────────────────

SEGMENTS = [
    {"seg_key": "0000", "start": 1.5, "end": 2.8, "speaker": "S0", "text": "おはよう。"},
    {"seg_key": "0001", "start": 3.25, "end": 4.0, "speaker": "S1", "text": "こんにちは。"},
]
# 片段沒有逐字時間：一段一行，SRT／VTT 在片段的結束時結束；只有 0.75 秒的「こんにちは。」
# 顯示最短的 0.8 秒（#96、ADR-0008）。S1 的字幕是黃色（#12；VTT 用預設的顏色類別，#271）
FROM_SEGMENTS = {
    "lrc": "[00:01.50][S0] おはよう。\n[00:03.25][S1] こんにちは。",
    "srt": ("1\n00:00:01,500 --> 00:00:02,800\n[S0] おはよう。\n\n"
            "2\n00:00:03,250 --> 00:00:04,050\n<font color=\"#FFDD55\">[S1] こんにちは。</font>\n"),
    "vtt": ("WEBVTT\n\n00:00:01.500 --> 00:00:02.800\n[S0] おはよう。\n\n"
            "00:00:03.250 --> 00:00:04.050\n<c.yellow>[S1] こんにちは。</c>\n"),
    "txt": "[S0] おはよう。\n[S1] こんにちは。",
}


def _with_segments(db: Session, log: TranscriptionLog, segments=SEGMENTS) -> TranscriptionLog:
    TranscriptSegmentRepository.replace_for_task(db, log.task_uuid, segments)
    db.commit()
    return log


class TestDownloadFromSegments:
    @pytest.mark.parametrize("fmt", ["lrc", "srt", "vtt", "txt"])
    def test_every_format_comes_from_segments_not_the_stored_lrc(
            self, client: TestClient, db_session: Session, fmt):
        # 存下來的 LRC 只是凍結的原始轉錄副本，有片段時下載不讀它
        log = _create_log(db_session, lrc_content="[00:00.00]凍結的原始轉錄副本")
        TranscriptSegmentRepository.replace_for_task(db_session, log.task_uuid, SEGMENTS)
        db_session.commit()

        response = client.get(f"/api/v1/history/{log.task_uuid}/download/{fmt}")
        assert response.status_code == 200
        assert response.text == FROM_SEGMENTS[fmt]


# 沒有片段的任務（片段功能上線前的任務、#110 之前的 Gemini 任務、#115 之前批次裡的任務），輸出要和
# 以前從存下來的 LRC 轉換時一模一樣
STORED_LRC = ("[00:01.50]Speaker A: Hello\n[00:03.123]Speaker B: World\n"
              "這行沒有時間戳\n[61:02.00]Final line")
FROM_STORED_LRC = {
    "lrc": STORED_LRC,
    "srt": ("1\n00:00:01,500 --> 00:00:03,123\nHello\n\n"
            "2\n00:00:03,123 --> 01:01:02,000\nWorld\n\n"
            "3\n01:01:02,000 --> 01:01:07,000\nFinal line\n"),
    "vtt": ("WEBVTT\n\n00:00:01.500 --> 00:00:03.123\nHello\n\n"
            "00:00:03.123 --> 01:01:02.000\nWorld\n\n"
            "01:01:02.000 --> 01:01:07.000\nFinal line\n"),
    "txt": "Hello\nWorld\nFinal line",
}
BATCH_LRC = "[00:02.00]批次的結果"
FROM_BATCH_LRC = {
    "lrc": BATCH_LRC,
    "srt": "1\n00:00:02,000 --> 00:00:07,000\n批次的結果\n",
    "vtt": "WEBVTT\n\n00:00:02.000 --> 00:00:07.000\n批次的結果\n",
    "txt": "批次的結果",
}


class TestDownloadWithoutSegments:
    @pytest.mark.parametrize("fmt", ["lrc", "srt", "vtt", "txt"])
    def test_task_without_segments_converts_the_stored_lrc_as_before(
            self, client: TestClient, db_session: Session, fmt):
        log = _create_log(db_session, lrc_content=STORED_LRC)

        response = client.get(f"/api/v1/history/{log.task_uuid}/download/{fmt}")
        assert response.status_code == 200
        assert response.text == FROM_STORED_LRC[fmt]

    @pytest.mark.parametrize("fmt", ["lrc", "srt", "vtt", "txt"])
    def test_task_in_a_batch_without_stored_lrc_uses_the_batch_result(
            self, client: TestClient, db_session: Session, fmt):
        task_uuid = uuid.uuid4()
        batch_id = f"batch-{task_uuid.hex[:8]}"
        db_session.add(BatchJob(
            batch_id=batch_id,
            results_json=json.dumps({"f1": {"transcripts": {"lrc": BATCH_LRC}}}),
            file_log_uuids_json=json.dumps({"f1": str(task_uuid)}),
        ))
        db_session.commit()
        _create_log(db_session, task_uuid=task_uuid, is_batch=True, batch_id=batch_id)

        response = client.get(f"/api/v1/history/{task_uuid}/download/{fmt}")
        assert response.status_code == 200
        assert response.text == FROM_BATCH_LRC[fmt]

    def test_stored_lrc_without_timestamps_has_no_subtitles(
            self, client: TestClient, db_session: Session):
        log = _create_log(db_session, lrc_content="沒有任何時間戳")

        assert client.get(f"/api/v1/history/{log.task_uuid}/download/lrc").text == "沒有任何時間戳"
        response = client.get(f"/api/v1/history/{log.task_uuid}/download/srt")
        assert response.status_code == 404
        assert response.json()["detail"] == "無法產生此格式的字幕內容"


# ─── 下載的版本（#346）────────────────────────────────────────────────────────
# 下載預設給校正後版本，version=original 給原始轉錄（ADR 0011：校正後版本由原始轉錄加校正紀錄算出，
# 凍結的原始轉錄副本不回寫）。寫入校正的端點（#341）還沒做好，校正直接用 #340 的 repository 記

FOUR_SEGMENTS = [
    {"seg_key": "0000", "start": 1.0, "end": 2.0, "speaker": "S0", "text": "おはよう。"},
    {"seg_key": "0001", "start": 3.0, "end": 4.0, "speaker": "S1", "text": "えーと。"},
    {"seg_key": "0002", "start": 5.0, "end": 6.0, "speaker": "S1", "text": "こんにちは。"},
    {"seg_key": "0003", "start": 7.0, "end": 8.0, "speaker": "S0", "text": "さようなら。"},
]
# 原始轉錄：和這張之前的下載逐位元組相同。片段沒有逐字時間，一段一行，在片段的結束時結束
FOUR_ORIGINAL = {
    "lrc": ("[00:01.00][S0] おはよう。\n[00:03.00][S1] えーと。\n"
            "[00:05.00][S1] こんにちは。\n[00:07.00][S0] さようなら。"),
    "srt": ("1\n00:00:01,000 --> 00:00:02,000\n[S0] おはよう。\n\n"
            "2\n00:00:03,000 --> 00:00:04,000\n<font color=\"#FFDD55\">[S1] えーと。</font>\n\n"
            "3\n00:00:05,000 --> 00:00:06,000\n<font color=\"#FFDD55\">[S1] こんにちは。</font>\n\n"
            "4\n00:00:07,000 --> 00:00:08,000\n[S0] さようなら。\n"),
    "vtt": ("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n[S0] おはよう。\n\n"
            "00:00:03.000 --> 00:00:04.000\n<c.yellow>[S1] えーと。</c>\n\n"
            "00:00:05.000 --> 00:00:06.000\n<c.yellow>[S1] こんにちは。</c>\n\n"
            "00:00:07.000 --> 00:00:08.000\n[S0] さようなら。\n"),
    "txt": "[S0] おはよう。\n[S1] えーと。\n[S1] こんにちは。\n[S0] さようなら。",
}
# 校正後版本：0000 改了文字，0001 刪掉了（不出現，SRT 的編號照樣連續），0002 的說話者改成 S2
# （顏色跟著說話者編號換成青色）
FOUR_CORRECTED = {
    "lrc": "[00:01.00][S0] おはようございます。\n[00:05.00][S2] こんにちは。\n[00:07.00][S0] さようなら。",
    "srt": ("1\n00:00:01,000 --> 00:00:02,000\n[S0] おはようございます。\n\n"
            "2\n00:00:05,000 --> 00:00:06,000\n<font color=\"#66CCFF\">[S2] こんにちは。</font>\n\n"
            "3\n00:00:07,000 --> 00:00:08,000\n[S0] さようなら。\n"),
    "vtt": ("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n[S0] おはようございます。\n\n"
            "00:00:05.000 --> 00:00:06.000\n<c.cyan>[S2] こんにちは。</c>\n\n"
            "00:00:07.000 --> 00:00:08.000\n[S0] さようなら。\n"),
    "txt": "[S0] おはようございます。\n[S2] こんにちは。\n[S0] さようなら。",
}
FOUR_CORRECTIONS = [
    Correction("0000", CorrectionField.TEXT, "おはようございます。"),
    Correction("0001", CorrectionField.TEXT, ""),
    Correction("0002", CorrectionField.SPEAKER, "S2"),
]


def _download(client: TestClient, log: TranscriptionLog, fmt: str, version: Optional[str] = None):
    params = {"version": version} if version else {}
    return client.get(f"/api/v1/history/{log.task_uuid}/download/{fmt}", params=params)


def _corrected_task(db: Session, **kwargs) -> TranscriptionLog:
    """四個片段的任務，記了 FOUR_CORRECTIONS 這一次操作。"""
    log = _with_segments(db, _create_log(db, **kwargs), FOUR_SEGMENTS)
    CorrectionRepository.record_operation(db, log.task_uuid, FOUR_CORRECTIONS)
    return log


class TestDownloadVersions:
    @pytest.mark.parametrize("fmt", ["lrc", "srt", "vtt", "txt"])
    def test_corrected_version_is_the_default(self, client: TestClient, db_session: Session, fmt):
        log = _corrected_task(db_session)

        for version in (None, "corrected"):
            response = _download(client, log, fmt, version)
            assert response.status_code == 200
            assert response.text == FOUR_CORRECTED[fmt]

    @pytest.mark.parametrize("fmt", ["lrc", "srt", "vtt", "txt"])
    def test_original_version_is_the_same_as_before_corrections(
            self, client: TestClient, db_session: Session, fmt):
        log = _corrected_task(db_session)

        response = _download(client, log, fmt, "original")
        assert response.status_code == 200
        assert response.text == FOUR_ORIGINAL[fmt]

    @pytest.mark.parametrize("version", [None, "corrected", "original"])
    @pytest.mark.parametrize("fmt", ["lrc", "srt", "vtt", "txt"])
    def test_task_without_corrections_has_the_same_content_in_both_versions(
            self, client: TestClient, db_session: Session, fmt, version):
        log = _with_segments(db_session, _create_log(db_session), FOUR_SEGMENTS)

        assert _download(client, log, fmt, version).text == FOUR_ORIGINAL[fmt]

    @pytest.mark.parametrize("version", [None, "corrected", "original"])
    @pytest.mark.parametrize("fmt", ["lrc", "srt", "vtt", "txt"])
    def test_task_without_segments_gives_the_stored_lrc_in_both_versions(
            self, client: TestClient, db_session: Session, fmt, version):
        # 片段上線前的任務不能校正，兩個版本都是從存下來的 LRC 轉換的內容
        log = _create_log(db_session, lrc_content=STORED_LRC)

        assert _download(client, log, fmt, version).text == FROM_STORED_LRC[fmt]

    def test_corrections_do_not_change_the_frozen_copy(self, client: TestClient, db_session: Session):
        log = _corrected_task(db_session, lrc_content="[00:01.00][S0] おはよう。")

        db_session.expire_all()
        frozen = db_session.query(TranscriptionLog).filter_by(task_uuid=log.task_uuid).one().lrc_content
        assert frozen == "[00:01.00][S0] おはよう。"

    @pytest.mark.parametrize("fmt", ["lrc", "srt", "vtt", "txt"])
    def test_every_segment_deleted_has_nothing_to_download(
            self, client: TestClient, db_session: Session, fmt):
        # 四種格式一樣：VTT 不會只下載到檔頭
        log = _with_segments(db_session, _create_log(db_session), SEGMENTS)
        CorrectionRepository.record_operation(db_session, log.task_uuid, [
            Correction(seg["seg_key"], CorrectionField.TEXT, "") for seg in SEGMENTS])

        response = _download(client, log, fmt)
        assert response.status_code == 404
        assert response.json()["detail"] == "無法產生此格式的字幕內容"
        assert _download(client, log, fmt, "original").text == FROM_SEGMENTS[fmt]

    def test_corrected_version_follows_the_multi_speaker_switch_too(
            self, client: TestClient, db_session: Session):
        # 帶不帶說話者標記照當時的規則（Multi-Speaker 開關），對著被下載的那個版本算：關著時校正後
        # 版本一樣不帶，也不上色
        log = _corrected_task(db_session, multi_speaker=False)

        assert _download(client, log, "txt").text == "おはようございます。\nこんにちは。\nさようなら。"
        assert "color" not in _download(client, log, "srt").text

    def test_labels_follow_the_speakers_left_in_the_corrected_version(
            self, client: TestClient, db_session: Session):
        # 照模型判斷的任務（#352）：輸出有兩位以上的說話者才帶標記，對著被下載的那個版本算。校正把 S1 的
        # 兩段改成 S0 之後只剩一位，校正後版本不帶也不上色；原始轉錄照樣有兩位、帶標記
        log = _with_segments(db_session, _create_log(db_session, speaker_count="auto"), FOUR_SEGMENTS)
        CorrectionRepository.record_operation(db_session, log.task_uuid, [
            Correction("0001", CorrectionField.SPEAKER, "S0"),
            Correction("0002", CorrectionField.SPEAKER, "S0")])

        assert _download(client, log, "txt").text == "おはよう。\nえーと。\nこんにちは。\nさようなら。"
        assert "color" not in _download(client, log, "srt").text
        assert _download(client, log, "lrc", "original").text == FOUR_ORIGINAL["lrc"]

    def test_completed_result_counts_speakers_in_the_corrected_version(self, db_session: Session):
        # 批次取回的結果是校正後版本（#346）：結果頁的說話者數目和四種格式對著同一個版本算（#352）
        from app.tasks.lifecycle import completed_result

        log = _with_segments(db_session, _create_log(db_session, speaker_count="auto"), FOUR_SEGMENTS)
        CorrectionRepository.record_operation(db_session, log.task_uuid, [
            Correction("0001", CorrectionField.SPEAKER, "S0"),
            Correction("0002", CorrectionField.SPEAKER, "S0")])

        result = completed_result(db_session, log.task_uuid)
        assert result is not None
        assert (result["speaker_count"], result["selected_speaker_count"]) == (1, "auto")
        assert "[S" not in result["transcripts"]["lrc"]

    def test_unknown_version_is_rejected(self, client: TestClient, db_session: Session):
        log = _corrected_task(db_session)

        assert _download(client, log, "srt", "latest").status_code == 422


# ─── 改過文字的片段照常斷句與拆字幕（#357）─────────────────────────────────────
# 逐字時間對的是原始轉錄的文字。校正後版本照校正後的文字重算（沒改到的字沿用原本的時間，改到的字照字數
# 平均分配），交給同一套斷行與拆字幕的規則；這張之前，改過文字的片段整段變成一則字幕。期望值寫成黃金檔，
# 原始轉錄的是這張之前 main 的下載

MEETING = "今天先請王小明報告進度。預算的部分，我們下週開會的時候再請財務部門一起仔細討論一下比較好。大家有沒有問題？"
REPLY = "好，沒有問題。"


def _timed(text: str, start: float, step: float = 0.3, pause: float = 0.8) -> list:
    """本機的逐字時間：一個漢字一個詞，每個詞 step 秒、一個接一個；句尾標點停 pause 秒，讀點不算詞。"""
    words, time = [], start
    for char in text:
        if char in "。？":
            time += pause
        elif char != "，":
            words.append({"text": char, "start": round(time, 3), "end": round(time + step, 3)})
            time += step
    return words


MEETING_SEGMENTS = [
    {"seg_key": "0000", "seq": 0, "start": 10.0, "end": 30.0, "speaker": "S0", "text": MEETING,
     "words": _timed(MEETING, 10.2)},
    {"seg_key": "0001", "seq": 1, "start": 31.0, "end": 33.5, "speaker": "S1", "text": REPLY,
     "words": _timed(REPLY, 31.1)},
]
# 一句一則；第二句超過字寬上限，用逐字時間拆成兩則
MEETING_ORIGINAL_SRT = """1
00:00:10,200 --> 00:00:13,500
[S0] 今天先請王小明報告進度。

2
00:00:14,300 --> 00:00:18,800
[S0] 預算的部分，我們下週開會的時候再

3
00:00:18,800 --> 00:00:23,600
[S0] 請財務部門一起仔細討論一下比較好。

4
00:00:24,400 --> 00:00:26,500
[S0] 大家有沒有問題？

5
00:00:31,100 --> 00:00:32,600
<font color="#FFDD55">[S1] 好，沒有問題。</font>
"""
# 「王小明」改成「王曉明」：照樣一句一則、第二句拆成兩則，每一則的起訖時間都和原始轉錄相同
MEETING_CORRECTED_SRT = """1
00:00:10,200 --> 00:00:13,500
[S0] 今天先請王曉明報告進度。

2
00:00:14,300 --> 00:00:18,800
[S0] 預算的部分，我們下週開會的時候再

3
00:00:18,800 --> 00:00:23,600
[S0] 請財務部門一起仔細討論一下比較好。

4
00:00:24,400 --> 00:00:26,500
[S0] 大家有沒有問題？

5
00:00:31,100 --> 00:00:32,600
<font color="#FFDD55">[S1] 好，沒有問題。</font>
"""


class TestCorrectedTextKeepsItsLineBreaks:
    def test_one_character_changed_still_breaks_by_sentence_at_the_original_times(
            self, client: TestClient, db_session: Session):
        log = _with_segments(db_session, _create_log(db_session), MEETING_SEGMENTS)
        CorrectionRepository.record_operation(db_session, log.task_uuid, [
            Correction("0000", CorrectionField.TEXT, MEETING.replace("王小明", "王曉明"))])

        assert _download(client, log, "srt").text == MEETING_CORRECTED_SRT
        assert _download(client, log, "srt", "original").text == MEETING_ORIGINAL_SRT

    def test_shortened_sentence_ends_at_its_last_remaining_word(
            self, client: TestClient, db_session: Session):
        # 刪掉的字連同時間一起拿掉：第二句改短後在「論」的結束（22.1 秒）結束，其他句子不動
        log = _with_segments(db_session, _create_log(db_session), MEETING_SEGMENTS)
        CorrectionRepository.record_operation(db_session, log.task_uuid, [Correction(
            "0000", CorrectionField.TEXT, "今天先請王小明報告進度。預算的部分我們下週再討論。大家有沒有問題？")])

        assert _download(client, log, "lrc").text == (
            "[00:10.20][S0] 今天先請王小明報告進度。\n[00:14.30][S0] 預算的部分我們下週再討論。\n"
            "[00:24.40][S0] 大家有沒有問題？\n[00:31.10][S1] 好，沒有問題。")
        assert "00:00:14,300 --> 00:00:22,100\n[S0] 預算的部分我們下週再討論。" in _download(client, log, "srt").text


class TestDownloadFilename:
    @pytest.mark.parametrize("version, filename", [
        (None, "%E6%9C%83%E8%AD%B0.srt"),
        ("corrected", "%E6%9C%83%E8%AD%B0.srt"),
        ("original", "%E6%9C%83%E8%AD%B0.original.srt"),
    ])
    def test_original_version_has_original_before_the_extension(
            self, client: TestClient, db_session: Session, version, filename):
        # 會議.srt 是校正後版本、會議.original.srt 是原始轉錄；中文檔名照原本的寫法（RFC 5987）編碼
        log = _corrected_task(db_session, original_filename="會議.mp3")

        response = _download(client, log, "srt", version)
        assert response.headers["content-disposition"] == f"attachment; filename*=UTF-8''{filename}"

    def test_task_without_a_filename_is_named_transcript(self, client: TestClient, db_session: Session):
        log = _corrected_task(db_session, original_filename=None)

        response = _download(client, log, "txt", "original")
        assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''transcript.original.txt"


# ─── 用量彙總 API ─────────────────────────────────────────────────────────────

class TestHistoryUsage:
    def test_usage_returns_200_with_structure(self, client: TestClient):
        response = client.get("/api/v1/history/usage")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["daily"], list)
        assert isinstance(data["by_model"], list)
        assert isinstance(data["pricing"], list)

    def test_usage_counts_what_failed_and_cancelled_tasks_were_billed(
            self, client: TestClient, db_session: Session):
        # 失敗與取消的任務，供應商照樣收費：token 與費用算進每日與各模型的用量，檔案數只算完成的
        # （#155）。日期與模型都是其他測試沒用到的，那一天與那個模型只有這幾筆
        model = "usage-test-model-alpha"
        noon = _noon_days_ago(100)
        for status, tokens, cost in [
            ("COMPLETED", 1000, 0.1),
            ("COMPLETED", 2000, 0.2),
            ("FAILED", 400, 0.04),
            ("CANCELLED", 500, 0.05),
            # 沒有用量的（開始前就取消、還在處理中）什麼都不加
            ("CANCELLED", None, None),
            ("PROCESSING", None, None),
        ]:
            _create_log(db_session, model_used=model, status=status, total_tokens=tokens,
                        cost=cost, request_timestamp=noon)

        data = client.get("/api/v1/history/usage").json()
        [day] = [d for d in data["daily"] if d["date"] == noon.date().isoformat()]
        [entry] = [m for m in data["by_model"] if m["model"] == model]
        for row in (day, entry):
            assert row["tokens"] == 3900
            assert row["cost"] == pytest.approx(0.39)
            assert row["files"] == 2

    def test_tasks_without_usage_add_no_rows(self, client: TestClient, db_session: Session):
        # 只有沒用量的失敗與取消：不多出全是 0 的一天或一個模型，計費頁沒有用量時照樣顯示空的說明
        model = "usage-test-model-unbilled"
        noon = _noon_days_ago(101)
        _create_log(db_session, model_used=model, status="FAILED", total_tokens=0, cost=0.0,
                    request_timestamp=noon)
        _create_log(db_session, model_used=model, status="CANCELLED", total_tokens=None,
                    cost=None, request_timestamp=noon)

        data = client.get("/api/v1/history/usage").json()
        assert noon.date().isoformat() not in [d["date"] for d in data["daily"]]
        assert model not in [m["model"] for m in data["by_model"]]

    def test_usage_daily_has_expected_fields(self, client: TestClient, db_session: Session):
        _create_log(db_session, model_used="usage-test-model-daily",
                    total_tokens=500, cost=0.05)
        data = client.get("/api/v1/history/usage").json()
        assert len(data["daily"]) > 0
        for entry in data["daily"]:
            assert set(entry.keys()) == {"date", "tokens", "cost", "files"}

    def test_usage_pricing_from_model_prices(self, client: TestClient):
        data = client.get("/api/v1/history/usage").json()
        models = [p["model"] for p in data["pricing"]]
        assert "gemini-2.5-flash" in models
        assert "default" not in models
        for p in data["pricing"]:
            # 本機的模型（如 vibevoice-qwen3-asr）價格為 0，故僅要求非負
            assert p["input_text"] >= 0
            assert p["input_audio"] >= 0
            assert p["output_text"] >= 0

    def test_usage_invalid_days_returns_422(self, client: TestClient):
        assert client.get("/api/v1/history/usage?days=0").status_code == 422
        assert client.get("/api/v1/history/usage?days=999").status_code == 422


# ─── 能不能校正（#347）─────────────────────────────────────────────────────────
# 能校正的任務：已完成、有片段，而且不是轉錄並翻譯的任務（#345 第 1 節）。History 照這個值決定要不要
# 顯示「校正」按鈕

def _listed(client: TestClient, log: TranscriptionLog) -> dict:
    """History 清單裡這個任務的那一筆；用檔名搜尋，不受其他測試留下的紀錄影響。"""
    items = client.get("/api/v1/history", params={"keyword": log.original_filename}).json()["items"]
    (item,) = [i for i in items if i["task_uuid"] == str(log.task_uuid)]
    return item


class TestCorrectable:
    def test_completed_task_with_segments_is_correctable(
            self, client: TestClient, db_session: Session):
        log = _with_segments(db_session, _create_log(db_session, original_filename="ok-347.wav"))
        assert _listed(client, log)["correctable"] is True

    @pytest.mark.parametrize("status", ["PROCESSING", "FAILED", "CANCELLED"])
    def test_task_that_did_not_complete_is_not_correctable(
            self, client: TestClient, db_session: Session, status):
        log = _with_segments(db_session, _create_log(
            db_session, status=status, original_filename=f"{status.lower()}-347.wav"))
        assert _listed(client, log)["correctable"] is False

    def test_completed_task_without_segments_is_not_correctable(
            self, client: TestClient, db_session: Session):
        # 片段上線前的任務只有凍結的原始轉錄副本，能下載、不能逐段校正
        log = _create_log(db_session, original_filename="no-segments-347.wav",
                          lrc_content="[00:01.00]只有凍結的副本")
        assert _listed(client, log)["correctable"] is False

    def test_task_with_translation_is_not_correctable(self, client: TestClient, db_session: Session):
        log = _with_segments(db_session, _create_log(
            db_session, original_filename="translated-347.wav",
            source_language="ja-JP", target_language="zh-TW"))
        assert _listed(client, log)["correctable"] is False

    def test_target_language_same_as_source_is_not_with_translation(
            self, client: TestClient, db_session: Session):
        # 和提示詞同一條規則（app.core.default_prompt.build_prompt）：目標語言和來源相同時沒有翻譯，不是轉錄並翻譯
        log = _with_segments(db_session, _create_log(
            db_session, original_filename="same-language-347.wav",
            source_language="ja-JP", target_language="ja-JP"))
        assert _listed(client, log)["correctable"] is True

    def test_each_task_in_a_page_gets_its_own_value(self, client: TestClient, db_session: Session):
        ok = _with_segments(db_session, _create_log(db_session, original_filename="page-347-a.wav"))
        bare = _create_log(db_session, original_filename="page-347-b.wav")

        items = client.get("/api/v1/history", params={"keyword": "page-347"}).json()["items"]
        values = {i["task_uuid"]: i["correctable"] for i in items}
        assert values == {str(ok.task_uuid): True, str(bare.task_uuid): False}

    def test_detail_reports_it_too(self, client: TestClient, db_session: Session):
        log = _with_segments(db_session, _create_log(db_session, original_filename="detail-347.wav"))
        assert client.get(f"/api/v1/history/{log.task_uuid}").json()["correctable"] is True


# ─── 有沒有校正（#346）────────────────────────────────────────────────────────
# History 的下載選單照這個值決定要不要多一組「原始轉錄」：有校正紀錄的任務才有

class TestHasCorrections:
    def test_task_without_correction_records_has_none(self, client: TestClient, db_session: Session):
        log = _with_segments(db_session, _create_log(db_session, original_filename="plain-346.wav"))
        assert _listed(client, log)["has_corrections"] is False

    def test_task_with_a_correction_has_corrections(self, client: TestClient, db_session: Session):
        log = _corrected_task(db_session, original_filename="corrected-346.wav")
        assert _listed(client, log)["has_corrections"] is True

    def test_a_correction_saved_from_the_correction_page_marks_the_task(
            self, client: TestClient, db_session: Session):
        # 校正頁存的校正（#341 的 PATCH）：History 的清單標出這個任務有校正，刪除時的確認多一句（#348）
        log = _with_segments(db_session, _create_log(db_session, original_filename="patched-348.wav"))
        assert _listed(client, log)["has_corrections"] is False

        response = client.patch(f"/api/v1/transcripts/{log.task_uuid}/segments/0000", json={"text": "改過"})

        assert response.status_code == 200, response.text
        assert _listed(client, log)["has_corrections"] is True

    def test_correction_changed_back_still_counts(self, client: TestClient, db_session: Session):
        # 改回和原始轉錄相同之後，校正紀錄還在（ADR 0011：只增不改），下載選單照樣有原始轉錄
        log = _with_segments(db_session, _create_log(db_session, original_filename="reverted-346.wav"))
        CorrectionRepository.record_operation(
            db_session, log.task_uuid, [Correction("0000", CorrectionField.TEXT, "改過")])
        CorrectionRepository.record_operation(
            db_session, log.task_uuid, [Correction("0000", CorrectionField.TEXT, SEGMENTS[0]["text"])])

        assert _listed(client, log)["has_corrections"] is True

    def test_each_task_in_a_page_gets_its_own_value(self, client: TestClient, db_session: Session):
        corrected = _corrected_task(db_session, original_filename="page-346-a.wav")
        plain = _with_segments(db_session, _create_log(db_session, original_filename="page-346-b.wav"))
        bare = _create_log(db_session, original_filename="page-346-c.wav", lrc_content=STORED_LRC)

        items = client.get("/api/v1/history", params={"keyword": "page-346"}).json()["items"]
        values = {i["task_uuid"]: i["has_corrections"] for i in items}
        assert values == {str(corrected.task_uuid): True, str(plain.task_uuid): False,
                          str(bare.task_uuid): False}

    def test_detail_reports_it_too(self, client: TestClient, db_session: Session):
        log = _corrected_task(db_session, original_filename="detail-346.wav")
        assert client.get(f"/api/v1/history/{log.task_uuid}").json()["has_corrections"] is True
