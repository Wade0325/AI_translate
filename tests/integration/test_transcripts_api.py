"""整合測試：校正介面用的轉錄文件 API

測試範圍：
  GET    /api/v1/transcripts/{task_uuid}（片段是校正後版本，另外帶著原始轉錄，#341）
  GET    /api/v1/transcripts/{task_uuid}/audio
  PATCH  /api/v1/transcripts/{task_uuid}/segments/{seg_key}（改文字、說話者、確認狀態，#341）
  POST   /api/v1/transcripts/{task_uuid}/operations/{operation_id}/undo（復原一次操作，#341）
  POST   /api/v1/transcripts/{task_uuid}/speakers/reassign（把這位說話者全部換成另一位，#354）
  PATCH  /api/v1/transcripts/{task_uuid}（切換整份當成同一位說話者，#354）
  DELETE /api/v1/history/{task_uuid} 連帶刪除片段
  寫入校正或確認狀態時，保留音檔的保留天數重新起算（#350）

校正的結果從讀取端點與 ``version=original`` 的下載驗（#25 的測試決策）；校正紀錄的筆數與操作編號
還沒有讀的端點（#355），直接查資料表。
"""
import json
import os
import time
import uuid
from pathlib import Path
from typing import Tuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.api.transcripts  # noqa: F401  app_log 只接得到 fixture 啟動前已經建立的 logger
from app.core.config import get_settings
from app.database.models import CorrectionRecord, TranscriptionLog, TranscriptSegment
from app.services import audio_store


def _create_log(db: Session, **kwargs) -> TranscriptionLog:
    defaults = {
        "task_uuid": uuid.uuid4(),
        "status": "COMPLETED",
        "original_filename": "meeting.m4a",
        "audio_duration_seconds": 120.0,
        "model_used": "vibevoice-qwen3-asr",
        "provider": "Local",
        "source_language": "zh-TW",
    }
    defaults.update(kwargs)
    log = TranscriptionLog(**defaults)
    db.add(log)
    db.commit()
    return log


def _create_segment(db: Session, task_uuid, **kwargs) -> TranscriptSegment:
    defaults = {
        "task_uuid": task_uuid,
        "seg_key": "0000",
        "seq": 0,
        "start_sec": 1.0,
        "end_sec": 3.5,
        "speaker": "S0",
        "text": "這個就是實作層",
        "text_alt": "這個就是十座城",
        "source": "qwen",
    }
    defaults.update(kwargs)
    seg = TranscriptSegment(**defaults)
    db.add(seg)
    db.commit()
    return seg


class TestGetTranscript:
    def test_unknown_task_returns_404(self, client: TestClient):
        assert client.get(f"/api/v1/transcripts/{uuid.uuid4()}").status_code == 404

    def test_malformed_uuid_returns_400(self, client: TestClient):
        assert client.get("/api/v1/transcripts/not-a-uuid").status_code == 400

    def test_completed_task_without_segments(self, client: TestClient, db_session: Session):
        log = _create_log(db_session)
        data = client.get(f"/api/v1/transcripts/{log.task_uuid}").json()
        assert data["segment_count"] == 0
        assert data["segments"] == []
        # 沒有保留音檔時要明確回報，前端才能決定是否顯示播放器
        assert data["audio_available"] is False

    def test_segments_returned_in_seq_order(self, client: TestClient, db_session: Session):
        log = _create_log(db_session)
        _create_segment(db_session, log.task_uuid, seg_key="b.0001", seq=1,
                        start_sec=9.0, speaker="S1", text="第二段")
        _create_segment(db_session, log.task_uuid, seg_key="a.0000", seq=0,
                        start_sec=1.0, speaker="S0", text="第一段")

        data = client.get(f"/api/v1/transcripts/{log.task_uuid}").json()
        assert [s["seq"] for s in data["segments"]] == [0, 1]
        assert [s["text"] for s in data["segments"]] == ["第一段", "第二段"]
        assert data["segment_count"] == 2

    def test_alt_text_and_words_exposed(self, client: TestClient, db_session: Session):
        log = _create_log(db_session)
        words = [{"text": "實", "start": 1.0, "end": 1.2},
                 {"text": "作", "start": 1.2, "end": 1.4}]
        _create_segment(db_session, log.task_uuid,
                        words_json=json.dumps(words, ensure_ascii=False))

        seg = client.get(f"/api/v1/transcripts/{log.task_uuid}").json()["segments"][0]
        # 第二份轉錄要能取到，前端才能標示兩個模型不一致的地方
        assert seg["text_alt"] == "這個就是十座城"
        assert seg["words"][0]["text"] == "實"
        assert seg["words"][1]["start"] == 1.2

    def test_broken_words_json_degrades_gracefully(self, client: TestClient, db_session: Session):
        log = _create_log(db_session)
        _create_segment(db_session, log.task_uuid, words_json="{not json")
        seg = client.get(f"/api/v1/transcripts/{log.task_uuid}").json()["segments"][0]
        assert seg["words"] is None


class TestGetTranscriptAudio:
    def test_missing_audio_returns_404(self, client: TestClient, db_session: Session):
        log = _create_log(db_session)
        assert client.get(f"/api/v1/transcripts/{log.task_uuid}/audio").status_code == 404

    def test_audio_filename_pointing_nowhere_returns_404(
            self, client: TestClient, db_session: Session):
        log = _create_log(db_session, audio_filename="does-not-exist.m4a")
        assert client.get(f"/api/v1/transcripts/{log.task_uuid}/audio").status_code == 404

    def test_serves_retained_audio(self, client: TestClient, db_session: Session, tmp_path,
                                   monkeypatch):
        from app.services import audio_store

        monkeypatch.setattr(audio_store, "store_path", lambda: tmp_path)
        (tmp_path / "kept.wav").write_bytes(b"RIFF0000WAVE")
        log = _create_log(db_session, audio_filename="kept.wav")

        resp = client.get(f"/api/v1/transcripts/{log.task_uuid}/audio")
        assert resp.status_code == 200
        assert resp.content == b"RIFF0000WAVE"
        # 播放器拖曳需要 Range 支援
        assert resp.headers.get("accept-ranges") == "bytes"

    def test_rejects_path_traversal_filename(self, client: TestClient, db_session: Session,
                                             tmp_path, monkeypatch):
        from app.services import audio_store

        monkeypatch.setattr(audio_store, "store_path", lambda: tmp_path)
        log = _create_log(db_session, audio_filename="../secret.wav")
        assert client.get(f"/api/v1/transcripts/{log.task_uuid}/audio").status_code == 404


