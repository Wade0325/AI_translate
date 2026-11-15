"""整合測試：校正的歷程（#355）

測試範圍：
  GET  /api/v1/transcripts/{task_uuid}/segments/{seg_key}/correction-records（一個片段的校正紀錄）
  回到某一版：把那一版的內容用 PATCH /api/v1/transcripts/{task_uuid}/segments/{seg_key} 送出（#341）
  整批復原：POST /api/v1/transcripts/{task_uuid}/operations/{operation_id}/undo（#341）

全部從 HTTP API 驗（#25 的測試決策）。一次改很多個片段的操作（全部取代 #356、把這位說話者全部換成另一位
#354）的端點還沒有合併，這裡直接用 repository 記一次改了 5 個片段的操作，形狀和那兩個端點寫的相同：
同一個操作編號，每個改到的片段各記一筆。
"""
import uuid
from typing import List, Optional

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database.models import TranscriptionLog, TranscriptSegment
from app.repositories.correction_repository import Correction, CorrectionField, CorrectionRepository


def _task(db: Session, texts: List[str]) -> TranscriptionLog:
    """一個能校正的任務：片段 0000、0001…，說話者 S0，文字照 texts。"""
    log = TranscriptionLog(task_uuid=uuid.uuid4(), status="COMPLETED", original_filename="meeting.m4a",
                           audio_duration_seconds=60.0, model_used="moss-align", provider="Local",
                           source_language="zh-TW")
    db.add(log)
    for seq, text in enumerate(texts):
        db.add(TranscriptSegment(task_uuid=log.task_uuid, seg_key=f"{seq:04d}", seq=seq,
                                 start_sec=seq * 5.0, end_sec=seq * 5.0 + 4.0, speaker="S0", text=text,
                                 source="aligned"))
    db.commit()
    return log


def _patch(client: TestClient, task_uuid, seg_key: str, **body) -> Optional[str]:
    """改一個片段，回這次的操作編號。"""
    response = client.patch(f"/api/v1/transcripts/{task_uuid}/segments/{seg_key}", json=body)
    assert response.status_code == 200, response.text
    return response.json()["operation_id"]


def _history(client: TestClient, task_uuid, seg_key: str = "0000") -> dict:
    response = client.get(f"/api/v1/transcripts/{task_uuid}/segments/{seg_key}/correction-records")
    assert response.status_code == 200, response.text
    return response.json()


def _changes(history: dict) -> list:
    """(改了什麼, 改前, 改後)，依編號排序。"""
    return [(r["field"], r["old_value"], r["new_value"]) for r in history["records"]]


def _segment(client: TestClient, task_uuid, seg_key: str = "0000") -> dict:
    segments = client.get(f"/api/v1/transcripts/{task_uuid}").json()["segments"]
    return next(s for s in segments if s["seg_key"] == seg_key)


