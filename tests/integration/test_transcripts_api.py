"""整合測試：校正介面用的轉錄文件 API

測試範圍：
  GET    /api/v1/transcripts/{task_uuid}
  GET    /api/v1/transcripts/{task_uuid}/audio
  DELETE /api/v1/history/{task_uuid} 連帶刪除片段
"""
import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database.models import TranscriptionLog, TranscriptSegment


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
