"""整合測試：校正紀錄的 repository（#340，ADR 0011）

片段存的是原始轉錄，寫入後不再改；每一次校正另存一筆校正紀錄，只增不改；校正後版本由原始轉錄
套上最新的校正紀錄算出來。這裡在 repository 這一層測（#25 的測試決策），用 SQLite 測試資料庫
（tests/conftest.py 的 test_engine）。
"""
import threading
import time
import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import CorrectionRecord, TranscriptionLog, TranscriptSegment
from app.repositories.correction_repository import (
    Correction,
    CorrectionField,
    CorrectionRepository,
)
from app.repositories.transcript_segment_repository import TranscriptSegmentRepository
from app.services import output_format
from app.services.transcription.models import TranscriptionTaskResult
from tests.support.db_faults import writes_fail

TEXT = CorrectionField.TEXT
SPEAKER = CorrectionField.SPEAKER
SPEAKER_NAME = CorrectionField.SPEAKER_NAME

ORIGINAL = [
    {"seg_key": "0-0", "start": 1.0, "end": 2.5, "speaker": "S0", "text": "今日は晴れです。"},
    {"seg_key": "0-1", "start": 3.0, "end": 4.0, "speaker": "S1", "text": "そうですね。"},
    {"seg_key": "0-2", "start": 5.0, "end": 6.0, "speaker": "S0", "text": "散歩しましょう。"},
]


@pytest.fixture
def task(db_session: Session) -> uuid.UUID:
    """一個完成的任務，片段是 ORIGINAL。"""
    task_uuid = uuid.uuid4()
    db_session.add(TranscriptionLog(task_uuid=task_uuid, status="COMPLETED",
                                    original_filename="meeting.m4a"))
    for seq, seg in enumerate(ORIGINAL):
        db_session.add(TranscriptSegment(
            task_uuid=task_uuid, seg_key=seg["seg_key"], seq=seq, start_sec=seg["start"],
            end_sec=seg["end"], speaker=seg["speaker"], text=seg["text"], source="aligned"))
    db_session.commit()
    return task_uuid


def _record(db: Session, task_uuid, *changes):
    return CorrectionRepository.record_operation(
        db, task_uuid, [Correction(target, field, value) for target, field, value in changes])


def _corrected(db: Session, task_uuid) -> dict:
    return {seg["seg_key"]: seg for seg in CorrectionRepository.corrected_version(db, task_uuid)}


def _segment_row(db: Session, task_uuid, seg_key) -> TranscriptSegment:
    db.expire_all()
    return db.query(TranscriptSegment).filter_by(task_uuid=task_uuid, seg_key=seg_key).one()


def _texts(db: Session, task_uuid) -> list:
    return [seg["text"] for seg in CorrectionRepository.corrected_version(db, task_uuid)]


def _one_segment_task(db: Session, text="別の任務", speaker=None) -> uuid.UUID:
    """另一個任務，只有一個片段 0-0。"""
    task_uuid = uuid.uuid4()
    db.add(TranscriptionLog(task_uuid=task_uuid, status="COMPLETED"))
    db.add(TranscriptSegment(task_uuid=task_uuid, seg_key="0-0", seq=0, start_sec=0.0, text=text,
                             speaker=speaker))
    db.commit()
    return task_uuid


def _other_task_with_a_record(db: Session):
    """另一個任務，它的片段改過一次文字；回傳 (任務 id, 那次的操作編號)。"""
    other = _one_segment_task(db)
    return other, _record(db, other, ("0-0", TEXT, "A"))