class TestDeleteCascade:
    def test_deleting_history_removes_segments(self, client: TestClient, db_session: Session):
        log = _create_log(db_session)
        task_uuid = log.task_uuid
        _create_segment(db_session, task_uuid)

        assert client.delete(f"/api/v1/history/{task_uuid}").status_code == 200
        db_session.expire_all()
        remaining = (
            db_session.query(TranscriptSegment)
            .filter(TranscriptSegment.task_uuid == task_uuid)
            .count()
        )
        assert remaining == 0


class TestCorrectable:
    """直接開校正頁的網址時，畫面照這兩個欄位寫出為什麼不能校正（#347）。"""

    def _get(self, client: TestClient, log: TranscriptionLog) -> dict:
        return client.get(f"/api/v1/transcripts/{log.task_uuid}").json()

    def test_completed_task_with_segments(self, client: TestClient, db_session: Session):
        log = _create_log(db_session)
        _create_segment(db_session, log.task_uuid)
        data = self._get(client, log)
        assert data["correctable"] is True
        assert data["uncorrectable_reason"] is None

    def test_task_that_is_still_transcribing(self, client: TestClient, db_session: Session):
        log = _create_log(db_session, status="PROCESSING")
        data = self._get(client, log)
        assert data["correctable"] is False
        assert data["uncorrectable_reason"] == "not_completed"

    def test_task_without_segments(self, client: TestClient, db_session: Session):
        data = self._get(client, _create_log(db_session))
        assert data["correctable"] is False
        assert data["uncorrectable_reason"] == "no_segments"

    def test_task_with_translation(self, client: TestClient, db_session: Session):
        log = _create_log(db_session, source_language="ja-JP", target_language="zh-TW")
        _create_segment(db_session, log.task_uuid)
        data = self._get(client, log)
        assert data["correctable"] is False
        assert data["uncorrectable_reason"] == "with_translation"


# ─── 校正（#341） ────────────────────────────────────────────────────────────

def _url(task_uuid, seg_key="0000") -> str:
    return f"/api/v1/transcripts/{task_uuid}/segments/{seg_key}"


def _undo_url(task_uuid, operation_id) -> str:
    return f"/api/v1/transcripts/{task_uuid}/operations/{operation_id}/undo"


def _correctable(db: Session, **segment) -> TranscriptionLog:
    """一個能校正的任務：已完成，一個片段 0000（說話者 S0，文字「這個就是實作層」）。"""
    log = _create_log(db)
    _create_segment(db, log.task_uuid, **segment)
    return log


def _segment(client: TestClient, task_uuid, seg_key="0000") -> dict:
    segments = client.get(f"/api/v1/transcripts/{task_uuid}").json()["segments"]
    return next(s for s in segments if s["seg_key"] == seg_key)


def _records(db: Session, task_uuid) -> list:
    """(改了什麼, 改前, 改後, 操作編號)，依編號排序。"""
    db.expire_all()
    rows = (db.query(CorrectionRecord).filter(CorrectionRecord.task_uuid == task_uuid)
            .order_by(CorrectionRecord.id).all())
    return [(r.field, r.old_value, r.new_value, str(r.operation_id)) for r in rows]


def _download(client: TestClient, task_uuid, version: str) -> str:
    response = client.get(f"/api/v1/history/{task_uuid}/download/txt", params={"version": version})
    assert response.status_code == 200, response.text
    return response.text


class TestReadCorrectedVersion:
    def test_an_untouched_segment_is_its_original_transcription(self, client, db_session):
        log = _correctable(db_session)

        segment = _segment(client, log.task_uuid)

        assert {key: segment[key] for key in (
            "text", "original_text", "speaker", "original_speaker", "corrected", "deleted",
            "has_correction_records", "review_state")} == {
            "text": "這個就是實作層", "original_text": "這個就是實作層", "speaker": "S0",
            "original_speaker": "S0", "corrected": False, "deleted": False,
            "has_correction_records": False, "review_state": None}