class TestSegmentHistory:
    def test_three_text_corrections_then_back_to_the_first(self, client, db_session):
        log = _task(db_session, ["這個就是實作層"])
        for text in ("第一版", "第二版", "第三版"):
            _patch(client, log.task_uuid, "0000", text=text)

        history = _history(client, log.task_uuid)

        assert (history["seg_key"], history["original_text"], history["original_speaker"]) == (
            "0000", "這個就是實作層", "S0")
        assert _changes(history) == [
            ("text", "這個就是實作層", "第一版"), ("text", "第一版", "第二版"), ("text", "第二版", "第三版")]
        # 回到第一版：把那一版的內容當成一次普通的校正送出
        first = history["records"][0]
        _patch(client, log.task_uuid, "0000", text=first["new_value"])

        assert _segment(client, log.task_uuid)["text"] == "第一版"
        after = _history(client, log.task_uuid)
        # 之前的每一筆都留著，所以回去之後還能再回來
        assert _changes(after) == _changes(history) + [("text", "第三版", "第一版")]

    def test_back_to_the_original_reverts_text_and_speaker_in_one_operation(self, client, db_session):
        log = _task(db_session, ["這個就是實作層"])
        _patch(client, log.task_uuid, "0000", text="這個就是十座城")
        _patch(client, log.task_uuid, "0000", speaker="S1")
        history = _history(client, log.task_uuid)

        # 回到原始轉錄：文字與說話者都回去，同一個請求
        _patch(client, log.task_uuid, "0000", text=history["original_text"], speaker=history["original_speaker"])

        segment = _segment(client, log.task_uuid)
        assert (segment["text"], segment["speaker"], segment["corrected"]) == ("這個就是實作層", "S0", False)
        records = _history(client, log.task_uuid)["records"]
        assert [(r["field"], r["old_value"], r["new_value"]) for r in records[2:]] == [
            ("text", "這個就是十座城", "這個就是實作層"), ("speaker", "S1", "S0")]
        assert records[2]["operation_id"] == records[3]["operation_id"]
        assert records[1]["operation_id"] != records[2]["operation_id"]

    def test_each_record_says_when_and_how_big_its_operation_was(self, client, db_session):
        log = _task(db_session, ["這個就是實作層"])
        single = _patch(client, log.task_uuid, "0000", text="這個就是十座城")
        both = _patch(client, log.task_uuid, "0000", text="實作層", speaker="S2")

        records = _history(client, log.task_uuid)["records"]

        assert [r["operation_id"] for r in records] == [single, both, both]
        # 一共有幾筆，以及改到幾個片段：回到原始轉錄這類一個片段的兩筆不是整批操作
        assert [(r["operation_record_count"], r["operation_segment_count"]) for r in records] == [
            (1, 1), (2, 1), (2, 1)]
        assert [r["id"] for r in records] == sorted(r["id"] for r in records)
        assert all(r["created_at"] for r in records)

    def test_a_segment_without_corrections_has_only_its_original(self, client, db_session):
        log = _task(db_session, ["這個就是實作層"])

        history = _history(client, log.task_uuid)

        assert history["records"] == []
        assert history["original_text"] == "這個就是實作層"

    def test_other_segments_speaker_names_and_review_states_are_not_listed(self, client, db_session):
        log = _task(db_session, ["第一段", "第二段"])
        _patch(client, log.task_uuid, "0001", text="別的片段")
        _patch(client, log.task_uuid, "0000", review_state="verified")
        # 說話者名稱的對象是說話者，不是片段（#359 的端點還沒有合併，直接記）
        CorrectionRepository.record_operation(
            db_session, log.task_uuid, [Correction("S0", CorrectionField.SPEAKER_NAME, "王小明")])

        assert _history(client, log.task_uuid, "0000")["records"] == []
        assert _changes(_history(client, log.task_uuid, "0001")) == [("text", "第二段", "別的片段")]

    def test_deleting_and_restoring_are_records_too(self, client, db_session):
        log = _task(db_session, ["這個就是實作層"])
        _patch(client, log.task_uuid, "0000", text="")
        _patch(client, log.task_uuid, "0000", text="這個就是實作層")

        assert _changes(_history(client, log.task_uuid)) == [
            ("text", "這個就是實作層", ""), ("text", "", "這個就是實作層")]


class TestBulkUndo:
    def test_restores_the_untouched_segments_and_skips_the_one_changed_afterwards(self, client, db_session):
        texts = ["今天看進度", "進度落後", "進度表", "下次看進度", "進度會議"]
        log = _task(db_session, texts)
        # 全部取代「進度」→「進展」：一次操作，5 個片段各記一筆
        replace_all = CorrectionRepository.record_operation(db_session, log.task_uuid, [
            Correction(f"{i:04d}", CorrectionField.TEXT, text.replace("進度", "進展"))
            for i, text in enumerate(texts)])
        records = _history(client, log.task_uuid, "0002")["records"]
        assert [(r["operation_id"], r["operation_record_count"], r["operation_segment_count"])
                for r in records] == [(str(replace_all), 5, 5)]
        # 之後手動再改其中 1 個
        _patch(client, log.task_uuid, "0002", text="進展表（修訂）")

        response = client.post(f"/api/v1/transcripts/{log.task_uuid}/operations/{replace_all}/undo")

        assert response.status_code == 200, response.text
        undo = response.json()
        assert (undo["restored"], undo["skipped"]) == (4, 1)
        assert [s["text"] for s in undo["segments"]] == [
            "今天看進度", "進度落後", "進展表（修訂）", "下次看進度", "進度會議"]
        segments = client.get(f"/api/v1/transcripts/{log.task_uuid}").json()["segments"]
        assert [s["text"] for s in segments] == [s["text"] for s in undo["segments"]]
        # 整批復原本身也是一次操作：還原的 4 個片段各多一筆，共用新的操作編號，歷程也看得到
        restored = _history(client, log.task_uuid, "0000")["records"][-1]
        assert (restored["operation_id"], restored["operation_record_count"],
                restored["operation_segment_count"]) == (undo["operation_id"], 4, 4)
        assert _changes(_history(client, log.task_uuid, "0002"))[-1] == ("text", "進展表", "進展表（修訂）")


class TestRefused:
    def test_unknown_task(self, client):
        assert client.get(f"/api/v1/transcripts/{uuid.uuid4()}/segments/0000/correction-records").status_code == 404

    def test_malformed_task_id(self, client):
        assert client.get("/api/v1/transcripts/not-a-uuid/segments/0000/correction-records").status_code == 400

    def test_unknown_segment(self, client, db_session):
        log = _task(db_session, ["第一段"])

        response = client.get(f"/api/v1/transcripts/{log.task_uuid}/segments/9999/correction-records")

        assert response.status_code == 404
        assert response.json()["detail"] == "找不到此片段"