class TestText:
    def test_second_text_correction_wins_and_the_original_stays(self, db_session, task):
        _record(db_session, task, ("0-0", TEXT, "今日は曇りです。"))
        _record(db_session, task, ("0-0", TEXT, "今日は雨です。"))

        assert _corrected(db_session, task)["0-0"]["text"] == "今日は雨です。"
        assert _segment_row(db_session, task, "0-0").text == "今日は晴れです。"
        records = CorrectionRepository.records_for_segment(db_session, task, "0-0")
        assert [(r.field, r.old_value, r.new_value) for r in records] == [
            ("text", "今日は晴れです。", "今日は曇りです。"),
            ("text", "今日は曇りです。", "今日は雨です。"),
        ]

    def test_text_and_speaker_corrections_do_not_affect_each_other(self, db_session, task):
        _record(db_session, task, ("0-0", TEXT, "今日は曇りです。"))
        _record(db_session, task, ("0-0", SPEAKER, "S1"))
        _record(db_session, task, ("0-1", SPEAKER, "S0"))

        version = _corrected(db_session, task)
        assert (version["0-0"]["text"], version["0-0"]["speaker"]) == ("今日は曇りです。", "S1")
        assert (version["0-1"]["text"], version["0-1"]["speaker"]) == ("そうですね。", "S0")
        records = CorrectionRepository.records_for_segment(db_session, task, "0-0")
        assert [(r.field, r.old_value, r.new_value) for r in records] == [
            ("text", "今日は晴れです。", "今日は曇りです。"),
            ("speaker", "S0", "S1"),
        ]

    def test_empty_text_marks_the_segment_deleted_until_it_is_restored(self, db_session, task):
        _record(db_session, task, ("0-1", TEXT, ""))
        deleted = _corrected(db_session, task)["0-1"]
        assert (deleted["text"], deleted["deleted"], deleted["corrected"]) == ("", True, True)
        assert deleted["original_text"] == "そうですね。"

        _record(db_session, task, ("0-1", TEXT, "そうですね。"))
        restored = _corrected(db_session, task)["0-1"]
        assert (restored["text"], restored["deleted"]) == ("そうですね。", False)

    def test_back_to_the_original_is_not_corrected_but_has_records(self, db_session, task):
        _record(db_session, task, ("0-2", TEXT, "散歩しよう。"), ("0-2", SPEAKER, "S1"))
        _record(db_session, task, ("0-2", TEXT, "散歩しましょう。"), ("0-2", SPEAKER, "S0"))

        segment = _corrected(db_session, task)["0-2"]
        assert (segment["corrected"], segment["has_correction_records"]) == (False, True)
        untouched = _corrected(db_session, task)["0-1"]
        assert (untouched["corrected"], untouched["has_correction_records"]) == (False, False)

    def test_a_correction_equal_to_the_current_content_is_not_recorded(self, db_session, task):
        assert _record(db_session, task, ("0-0", TEXT, "今日は晴れです。"), ("0-0", SPEAKER, "S0")) is None
        operation = _record(db_session, task, ("0-0", TEXT, "今日は雨です。"), ("0-1", SPEAKER, "S1"))

        assert operation is not None
        assert CorrectionRepository.records_for_segment(db_session, task, "0-1") == []
        assert len(CorrectionRepository.records_for_segment(db_session, task, "0-0")) == 1

    def test_no_value_and_an_empty_string_are_the_same(self, db_session):
        # 原始轉錄沒有說話者（NULL）、文字是 NULL：改成空字串都和現在相同
        task_uuid = _one_segment_task(db_session, text=None, speaker=None)

        assert _record(db_session, task_uuid, ("0-0", SPEAKER, ""), ("0-0", TEXT, ""),
                       ("S0", SPEAKER_NAME, None)) is None
        assert CorrectionRepository.touched_by_user(db_session, task_uuid) is False