class TestCorrectText:
    def test_corrected_text_is_read_back_and_the_original_stays(self, client, db_session):
        log = _correctable(db_session)
        original_download = _download(client, log.task_uuid, "original")

        response = client.patch(_url(log.task_uuid), json={"text": "這個就是十座城"})

        assert response.status_code == 200, response.text
        body = response.json()
        segment = _segment(client, log.task_uuid)
        assert body["segment"] == segment
        assert (segment["text"], segment["original_text"], segment["corrected"],
                segment["has_correction_records"]) == ("這個就是十座城", "這個就是實作層", True, True)
        assert _records(db_session, log.task_uuid) == [
            ("text", "這個就是實作層", "這個就是十座城", body["operation_id"])]
        # 原始轉錄的下載不變，校正後版本的下載是改好的
        assert _download(client, log.task_uuid, "original") == original_download
        assert "這個就是十座城" in _download(client, log.task_uuid, "corrected")

    def test_text_is_trimmed_and_line_breaks_become_one_space(self, client, db_session):
        log = _correctable(db_session)

        client.patch(_url(log.task_uuid), json={"text": "  \n今天先看進度 \r\n\n 再討論。\t "})

        assert _segment(client, log.task_uuid)["text"] == "今天先看進度 再討論。"

    def test_other_line_separators_also_become_one_space(self, client, db_session):
        log = _correctable(db_session)

        client.patch(_url(log.task_uuid), json={"text": "第一句\u2028第二句\x85第三句\x0b\x0c第四句"})

        assert _segment(client, log.task_uuid)["text"] == "第一句 第二句 第三句 第四句"

    def test_sending_back_the_original_returns_to_it_even_if_it_was_not_normalized(self, client, db_session):
        # 回到原始轉錄是把原始轉錄用 PATCH 送回來：原始轉錄有換行、或說話者編號不是現在的寫法時，
        # 照原始轉錄存，才不會一直算成校正過
        log = _correctable(db_session, text=" 第一行\n第二行", speaker="S01")
        client.patch(_url(log.task_uuid), json={"text": "改過的", "speaker": "S1"})

        response = client.patch(_url(log.task_uuid), json={"text": " 第一行\n第二行", "speaker": "S01"})

        assert response.status_code == 200, response.text
        segment = response.json()["segment"]
        assert (segment["text"], segment["speaker"], segment["corrected"]) == (" 第一行\n第二行", "S01", False)
        # 送的是收成一行的樣子也一樣：內容和原始轉錄相同
        client.patch(_url(log.task_uuid), json={"text": "改過的"})
        assert client.patch(_url(log.task_uuid), json={"text": "第一行 第二行"}).json()["segment"]["corrected"] is False

    def test_text_is_stored_as_typed_without_traditional_output_conversion(self, client, db_session):
        log = _correctable(db_session)  # 來源語言 zh-TW：轉錄時會轉成繁體輸出

        client.patch(_url(log.task_uuid), json={"text": "软件开发"})

        assert _segment(client, log.task_uuid)["text"] == "软件开发"

    def test_word_timings_follow_the_corrected_text(self, client, db_session):
        # 本機的片段帶逐字時間：改過文字之後，讀到的與 PATCH 回的逐字時間都對得上校正後的文字，校正頁
        # 才標得出正在唸的字（#357 的重算）；沒改到的字沿用原本的時間
        chars = "這個就是實作層"
        words = [{"text": c, "start": 1.0 + i * 0.3, "end": 1.3 + i * 0.3} for i, c in enumerate(chars)]
        log = _correctable(db_session, start_sec=1.0, end_sec=3.1,
                           words_json=json.dumps(words, ensure_ascii=False))

        response = client.patch(_url(log.task_uuid), json={"text": "這個就是十座城喔"})

        patched = response.json()["segment"]["words"]
        assert patched == _segment(client, log.task_uuid)["words"]
        assert [w["text"] for w in patched] == list("這個就是十座城喔")
        assert patched[:4] == words[:4]
        # 刪掉的片段沒有逐字時間
        assert client.patch(_url(log.task_uuid), json={"text": ""}).json()["segment"]["words"] is None

    def test_empty_text_deletes_the_segment(self, client, db_session):
        log = _correctable(db_session)
        _create_segment(db_session, log.task_uuid, seg_key="0001", seq=1, start_sec=5.0,
                        end_sec=6.0, speaker="S1", text="留下來的")

        response = client.patch(_url(log.task_uuid), json={"text": " \n "})

        assert response.status_code == 200, response.text
        segment = _segment(client, log.task_uuid)
        assert (segment["text"], segment["deleted"], segment["original_text"]) == (
            "", True, "這個就是實作層")
        assert _download(client, log.task_uuid, "corrected") == "[S1] 留下來的"

    def test_restoring_a_deleted_segment_is_one_more_correction(self, client, db_session):
        log = _correctable(db_session)
        client.patch(_url(log.task_uuid), json={"text": ""})

        response = client.patch(_url(log.task_uuid), json={"text": "這個就是實作層"})

        segment = response.json()["segment"]
        assert (segment["deleted"], segment["corrected"], segment["has_correction_records"]) == (
            False, False, True)
        assert [(f, old, new) for f, old, new, _ in _records(db_session, log.task_uuid)] == [
            ("text", "這個就是實作層", ""), ("text", "", "這個就是實作層")]

    def test_a_deleted_segment_carries_the_text_it_had_before_it_was_deleted(self, client, db_session):
        # 校正頁的「還原」送回刪掉之前的文字（#348）：改過再刪掉的，還原成改過的文字，不是原始轉錄
        log = _correctable(db_session)
        client.patch(_url(log.task_uuid), json={"text": "這個就是十座城"})

        deleted = client.patch(_url(log.task_uuid), json={"text": ""}).json()["segment"]

        assert (deleted["deleted"], deleted["deleted_text"]) == (True, "這個就是十座城")
        assert _segment(client, log.task_uuid)["deleted_text"] == "這個就是十座城"
        restored = client.patch(_url(log.task_uuid), json={"text": deleted["deleted_text"]}).json()["segment"]
        assert (restored["text"], restored["deleted"], restored["deleted_text"]) == ("這個就是十座城", False, None)

    def test_undoing_a_restore_deletes_it_again_with_the_same_text_to_restore(self, client, db_session):
        log = _correctable(db_session)
        client.patch(_url(log.task_uuid), json={"text": ""})
        restore = client.patch(_url(log.task_uuid), json={"text": "這個就是實作層"}).json()

        undone = client.post(_undo_url(log.task_uuid, restore["operation_id"])).json()["segments"][0]

        assert (undone["deleted"], undone["deleted_text"]) == (True, "這個就是實作層")

    def test_only_segments_the_user_deleted_carry_deleted_text(self, client, db_session):
        log = _correctable(db_session)
        _create_segment(db_session, log.task_uuid, seg_key="0001", seq=1, start_sec=5.0, end_sec=6.0, text="")
        client.patch(_url(log.task_uuid), json={"text": "改過的"})

        assert _segment(client, log.task_uuid)["deleted_text"] is None
        # 原始轉錄就沒有文字的片段也算刪掉的片段（下載時略過），但不是使用者刪的，沒有可以還原的文字
        empty = _segment(client, log.task_uuid, "0001")
        assert (empty["deleted"], empty["deleted_text"]) == (True, None)

    def test_the_same_content_as_now_records_nothing(self, client, db_session):
        log = _correctable(db_session)

        response = client.patch(_url(log.task_uuid), json={"text": " 這個就是實作層\n", "speaker": "S0"})

        assert response.status_code == 200, response.text
        assert response.json()["operation_id"] is None
        assert response.json()["segment"]["has_correction_records"] is False
        assert _records(db_session, log.task_uuid) == []

    def test_transcript_text_is_not_written_to_the_log(self, client, db_session, app_log):
        log = _correctable(db_session)

        client.patch(_url(log.task_uuid), json={"text": "不能出現在日誌裡的校正"})
        client.patch(_url(log.task_uuid), json={"text": "日誌" * 3000})
        client.patch(_url(log.task_uuid, "9999"), json={"text": "不存在的片段的校正"})

        assert not [entry for entry in app_log if "校正" in entry or "日誌日誌" in entry]


