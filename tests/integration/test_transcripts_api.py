"""整合測試：校正介面用的轉錄文件 API

測試範圍：
  GET    /api/v1/transcripts/{task_uuid}（片段是校正後版本，另外帶著原始轉錄，#341）
  GET    /api/v1/transcripts/{task_uuid}/audio
  PATCH  /api/v1/transcripts/{task_uuid}/segments/{seg_key}（改文字、說話者、確認狀態，#341）
  POST   /api/v1/transcripts/{task_uuid}/operations/{operation_id}/undo（復原一次操作，#341）
  DELETE /api/v1/history/{task_uuid} 連帶刪除片段

校正的結果從讀取端點與 ``version=original`` 的下載驗（#25 的測試決策）；校正紀錄的筆數與操作編號
還沒有讀的端點（#355），直接查資料表。
"""
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.api.transcripts  # noqa: F401  app_log 只接得到 fixture 啟動前已經建立的 logger
from app.database.models import CorrectionRecord, TranscriptionLog, TranscriptSegment


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