class TestCorrectedVersion:
    def test_has_the_shape_of_the_original_segments(self, db_session, task):
        original = TranscriptSegmentRepository.segments_for_task(db_session, task)
        version = CorrectionRepository.corrected_version(db_session, task)

        assert [{key: seg[key] for key in original[0]} for seg in version] == original

    def test_goes_straight_into_the_output_formats_without_deleted_segments(self, db_session, task):
        _record(db_session, task, ("0-0", TEXT, "今日は雨です。"), ("0-1", TEXT, ""),
                ("0-2", SPEAKER, "S1"))
        version = CorrectionRepository.corrected_version(db_session, task)
        files = output_format.for_result(TranscriptionTaskResult(success=True, segments=version))

        assert files.txt == "[S0] 今日は雨です。\n[S1] 散歩しましょう。"

    def test_whitespace_only_text_counts_as_deleted_like_in_the_output(self, db_session, task):
        _record(db_session, task, ("0-1", TEXT, " \n "))

        assert _corrected(db_session, task)["0-1"]["deleted"] is True

    def test_a_segment_without_original_text_counts_as_deleted(self, db_session):
        # 規則 2：校正後版本裡文字是空的片段就是刪掉的片段，原始轉錄就是空的也一樣
        segment = _corrected(db_session, _one_segment_task(db_session, text=None))["0-0"]

        assert (segment["text"], segment["deleted"], segment["corrected"],
                segment["has_correction_records"]) == ("", True, False, False)

    def test_word_timings_follow_the_corrected_text(self, db_session):
        # #357：改過文字的片段，逐字時間照校正後的文字重算（沒改到的字沿用原本的時間），下載與校正頁都
        # 讀這一份；只改說話者、沒改過的片段照原樣；刪掉的片段沒有逐字時間。片段存的逐字時間不變
        timed = [
            {"seg_key": "0-0", "start": 1.0, "end": 2.5, "speaker": "S0", "text": "今天開會。",
             "words": [{"text": "今", "start": 1.0, "end": 1.2}, {"text": "天", "start": 1.2, "end": 1.4},
                       {"text": "開", "start": 1.6, "end": 1.8}, {"text": "會", "start": 1.8, "end": 2.0}]},
            {"seg_key": "0-1", "start": 3.0, "end": 4.0, "speaker": "S0", "text": "好的。",
             "words": [{"text": "好", "start": 3.0, "end": 3.2}, {"text": "的", "start": 3.2, "end": 3.4}]},
            {"seg_key": "0-2", "start": 5.0, "end": 6.0, "speaker": "S0", "text": "散會。",
             "words": [{"text": "散", "start": 5.0, "end": 5.2}, {"text": "會", "start": 5.2, "end": 5.4}]},
        ]
        task_uuid = uuid.uuid4()
        db_session.add(TranscriptionLog(task_uuid=task_uuid, status="COMPLETED"))
        TranscriptSegmentRepository.replace_for_task(db_session, task_uuid, timed)
        db_session.commit()
        _record(db_session, task_uuid, ("0-0", TEXT, "今天下午開會。"), ("0-1", SPEAKER, "S1"),
                ("0-2", TEXT, ""))

        version = _corrected(db_session, task_uuid)
        assert [(w["text"], round(w["start"], 6), round(w["end"], 6)) for w in version["0-0"]["words"]] == [
            ("今", 1.0, 1.2), ("天", 1.2, 1.4), ("下", 1.4, 1.5), ("午", 1.5, 1.6), ("開", 1.6, 1.8),
            ("會", 1.8, 2.0)]
        assert version["0-1"]["words"] == timed[1]["words"]
        assert version["0-2"]["words"] is None
        stored = TranscriptSegmentRepository.segments_for_task(db_session, task_uuid)
        assert [seg["words"] for seg in stored] == [seg["words"] for seg in timed]

    def test_queries_a_fixed_number_of_times_however_many_segments(self, db_session, task, test_engine):
        many = uuid.uuid4()
        db_session.add(TranscriptionLog(task_uuid=many, status="COMPLETED"))
        db_session.add_all(TranscriptSegment(task_uuid=many, seg_key=f"0-{i}", seq=i,
                                             start_sec=float(i), speaker="S0", text=f"{i}")
                           for i in range(1000))
        db_session.commit()
        CorrectionRepository.record_operation(
            db_session, many, [Correction(f"0-{i}", TEXT, f"改{i}") for i in range(0, 1000, 2)])

        statements = []
        listener = lambda *args: statements.append(args[2])  # noqa: E731
        event.listen(test_engine, "before_cursor_execute", listener)
        try:
            version = CorrectionRepository.corrected_version(db_session, many)
        finally:
            event.remove(test_engine, "before_cursor_execute", listener)

        assert len(version) == 1000 and version[998]["text"] == "改998"
        assert len([s for s in statements if s.lstrip().upper().startswith("SELECT")]) == 2