class TestCorrectSpeaker:
    def test_corrected_speaker_is_read_back_and_the_original_stays(self, client, db_session):
        log = _correctable(db_session)

        response = client.patch(_url(log.task_uuid), json={"speaker": "S1"})

        segment = _segment(client, log.task_uuid)
        assert (segment["speaker"], segment["original_speaker"], segment["corrected"]) == ("S1", "S0", True)
        assert _records(db_session, log.task_uuid) == [("speaker", "S0", "S1", response.json()["operation_id"])]

    def test_a_speaker_not_yet_in_the_task_is_allowed(self, client, db_session):
        log = _correctable(db_session)

        assert client.patch(_url(log.task_uuid), json={"speaker": "S7"}).status_code == 200
        assert _segment(client, log.task_uuid)["speaker"] == "S7"

    def test_null_goes_back_to_no_speaker(self, client, db_session):
        log = _correctable(db_session, speaker=None)
        client.patch(_url(log.task_uuid), json={"speaker": "S2"})

        response = client.patch(_url(log.task_uuid), json={"speaker": None})

        segment = response.json()["segment"]
        assert (segment["speaker"], segment["corrected"]) == (None, False)

    def test_text_and_speaker_in_one_request_share_one_operation(self, client, db_session):
        log = _correctable(db_session)

        response = client.patch(_url(log.task_uuid), json={"text": "改過的文字", "speaker": "S3"})

        operation = response.json()["operation_id"]
        assert operation is not None
        assert _records(db_session, log.task_uuid) == [
            ("text", "這個就是實作層", "改過的文字", operation), ("speaker", "S0", "S3", operation)]


class TestReviewState:
    @pytest.mark.parametrize("state", ["verified", "flagged"])
    def test_review_state_is_written_on_the_segment_without_a_record(self, client, db_session, state):
        log = _correctable(db_session)

        response = client.patch(_url(log.task_uuid), json={"review_state": state})

        assert response.status_code == 200, response.text
        assert response.json()["operation_id"] is None
        segment = _segment(client, log.task_uuid)
        assert (segment["review_state"], segment["corrected"], segment["has_correction_records"]) == (
            state, False, False)
        assert _records(db_session, log.task_uuid) == []

    def test_null_clears_the_review_state(self, client, db_session):
        log = _correctable(db_session)
        client.patch(_url(log.task_uuid), json={"review_state": "flagged"})

        client.patch(_url(log.task_uuid), json={"review_state": None})

        assert _segment(client, log.task_uuid)["review_state"] is None

    def test_review_state_with_a_correction_in_one_request(self, client, db_session):
        log = _correctable(db_session)

        response = client.patch(_url(log.task_uuid), json={"text": "改過的文字", "review_state": "verified"})

        segment = response.json()["segment"]
        assert (segment["text"], segment["review_state"]) == ("改過的文字", "verified")
        assert [f for f, *_ in _records(db_session, log.task_uuid)] == ["text"]

    def test_a_correction_does_not_change_the_review_state(self, client, db_session):
        # 校正過的片段不會自動變成已確認（#25 故事 62），已確認的也不會因為校正而清掉
        log = _correctable(db_session)
        client.patch(_url(log.task_uuid), json={"review_state": "verified"})

        segment = client.patch(_url(log.task_uuid), json={"text": "改過的文字"}).json()["segment"]

        assert segment["review_state"] == "verified"


class TestUndo:
    def test_undo_goes_back_and_the_undo_can_be_undone(self, client, db_session):
        log = _correctable(db_session)
        edit = client.patch(_url(log.task_uuid), json={"text": "改過的文字", "speaker": "S1"}).json()

        undo = client.post(_undo_url(log.task_uuid, edit["operation_id"]))

        assert undo.status_code == 200, undo.text
        body = undo.json()
        assert (body["restored"], body["skipped"]) == (2, 0)
        assert body["operation_id"] not in (None, edit["operation_id"])
        assert body["segments"] == [_segment(client, log.task_uuid)]
        assert (body["segments"][0]["text"], body["segments"][0]["speaker"],
                body["segments"][0]["corrected"]) == ("這個就是實作層", "S0", False)

        redo = client.post(_undo_url(log.task_uuid, body["operation_id"])).json()

        assert (redo["restored"], redo["skipped"]) == (2, 0)
        assert (redo["segments"][0]["text"], redo["segments"][0]["speaker"]) == ("改過的文字", "S1")

    def test_a_segment_changed_again_afterwards_is_skipped(self, client, db_session):
        log = _correctable(db_session)
        first = client.patch(_url(log.task_uuid), json={"text": "第一次"}).json()["operation_id"]
        client.patch(_url(log.task_uuid), json={"text": "第二次"})

        body = client.post(_undo_url(log.task_uuid, first)).json()

        assert (body["restored"], body["skipped"], body["operation_id"]) == (0, 1, None)
        assert body["segments"][0]["text"] == "第二次"

    def test_undo_returns_only_the_segments_of_that_operation(self, client, db_session):
        log = _correctable(db_session)
        _create_segment(db_session, log.task_uuid, seg_key="0001", seq=1, start_sec=5.0, text="另一段")
        operation = client.patch(_url(log.task_uuid, "0001"), json={"text": ""}).json()["operation_id"]

        body = client.post(_undo_url(log.task_uuid, operation)).json()

        assert [(s["seg_key"], s["text"], s["deleted"]) for s in body["segments"]] == [
            ("0001", "另一段", False)]