class TestUndo:
    def test_undoing_an_operation_restores_all_its_segments(self, db_session, task):
        operation = _record(db_session, task, ("0-0", TEXT, "A"), ("0-1", TEXT, "B"), ("0-2", TEXT, ""))

        undo = CorrectionRepository.undo_operation(db_session, task, operation)

        assert _texts(db_session, task) == [seg["text"] for seg in ORIGINAL]
        assert (undo.restored, undo.skipped) == (3, 0)
        assert undo.operation_id not in (None, operation)
        records = CorrectionRepository.records_for_segment(db_session, task, "0-2")
        assert [(r.old_value, r.new_value) for r in records] == [("散歩しましょう。", ""),
                                                                  ("", "散歩しましょう。")]
        assert records[1].operation_id == undo.operation_id

    def test_segments_changed_again_afterwards_are_skipped(self, db_session, task):
        operation = _record(db_session, task, ("0-0", TEXT, "A"), ("0-1", TEXT, "B"), ("0-2", TEXT, "C"))
        _record(db_session, task, ("0-1", TEXT, "手で直した"))

        undo = CorrectionRepository.undo_operation(db_session, task, operation)

        assert (undo.restored, undo.skipped) == (2, 1)
        assert _texts(db_session, task) == ["今日は晴れです。", "手で直した", "散歩しましょう。"]

    def test_undoing_the_undo_brings_back_the_operation(self, db_session, task):
        operation = _record(db_session, task, ("0-0", TEXT, "A"), ("0-1", SPEAKER, "S0"), ("0-2", TEXT, "C"))
        undo = CorrectionRepository.undo_operation(db_session, task, operation)

        redo = CorrectionRepository.undo_operation(db_session, task, undo.operation_id)

        assert (redo.restored, redo.skipped) == (3, 0)
        version = _corrected(db_session, task)
        assert [version[k]["text"] for k in ("0-0", "0-1", "0-2")] == ["A", "そうですね。", "C"]
        assert version["0-1"]["speaker"] == "S0"

    def test_the_same_segment_changed_twice_in_one_operation_goes_back_to_the_start(
            self, db_session, task):
        operation = _record(db_session, task, ("0-0", TEXT, "A"), ("0-0", TEXT, "B"))

        undo = CorrectionRepository.undo_operation(db_session, task, operation)

        assert (undo.restored, undo.skipped) == (2, 0)
        assert _corrected(db_session, task)["0-0"]["text"] == "今日は晴れです。"

    def test_a_segment_changed_twice_in_one_operation_and_back_by_hand_is_skipped(
            self, db_session, task):
        operation = _record(db_session, task, ("0-0", TEXT, "A"), ("0-0", TEXT, "B"))
        _record(db_session, task, ("0-0", TEXT, "A"))

        undo = CorrectionRepository.undo_operation(db_session, task, operation)

        assert (undo.restored, undo.skipped, undo.operation_id) == (0, 2, None)
        assert _corrected(db_session, task)["0-0"]["text"] == "A"

    def test_nothing_to_restore_records_nothing(self, db_session, task):
        operation = _record(db_session, task, ("0-0", TEXT, "A"))
        _record(db_session, task, ("0-0", TEXT, "B"))

        undo = CorrectionRepository.undo_operation(db_session, task, operation)

        assert (undo.restored, undo.skipped, undo.operation_id) == (0, 1, None)
        assert len(CorrectionRepository.records_for_segment(db_session, task, "0-0")) == 2

    def test_an_operation_of_another_task_is_not_found(self, db_session, task):
        other, operation = _other_task_with_a_record(db_session)

        assert CorrectionRepository.undo_operation(db_session, task, operation) is None
        assert CorrectionRepository.undo_operation(db_session, task, uuid.uuid4()) is None
        assert _texts(db_session, other) == ["A"]


class TestSpeakerNames:
    def test_naming_renaming_and_clearing(self, db_session, task):
        assert CorrectionRepository.speaker_names(db_session, task) == {}

        _record(db_session, task, ("S0", SPEAKER_NAME, "王小明"), ("S1", SPEAKER_NAME, "陳小華"))
        assert CorrectionRepository.speaker_names(db_session, task) == {"S0": "王小明", "S1": "陳小華"}

        _record(db_session, task, ("S0", SPEAKER_NAME, "王大明"))
        assert CorrectionRepository.speaker_names(db_session, task) == {"S0": "王大明", "S1": "陳小華"}

        _record(db_session, task, ("S1", SPEAKER_NAME, ""))
        assert CorrectionRepository.speaker_names(db_session, task) == {"S0": "王大明"}

    def test_each_change_leaves_a_record_and_can_be_undone(self, db_session, task):
        named = _record(db_session, task, ("S0", SPEAKER_NAME, "王小明"))
        _record(db_session, task, ("S0", SPEAKER_NAME, None))
        assert _record(db_session, task, ("S0", SPEAKER_NAME, "")) is None

        undo = CorrectionRepository.undo_operation(db_session, task, named)
        assert (undo.restored, undo.skipped) == (0, 1)

        renamed = _record(db_session, task, ("S0", SPEAKER_NAME, "王大明"))
        CorrectionRepository.undo_operation(db_session, task, renamed)
        assert CorrectionRepository.speaker_names(db_session, task) == {}

    def test_names_are_not_part_of_a_segment_history_or_the_corrected_version(self, db_session, task):
        _record(db_session, task, ("S0", SPEAKER_NAME, "王小明"))

        assert CorrectionRepository.records_for_segment(db_session, task, "S0") == []
        assert [seg["speaker"] for seg in CorrectionRepository.corrected_version(db_session, task)] \
            == ["S0", "S1", "S0"]


class TestTouchedByUser:
    def test_a_fresh_task_is_untouched(self, db_session, task):
        assert CorrectionRepository.touched_by_user(db_session, task) is False

    def test_any_correction_record_counts_even_after_it_is_undone(self, db_session, task):
        operation = _record(db_session, task, ("0-0", TEXT, "A"))
        CorrectionRepository.undo_operation(db_session, task, operation)

        assert CorrectionRepository.touched_by_user(db_session, task) is True

    def test_a_speaker_name_counts(self, db_session, task):
        _record(db_session, task, ("S0", SPEAKER_NAME, "王小明"))

        assert CorrectionRepository.touched_by_user(db_session, task) is True

    @pytest.mark.parametrize("review_state", ["verified", "flagged"])
    def test_a_review_state_counts_without_any_correction(self, db_session, task, review_state):
        _segment_row(db_session, task, "0-1").review_state = review_state
        db_session.commit()

        assert CorrectionRepository.touched_by_user(db_session, task) is True