# ─── 說話者（#354） ──────────────────────────────────────────────────────────

def _reassign_url(task_uuid) -> str:
    return f"/api/v1/transcripts/{task_uuid}/speakers/reassign"


def _settings_url(task_uuid) -> str:
    return f"/api/v1/transcripts/{task_uuid}"


def _speakers_task(db: Session, speakers) -> TranscriptionLog:
    """一個能校正的任務：片段 0000、0001…，說話者依序是 speakers（None 是沒有說話者），文字是「第 N 段」。"""
    log = _create_log(db)
    for i, speaker in enumerate(speakers):
        _create_segment(db, log.task_uuid, seg_key=f"{i:04d}", seq=i, start_sec=i * 5.0,
                        end_sec=i * 5.0 + 3.0, speaker=speaker, text=f"第 {i} 段")
    return log


def _speakers(client: TestClient, task_uuid) -> list:
    """每個片段的 (校正後的說話者, 原始轉錄的說話者)，依片段的順序。"""
    segments = client.get(f"/api/v1/transcripts/{task_uuid}").json()["segments"]
    return [(s["speaker"], s["original_speaker"]) for s in segments]


def _next_speaker(client: TestClient, task_uuid) -> str:
    return client.get(f"/api/v1/transcripts/{task_uuid}").json()["next_speaker"]


class TestReassignSpeaker:
    """把這位說話者全部換成另一位（#354 第 2 點）：每個片段各記一筆，共用一個操作編號，可以整批復原。"""

    def test_all_segments_of_a_speaker_move_in_one_operation_and_one_undo_brings_them_back(
            self, client, db_session):
        # 模型把主持人分成 S0 和 S3：把 S3 全部換成 S0
        log = _speakers_task(db_session, ["S0", "S3", "S1", "S3"])
        original_download = _download(client, log.task_uuid, "original")

        response = client.post(_reassign_url(log.task_uuid), json={"from_speaker": "S3", "to_speaker": "S0"})

        assert response.status_code == 200, response.text
        body = response.json()
        operation = body["operation_id"]
        assert body["changed"] == 2
        assert [(s["seg_key"], s["speaker"], s["original_speaker"]) for s in body["segments"]] == [
            ("0001", "S0", "S3"), ("0003", "S0", "S3")]
        assert _speakers(client, log.task_uuid) == [("S0", "S0"), ("S0", "S3"), ("S1", "S1"), ("S0", "S3")]
        assert _records(db_session, log.task_uuid) == [("speaker", "S3", "S0", operation)] * 2
        # 原始轉錄不變
        assert _download(client, log.task_uuid, "original") == original_download

        undo = client.post(_undo_url(log.task_uuid, operation)).json()

        assert (undo["restored"], undo["skipped"]) == (2, 0)
        assert _speakers(client, log.task_uuid) == [("S0", "S0"), ("S3", "S3"), ("S1", "S1"), ("S3", "S3")]
        assert _download(client, log.task_uuid, "corrected") == original_download

    def test_it_goes_by_the_corrected_speaker(self, client, db_session):
        log = _speakers_task(db_session, ["S0", "S1", "S1"])
        client.patch(_url(log.task_uuid, "0001"), json={"speaker": "S2"})

        body = client.post(_reassign_url(log.task_uuid), json={"from_speaker": "S1", "to_speaker": "S0"}).json()

        assert body["changed"] == 1
        assert _speakers(client, log.task_uuid) == [("S0", "S0"), ("S2", "S1"), ("S0", "S1")]

    def test_segments_without_a_speaker_can_all_be_given_to_one(self, client, db_session):
        # Gemini 當初沒有分說話者的任務：沒有說話者的片段一次全部指定給某一位
        log = _speakers_task(db_session, [None, "S0", None])

        body = client.post(_reassign_url(log.task_uuid), json={"from_speaker": None, "to_speaker": "S1"}).json()

        assert body["changed"] == 2
        assert _speakers(client, log.task_uuid) == [("S1", None), ("S0", "S0"), ("S1", None)]
        assert [r[1:3] for r in _records(db_session, log.task_uuid)] == [(None, "S1")] * 2

    def test_deleted_segments_move_too_and_come_back_with_the_new_speaker(self, client, db_session):
        log = _speakers_task(db_session, ["S3", "S3"])
        client.patch(_url(log.task_uuid, "0001"), json={"text": ""})

        body = client.post(_reassign_url(log.task_uuid), json={"from_speaker": "S3", "to_speaker": "S0"}).json()

        assert body["changed"] == 2
        restored = client.patch(_url(log.task_uuid, "0001"), json={"text": "第 1 段"}).json()["segment"]
        assert (restored["speaker"], restored["deleted"]) == ("S0", False)

    def test_nothing_to_move_records_nothing(self, client, db_session):
        log = _speakers_task(db_session, ["S0", "S1"])

        for request in ({"from_speaker": "S5", "to_speaker": "S0"}, {"from_speaker": "S1", "to_speaker": "S1"}):
            body = client.post(_reassign_url(log.task_uuid), json=request).json()
            assert (body["changed"], body["operation_id"], body["segments"]) == (0, None, [])
        assert _records(db_session, log.task_uuid) == []