class TestDeletedWithTheTask:
    def test_deleting_the_task_record_deletes_its_correction_records(
            self, client, db_session, task, test_engine):
        _record(db_session, task, ("0-0", TEXT, "A"), ("S0", SPEAKER_NAME, "王小明"))
        other, _ = _other_task_with_a_record(db_session)
        with test_engine.connect() as connection:
            # SQLite 預設不強制外鍵：ON DELETE CASCADE 不會發生，校正紀錄要由刪除的程式自己刪
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 0

        assert client.delete(f"/api/v1/history/{task}").status_code == 200

        db_session.expire_all()
        assert db_session.query(CorrectionRecord).filter_by(task_uuid=task).count() == 0
        assert db_session.query(CorrectionRecord).filter_by(task_uuid=other).count() == 1

    def test_a_failed_delete_keeps_the_segments_and_correction_records(
            self, client, db_session, task, test_engine):
        # 片段、校正紀錄與任務紀錄在同一個交易裡刪：任務紀錄刪不掉時，校正不能先不見（ADR 0007）
        _record(db_session, task, ("0-0", TEXT, "A"))

        with writes_fail(test_engine, "transcription_logs", "DELETE"):
            assert client.delete(f"/api/v1/history/{task}").status_code == 500

        db_session.expire_all()
        assert _texts(db_session, task) == ["A", "そうですね。", "散歩しましょう。"]




class TestRecordsAreAppendOnly:
    def test_a_record_cannot_be_changed(self, db_session, task):
        _record(db_session, task, ("0-0", TEXT, "A"))
        record = CorrectionRepository.records_for_segment(db_session, task, "0-0")[0]

        record.new_value = "B"
        with pytest.raises(RuntimeError, match="校正紀錄寫入後不改"):
            db_session.flush()

    def test_a_record_cannot_be_deleted_on_its_own(self, db_session, task):
        _record(db_session, task, ("0-0", TEXT, "A"))
        record = CorrectionRepository.records_for_segment(db_session, task, "0-0")[0]

        db_session.delete(record)
        with pytest.raises(RuntimeError, match="校正紀錄寫入後不改"):
            db_session.flush()


class TestRefusedOperations:
    def test_an_unknown_segment_records_nothing(self, db_session, task):
        with pytest.raises(ValueError, match="沒有片段 9-9"):
            _record(db_session, task, ("0-0", TEXT, "A"), ("9-9", TEXT, "B"))

        assert CorrectionRepository.touched_by_user(db_session, task) is False

    def test_a_speaker_name_for_a_missing_task_records_nothing(self, db_session):
        # SQLite 不強制外鍵，不擋的話會留下孤兒紀錄；Postgres 則是 IntegrityError
        missing = uuid.uuid4()

        with pytest.raises(ValueError, match="找不到任務"):
            _record(db_session, missing, ("S0", SPEAKER_NAME, "王小明"))

        assert CorrectionRepository.touched_by_user(db_session, missing) is False


class TestOneOperationAtATime:
    def test_a_concurrent_operation_waits_and_reads_what_the_first_one_wrote(
            self, db_session, task, test_engine, monkeypatch):
        # 兩個請求同時改同一個片段：後到的要等先到的寫完，改前才會是先到的改後，不是過時的原文
        other_session = sessionmaker(bind=test_engine)()
        second = threading.Thread(target=lambda: _record(other_session, task, ("0-0", TEXT, "B")))
        list_for_task = TranscriptSegmentRepository.list_for_task
        waited = []

        def first_reads_current_content(db, task_uuid):
            if not second.is_alive() and not waited:
                second.start()
                time.sleep(0.3)
                waited.append(second.is_alive())
            return list_for_task(db, task_uuid)

        monkeypatch.setattr(TranscriptSegmentRepository, "list_for_task",
                            staticmethod(first_reads_current_content))
        try:
            _record(db_session, task, ("0-0", TEXT, "A"))
            second.join(timeout=20)
        finally:
            other_session.close()

        assert waited == [True]
        records = CorrectionRepository.records_for_segment(db_session, task, "0-0")
        assert [(r.old_value, r.new_value) for r in records] == [("今日は晴れです。", "A"), ("A", "B")]