class TestNewSpeaker:
    """新的說話者（#354 第 1 點）：編號取這個任務還沒用過的下一個號碼，讀取端點回 ``next_speaker``。"""

    def test_the_next_number_after_every_speaker_in_the_task(self, client, db_session):
        log = _speakers_task(db_session, ["S0", "S2", None])

        assert _next_speaker(client, log.task_uuid) == "S3"

    def test_a_task_without_speakers_starts_at_s0(self, client, db_session):
        log = _speakers_task(db_session, [None, None])

        assert _next_speaker(client, log.task_uuid) == "S0"

    def test_splitting_two_guests_the_model_merged_into_one_speaker(self, client, db_session):
        log = _speakers_task(db_session, ["S0", "S1", "S1"])
        new = _next_speaker(client, log.task_uuid)

        response = client.patch(_url(log.task_uuid, "0002"), json={"speaker": new})

        assert response.status_code == 200, response.text
        assert new == "S2"
        assert _speakers(client, log.task_uuid) == [("S0", "S0"), ("S1", "S1"), ("S2", "S1")]
        assert _next_speaker(client, log.task_uuid) == "S3"

    def test_a_number_that_was_ever_used_is_not_given_again(self, client, db_session):
        # S2 全部換成 S1 之後沒有片段了，但原始轉錄與校正紀錄裡的 S2 是另一個人
        log = _speakers_task(db_session, ["S0", "S1", "S2"])
        client.post(_reassign_url(log.task_uuid), json={"from_speaker": "S2", "to_speaker": "S1"})
        assert _next_speaker(client, log.task_uuid) == "S3"

        # 指定過又復原的新的說話者也算用過
        operation = client.patch(_url(log.task_uuid, "0000"), json={"speaker": "S3"}).json()["operation_id"]
        client.post(_undo_url(log.task_uuid, operation))
        assert _next_speaker(client, log.task_uuid) == "S4"

    def test_a_number_that_has_a_speaker_name_is_not_given_again(self, client, db_session):
        # 說話者名稱以說話者編號為對象（#359）：新的說話者不能接手別人的名稱。名稱還沒有寫入的端點，直接用 repository 寫
        from app.repositories.correction_repository import Correction, CorrectionField, CorrectionRepository

        log = _speakers_task(db_session, ["S0"])
        CorrectionRepository.record_operation(
            db_session, log.task_uuid, [Correction("S4", CorrectionField.SPEAKER_NAME, "王小明")])

        assert _next_speaker(client, log.task_uuid) == "S5"


class TestSingleSpeaker:
    """「整份當成同一位說話者」與「照模型分出的說話者顯示」的切換（#354 第 3 點）：改的是任務的設定，不算校正，
    不留校正紀錄，也不重新轉錄。說話者人數（#352）合併之前，寫的是任務紀錄的 Multi-Speaker 開關。"""

    def _single(self, client, task_uuid) -> bool:
        return client.get(f"/api/v1/transcripts/{task_uuid}").json()["single_speaker"]

    def test_switching_changes_the_speaker_labels_in_downloads_and_leaves_segments_and_records(
            self, client, db_session):
        log = _speakers_task(db_session, ["S0", "S1"])
        client.patch(_url(log.task_uuid, "0000"), json={"text": "改過的第 0 段"})
        segments = client.get(f"/api/v1/transcripts/{log.task_uuid}").json()["segments"]
        records = _records(db_session, log.task_uuid)
        assert self._single(client, log.task_uuid) is False
        assert _download(client, log.task_uuid, "corrected") == "[S0] 改過的第 0 段\n[S1] 第 1 段"

        response = client.patch(_settings_url(log.task_uuid), json={"single_speaker": True})

        assert response.status_code == 200, response.text
        assert response.json() == {"single_speaker": True}
        assert self._single(client, log.task_uuid) is True
        assert _download(client, log.task_uuid, "corrected") == "改過的第 0 段\n第 1 段"
        assert _download(client, log.task_uuid, "original") == "第 0 段\n第 1 段"
        assert client.get(f"/api/v1/transcripts/{log.task_uuid}").json()["segments"] == segments
        assert _records(db_session, log.task_uuid) == records

        client.patch(_settings_url(log.task_uuid), json={"single_speaker": False})

        assert self._single(client, log.task_uuid) is False
        assert _download(client, log.task_uuid, "corrected") == "[S0] 改過的第 0 段\n[S1] 第 1 段"
        assert client.get(f"/api/v1/transcripts/{log.task_uuid}").json()["segments"] == segments
        assert _records(db_session, log.task_uuid) == records

    def test_an_old_task_with_multi_speaker_off_can_switch_to_the_speakers_the_model_found(
            self, client, db_session):
        # 人數做出來之前、Multi-Speaker 開關關著的任務：本機照樣存了模型分出的說話者編號
        log = _speakers_task(db_session, ["S0", "S1"])
        log.multi_speaker = False
        db_session.commit()
        assert self._single(client, log.task_uuid) is True
        assert _download(client, log.task_uuid, "corrected") == "第 0 段\n第 1 段"

        client.patch(_settings_url(log.task_uuid), json={"single_speaker": False})

        assert self._single(client, log.task_uuid) is False
        assert _download(client, log.task_uuid, "corrected") == "[S0] 第 0 段\n[S1] 第 1 段"


class TestRefusedSpeakerWrites:
    """說話者的寫入照校正的規則擋：任務要能校正，編號的格式要對；擋下時什麼都不寫。"""

    def test_task_not_completed(self, client, db_session):
        log = _speakers_task(db_session, ["S0", "S1"])
        log.status = "PROCESSING"
        db_session.commit()

        reassign = client.post(_reassign_url(log.task_uuid), json={"from_speaker": "S1", "to_speaker": "S0"})
        switch = client.patch(_settings_url(log.task_uuid), json={"single_speaker": True})

        assert (reassign.status_code, switch.status_code) == (409, 409)
        assert "還沒完成" in reassign.json()["detail"]
        assert _records(db_session, log.task_uuid) == []
        db_session.expire_all()
        assert log.multi_speaker is None

    def test_unknown_task(self, client):
        assert client.post(_reassign_url(uuid.uuid4()), json={"from_speaker": "S1", "to_speaker": "S0"}
                           ).status_code == 404
        assert client.patch(_settings_url(uuid.uuid4()), json={"single_speaker": True}).status_code == 404

    @pytest.mark.parametrize("speaker", ["s1", "S01", "Speaker 1", "", None])
    def test_malformed_target_speaker(self, client, db_session, speaker):
        log = _speakers_task(db_session, ["S0", "S1"])

        response = client.post(_reassign_url(log.task_uuid), json={"from_speaker": "S1", "to_speaker": speaker})

        assert response.status_code == 400, response.text
        assert "說話者" in response.json()["detail"]
        assert _records(db_session, log.task_uuid) == []

    @pytest.mark.parametrize("body", [{"to_speaker": "S0"}, {"from_speaker": "S1", "to_speaker": "S0", "x": 1}])
    def test_the_source_speaker_must_be_given_and_nothing_else(self, client, db_session, body):
        # 少了 from_speaker 不能當成「沒有說話者的片段」：那會把它們全部換掉
        log = _speakers_task(db_session, ["S0", None])

        assert client.post(_reassign_url(log.task_uuid), json=body).status_code == 422
        assert _records(db_session, log.task_uuid) == []

    @pytest.mark.parametrize("body", [{}, {"single_speaker": "yes"}, {"single_speaker": 1}, {"single_speaker": None}])
    def test_the_switch_takes_only_true_or_false(self, client, db_session, body):
        log = _speakers_task(db_session, ["S0", "S1"])

        assert client.patch(_settings_url(log.task_uuid), json=body).status_code == 422
        db_session.expire_all()
        assert log.multi_speaker is None


class TestRefusedWrites:
    """不能寫的請求回一句說明，什麼都不寫。"""

    @pytest.fixture
    def log(self, db_session):
        return _correctable(db_session)

    def _refused(self, response, status: int, db: Session, task_uuid) -> str:
        assert response.status_code == status, response.text
        assert _records(db, task_uuid) == []
        detail = response.json()["detail"]
        assert isinstance(detail, str) and detail
        return detail

    def test_unknown_task(self, client):
        assert client.patch(_url(uuid.uuid4()), json={"text": "A"}).status_code == 404
        assert client.post(_undo_url(uuid.uuid4(), uuid.uuid4())).status_code == 404

    def test_malformed_task_id(self, client):
        assert client.patch(_url("not-a-uuid"), json={"text": "A"}).status_code == 400
        assert client.post(_undo_url("not-a-uuid", uuid.uuid4())).status_code == 400

    @pytest.mark.parametrize("status", ["PROCESSING", "FAILED", "CANCELLED"])
    def test_task_not_completed(self, client, db_session, status):
        log = _correctable(db_session)
        log.status = status
        db_session.commit()

        detail = self._refused(client.patch(_url(log.task_uuid), json={"text": "A"}), 409,
                               db_session, log.task_uuid)
        assert "還沒完成" in detail
        assert client.post(_undo_url(log.task_uuid, uuid.uuid4())).status_code == 409

    def test_task_without_segments(self, client, db_session):
        log = _create_log(db_session)

        detail = self._refused(client.patch(_url(log.task_uuid), json={"review_state": "verified"}),
                               409, db_session, log.task_uuid)
        assert "片段" in detail

    def test_task_with_translation(self, client, db_session):
        log = _create_log(db_session, source_language="ja-JP", target_language="zh-TW")
        _create_segment(db_session, log.task_uuid)

        detail = self._refused(client.patch(_url(log.task_uuid), json={"text": "A"}), 409,
                               db_session, log.task_uuid)
        assert "翻譯" in detail
        assert client.post(_undo_url(log.task_uuid, uuid.uuid4())).status_code == 409

    @pytest.mark.parametrize("body", [{"text": "A"}, {"review_state": "verified"}])
    def test_unknown_segment(self, client, db_session, log, body):
        self._refused(client.patch(_url(log.task_uuid, "9999"), json=body), 404, db_session, log.task_uuid)

    @pytest.mark.parametrize("speaker", ["s1", "S", "S01", "S1000", "Speaker 1", "", "S-1", " S1"])
    def test_malformed_speaker(self, client, db_session, log, speaker):
        detail = self._refused(client.patch(_url(log.task_uuid), json={"speaker": speaker}), 400,
                               db_session, log.task_uuid)
        assert "說話者" in detail

    def test_text_too_long(self, client, db_session, log):
        detail = self._refused(client.patch(_url(log.task_uuid), json={"text": "字" * 5001}), 400,
                               db_session, log.task_uuid)
        assert "5000" in detail
        # 上限算的是去掉前後的空白之後的字數
        assert client.patch(_url(log.task_uuid), json={"text": " " + "字" * 5000 + "\n"}).status_code == 200

    @pytest.mark.parametrize("state", ["done", "VERIFIED", ""])
    def test_unknown_review_state(self, client, db_session, log, state):
        self._refused(client.patch(_url(log.task_uuid), json={"review_state": state}), 400,
                      db_session, log.task_uuid)

    @pytest.mark.parametrize("body", [{}, {"text": None}])
    def test_nothing_to_change(self, client, db_session, log, body):
        self._refused(client.patch(_url(log.task_uuid), json=body), 400, db_session, log.task_uuid)

    def test_a_bad_field_refuses_the_whole_request(self, client, db_session, log):
        self._refused(client.patch(_url(log.task_uuid), json={"text": "A", "speaker": "B", "review_state": "verified"}),
                      400, db_session, log.task_uuid)
        assert _segment(client, log.task_uuid)["review_state"] is None

    def test_an_operation_of_another_task(self, client, db_session, log):
        other = _correctable(db_session)
        operation = client.patch(_url(other.task_uuid), json={"text": "A"}).json()["operation_id"]

        response = client.post(_undo_url(log.task_uuid, operation))

        assert response.status_code == 404
        assert _segment(client, other.task_uuid)["text"] == "A"

    def test_an_unknown_or_malformed_operation(self, client, log):
        assert client.post(_undo_url(log.task_uuid, uuid.uuid4())).status_code == 404
        assert client.post(_undo_url(log.task_uuid, "not-an-operation")).status_code == 400


# ─── 保留天數從校正起算（#350） ───────────────────────────────────────────────

class TestAudioRetention:
    """寫入校正或確認狀態時，這個任務的保留音檔的保留天數從現在重新起算：啟動時的清除照舊只看檔案的
    修改時間，所以寫入時把修改時間更新成現在。放著不動的任務照樣過期。"""

    @pytest.fixture
    def store(self, uploads) -> Path:
        """保留區（測試的暫存資料夾裡）。"""
        store = audio_store.store_path()
        store.mkdir(parents=True, exist_ok=True)
        return store

    @staticmethod
    def _age(path: Path) -> None:
        """修改時間改成保留天數再多一天以前：下次清除就會刪掉。"""
        aged = time.time() - (get_settings().audio_retention_days + 1) * 86400
        os.utime(path, (aged, aged))

    def _with_old_audio(self, db: Session, store: Path) -> Tuple[TranscriptionLog, Path]:
        """一個能校正的任務，保留音檔已經超過保留天數。"""
        log = _correctable(db)
        path = store / f"{log.task_uuid}.m4a"
        path.write_bytes(b"audio")
        self._age(path)
        log.audio_filename = path.name
        db.commit()
        return log, path

    def test_a_corrected_task_keeps_its_audio_and_an_untouched_one_expires(self, client, db_session, store):
        corrected, corrected_audio = self._with_old_audio(db_session, store)
        untouched, untouched_audio = self._with_old_audio(db_session, store)

        assert client.patch(_url(corrected.task_uuid), json={"text": "改過的文字"}).status_code == 200
        audio_store.purge_expired()

        assert corrected_audio.exists()
        assert not untouched_audio.exists()
        assert client.get(f"/api/v1/transcripts/{corrected.task_uuid}/audio").status_code == 200
        assert client.get(f"/api/v1/transcripts/{untouched.task_uuid}/audio").status_code == 404

    def test_only_marking_a_review_state_also_restarts_the_count(self, client, db_session, store):
        log, audio = self._with_old_audio(db_session, store)

        assert client.patch(_url(log.task_uuid), json={"review_state": "flagged"}).status_code == 200
        audio_store.purge_expired()

        assert audio.exists()

    def test_an_undo_also_restarts_the_count(self, client, db_session, store):
        log, audio = self._with_old_audio(db_session, store)
        operation = client.patch(_url(log.task_uuid), json={"text": "改過的文字"}).json()["operation_id"]
        self._age(audio)

        assert client.post(_undo_url(log.task_uuid, operation)).status_code == 200
        audio_store.purge_expired()

        assert audio.exists()

    def test_a_write_that_changes_nothing_does_not_restart_the_count(self, client, db_session, store):
        # 和現在的內容相同的校正不記校正紀錄，不算一次校正（GLOSSARY）：只是點進去又離開，不延長保留
        log, audio = self._with_old_audio(db_session, store)

        response = client.patch(_url(log.task_uuid), json={"text": "這個就是實作層"})
        assert (response.status_code, response.json()["operation_id"]) == (200, None)
        audio_store.purge_expired()

        assert not audio.exists()

    def test_a_refused_write_does_not_restart_the_count(self, client, db_session, store):
        log, audio = self._with_old_audio(db_session, store)

        assert client.patch(_url(log.task_uuid), json={"speaker": "主持人"}).status_code == 400
        audio_store.purge_expired()

        assert not audio.exists()

    def test_a_task_whose_audio_is_gone_can_still_be_corrected(self, client, db_session, store):
        log, audio = self._with_old_audio(db_session, store)
        audio.unlink()

        response = client.patch(_url(log.task_uuid), json={"text": "改過的文字"})

        assert response.status_code == 200, response.text
        assert _segment(client, log.task_uuid)["text"] == "改過的文字"
        # 不在的保留音檔不會因為更新修改時間而多出一個空檔
        assert list(store.iterdir()) == []

    def test_a_failed_update_is_logged_and_the_correction_is_still_saved(
            self, client, db_session, store, monkeypatch, app_log):
        log, audio = self._with_old_audio(db_session, store)
        aged_mtime = audio.stat().st_mtime

        def utime(*_args, **_kwargs):
            raise PermissionError("拒絕存取")

        monkeypatch.setattr(os, "utime", utime)

        response = client.patch(_url(log.task_uuid), json={"text": "改過的文字"})

        assert response.status_code == 200, response.text
        assert _segment(client, log.task_uuid)["text"] == "改過的文字"
        assert audio.stat().st_mtime == aged_mtime
        failures = [entry for entry in app_log if "保留天數" in entry]
        assert len(failures) == 1
        # 日誌只寫保留音檔的檔名（task_uuid），不寫轉錄的文字
        assert audio.name in failures[0]
        assert not any("改過的文字" in entry for entry in app_log)
