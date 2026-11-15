"""整合測試：說話者名稱（#359）

測試範圍：
  PUT  /api/v1/transcripts/{task_uuid}/speakers/{speaker}/name（替一個說話者編號設定或清掉名稱）
  GET  /api/v1/transcripts/{task_uuid} 的 speaker_names
  POST /api/v1/transcripts/{task_uuid}/operations/{operation_id}/undo 的 speaker_names（復原取名字）
  GET  /api/v1/history/{task_uuid}/download/{fmt}：校正後版本寫名稱，原始轉錄寫編號

取名字算一次校正（GLOSSARY「校正」）：每次有變都留一筆校正紀錄，對象是說話者編號，可以復原。結果從讀取端點與
下載驗（#25 的測試決策）；校正紀錄的筆數與操作編號直接查資料表，說話者名稱的紀錄沒有讀的端點（片段的歷程只列
片段的紀錄）。四種輸出格式的黃金檔在 test_history_api.py 的 FOUR_NAMED。
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.api.transcripts  # noqa: F401  app_log 只接得到 fixture 啟動前已經建立的 logger
from app.database.models import CorrectionRecord, TranscriptionLog, TranscriptSegment


def _task(db: Session, speakers=("S0", "S1"), **log) -> TranscriptionLog:
    """一個能校正的任務：片段 0000、0001…，說話者依序是 speakers，文字是「第 N 段」。"""
    fields = {"task_uuid": uuid.uuid4(), "status": "COMPLETED", "original_filename": "meeting.m4a",
              "model_used": "moss-align", "provider": "Local", "source_language": "zh-TW", **log}
    task = TranscriptionLog(**fields)
    db.add(task)
    for i, speaker in enumerate(speakers):
        db.add(TranscriptSegment(task_uuid=task.task_uuid, seg_key=f"{i:04d}", seq=i, start_sec=i * 5.0,
                                 end_sec=i * 5.0 + 3.0, speaker=speaker, text=f"第 {i} 段"))
    db.commit()
    return task


def _name(client: TestClient, task_uuid, speaker: str, name):
    return client.put(f"/api/v1/transcripts/{task_uuid}/speakers/{speaker}/name", json={"name": name})


def _names(client: TestClient, task_uuid) -> dict:
    return client.get(f"/api/v1/transcripts/{task_uuid}").json()["speaker_names"]


def _download(client: TestClient, task_uuid, version: str = "corrected") -> str:
    response = client.get(f"/api/v1/history/{task_uuid}/download/txt", params={"version": version})
    assert response.status_code == 200, response.text
    return response.text


def _undo(client: TestClient, task_uuid, operation_id) -> dict:
    response = client.post(f"/api/v1/transcripts/{task_uuid}/operations/{operation_id}/undo")
    assert response.status_code == 200, response.text
    return response.json()


def _records(db: Session, task_uuid) -> list:
    """(改了什麼, 對象, 改前, 改後, 操作編號)，依編號排序。"""
    db.expire_all()
    rows = (db.query(CorrectionRecord).filter(CorrectionRecord.task_uuid == task_uuid)
            .order_by(CorrectionRecord.id).all())
    return [(r.field, r.target, r.old_value, r.new_value, str(r.operation_id)) for r in rows]


class TestSpeakerName:
    def test_naming_renaming_and_clearing_each_leave_one_correction_record(self, client, db_session):
        task = _task(db_session)
        original = _download(client, task.task_uuid, "original")
        assert _names(client, task.task_uuid) == {}

        named = _name(client, task.task_uuid, "S0", "王小明")

        assert named.status_code == 200, named.text
        body = named.json()
        assert (body["speaker"], body["name"], body["speaker_names"]) == ("S0", "王小明", {"S0": "王小明"})
        assert _names(client, task.task_uuid) == {"S0": "王小明"}
        assert _download(client, task.task_uuid) == "[王小明] 第 0 段\n[S1] 第 1 段"
        assert _download(client, task.task_uuid, "original") == original

        renamed = _name(client, task.task_uuid, "S0", "王大明").json()

        assert _download(client, task.task_uuid) == "[王大明] 第 0 段\n[S1] 第 1 段"

        cleared = _name(client, task.task_uuid, "S0", "").json()

        assert (cleared["name"], cleared["speaker_names"]) == (None, {})
        assert _names(client, task.task_uuid) == {}
        assert _download(client, task.task_uuid) == original
        assert _records(db_session, task.task_uuid) == [
            ("speaker_name", "S0", "", "王小明", body["operation_id"]),
            ("speaker_name", "S0", "王小明", "王大明", renamed["operation_id"]),
            ("speaker_name", "S0", "王大明", "", cleared["operation_id"]),
        ]
        assert len({body["operation_id"], renamed["operation_id"], cleared["operation_id"]}) == 3

    def test_the_name_it_already_has_records_nothing(self, client, db_session):
        task = _task(db_session)
        _name(client, task.task_uuid, "S0", "王小明")

        again = _name(client, task.task_uuid, "S0", " 王小明 ").json()
        unnamed = _name(client, task.task_uuid, "S1", "").json()

        assert (again["operation_id"], unnamed["operation_id"]) == (None, None)
        assert len(_records(db_session, task.task_uuid)) == 1

    @pytest.mark.parametrize("sent, stored", [("  王小明\t", "王小明"), (" \n 王小明 \r\n", "王小明"),
                                              ("Amy Chen", "Amy Chen"), ("名" * 30, "名" * 30)])
    def test_spaces_around_the_name_are_removed(self, client, db_session, sent, stored):
        task = _task(db_session)

        assert _name(client, task.task_uuid, "S1", sent).json()["name"] == stored
        assert _names(client, task.task_uuid) == {"S1": stored}

    def test_only_spaces_clears_the_name(self, client, db_session):
        task = _task(db_session)
        _name(client, task.task_uuid, "S0", "王小明")

        assert _name(client, task.task_uuid, "S0", "  ").json()["speaker_names"] == {}

    def test_naming_can_be_undone_and_the_undo_can_be_undone(self, client, db_session):
        task = _task(db_session)
        operation = _name(client, task.task_uuid, "S0", "王小明").json()["operation_id"]

        undo = _undo(client, task.task_uuid, operation)

        assert (undo["restored"], undo["skipped"], undo["segments"]) == (1, 0, [])
        assert undo["speaker_names"] == {}
        assert _download(client, task.task_uuid) == "[S0] 第 0 段\n[S1] 第 1 段"

        redo = _undo(client, task.task_uuid, undo["operation_id"])

        assert redo["speaker_names"] == {"S0": "王小明"}
        assert _download(client, task.task_uuid) == "[王小明] 第 0 段\n[S1] 第 1 段"

    def test_segments_are_not_corrected_by_a_name(self, client, db_session):
        # 名稱的對象是說話者編號，不是片段：片段沒有校正過，它的歷程也不列名稱的紀錄
        task = _task(db_session)
        before = client.get(f"/api/v1/transcripts/{task.task_uuid}").json()["segments"]

        _name(client, task.task_uuid, "S0", "王小明")

        assert client.get(f"/api/v1/transcripts/{task.task_uuid}").json()["segments"] == before
        history = client.get(f"/api/v1/transcripts/{task.task_uuid}/segments/0000/correction-records").json()
        assert history["records"] == []

    def test_names_belong_to_one_task(self, client, db_session):
        task, other = _task(db_session), _task(db_session)

        _name(client, task.task_uuid, "S0", "王小明")

        assert _names(client, other.task_uuid) == {}
        assert _name(client, other.task_uuid, "S0", "王小明").status_code == 200

    def test_the_name_goes_with_the_speaker_id_when_segments_move_to_it(self, client, db_session):
        # 模型把同一個人分成 S0 和 S2：把 S2 全部換成 S0，這些片段也寫 S0 的名稱
        task = _task(db_session, ("S0", "S1", "S2"))
        _name(client, task.task_uuid, "S0", "王小明")

        client.post(f"/api/v1/transcripts/{task.task_uuid}/speakers/reassign",
                    json={"from_speaker": "S2", "to_speaker": "S0"})

        assert _download(client, task.task_uuid) == "[王小明] 第 0 段\n[S1] 第 1 段\n[王小明] 第 2 段"

    def test_a_speaker_whose_segments_are_all_deleted_can_still_be_named(self, client, db_session):
        # 刪掉的片段還原之後就是那一位（和改說話者的範圍相同）
        task = _task(db_session)
        client.patch(f"/api/v1/transcripts/{task.task_uuid}/segments/0001", json={"text": ""})

        assert _name(client, task.task_uuid, "S1", "李大華").status_code == 200

    def test_a_single_speaker_task_writes_no_labels_and_so_no_names(self, client, db_session):
        task = _task(db_session)
        _name(client, task.task_uuid, "S0", "王小明")

        client.patch(f"/api/v1/transcripts/{task.task_uuid}", json={"single_speaker": True})

        assert _download(client, task.task_uuid) == "第 0 段\n第 1 段"

    def test_the_name_is_not_written_to_the_log(self, client, db_session, app_log):
        task = _task(db_session)

        _name(client, task.task_uuid, "S0", "王小明")
        _name(client, task.task_uuid, "S1", "王小明")  # 被擋下的也一樣

        assert not [entry for entry in app_log if "小明" in entry]


class TestDuplicateNames:
    """同一個任務裡，兩個說話者編號不能取同一個名稱（#359 第 3 點）：擋下時說明是哪一位已經用了，什麼都不寫。"""

    @pytest.mark.parametrize("taken, sent", [("王小明", "王小明"), ("王小明", " 王小明 "), ("Amy", "amy"),
                                             ("Amy", "ＡＭＹ"), ("ｻｸﾗ", "サクラ")])
    def test_a_name_another_speaker_has_is_refused_and_says_who(self, client, db_session, taken, sent):
        # 看起來一樣的名稱也算同一個：英文不分大小寫，全形與半形相同
        task = _task(db_session)
        _name(client, task.task_uuid, "S0", taken)
        records = _records(db_session, task.task_uuid)

        response = _name(client, task.task_uuid, "S1", sent)

        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert "S0" in detail and taken in detail
        assert _records(db_session, task.task_uuid) == records
        assert _names(client, task.task_uuid) == {"S0": taken}

    def test_the_name_is_free_again_once_the_other_speaker_lets_it_go(self, client, db_session):
        task = _task(db_session)
        _name(client, task.task_uuid, "S0", "王小明")
        _name(client, task.task_uuid, "S0", "王大明")

        assert _name(client, task.task_uuid, "S1", "王小明").status_code == 200
        assert _names(client, task.task_uuid) == {"S0": "王大明", "S1": "王小明"}

    def test_a_name_left_on_a_speaker_without_segments_moves_to_the_new_one(self, client, db_session):
        # S0 取了名字之後，S0 的片段全部換成 S1（同一個人）：S0 沒有片段、畫面上看不到了，再替 S1 取同一個名字時不擋，
        # 名稱從 S0 移到 S1，兩筆在同一次操作裡，一次復原就都回去
        task = _task(db_session)
        _name(client, task.task_uuid, "S0", "王小明")
        client.post(f"/api/v1/transcripts/{task.task_uuid}/speakers/reassign",
                    json={"from_speaker": "S0", "to_speaker": "S1"})

        moved = _name(client, task.task_uuid, "S1", "王小明")

        assert moved.status_code == 200, moved.text
        operation = moved.json()["operation_id"]
        assert moved.json()["speaker_names"] == {"S1": "王小明"}
        assert [r for r in _records(db_session, task.task_uuid) if r[0] == "speaker_name"][-2:] == [
            ("speaker_name", "S0", "王小明", "", operation), ("speaker_name", "S1", "", "王小明", operation)]
        assert _download(client, task.task_uuid) == "[王小明] 第 0 段\n[王小明] 第 1 段"

        assert _undo(client, task.task_uuid, operation)["speaker_names"] == {"S0": "王小明"}

    def test_undo_does_not_bring_back_a_name_another_speaker_has_taken(self, client, db_session):
        task = _task(db_session)
        _name(client, task.task_uuid, "S0", "王小明")
        rename = _name(client, task.task_uuid, "S0", "王大明").json()["operation_id"]
        _name(client, task.task_uuid, "S1", "王小明")

        undo = _undo(client, task.task_uuid, rename)

        assert (undo["restored"], undo["skipped"], undo["operation_id"]) == (0, 1, None)
        assert undo["speaker_names"] == {"S0": "王大明", "S1": "王小明"}


class TestRefusedSpeakerNames:
    """不合規則的名稱回一句說明，什麼都不寫（#359 第 6 點）。"""

    def _refused(self, response, status: int, db: Session, task_uuid) -> str:
        assert response.status_code == status, response.text
        assert _records(db, task_uuid) == []
        detail = response.json()["detail"]
        assert isinstance(detail, str) and detail
        return detail

    def test_a_name_over_30_characters(self, client, db_session):
        task = _task(db_session)

        detail = self._refused(_name(client, task.task_uuid, "S0", "名" * 31), 400, db_session, task.task_uuid)

        assert "30" in detail

    @pytest.mark.parametrize("name", ["[王小明]", "王]", "a[b"])
    def test_square_brackets(self, client, db_session, name):
        task = _task(db_session)

        detail = self._refused(_name(client, task.task_uuid, "S0", name), 400, db_session, task.task_uuid)

        assert "方括號" in detail

    @pytest.mark.parametrize("name", ["王\n小明", "王\r\n小明", "王 小明", "王\x85小明"])
    def test_line_breaks(self, client, db_session, name):
        task = _task(db_session)

        detail = self._refused(_name(client, task.task_uuid, "S0", name), 400, db_session, task.task_uuid)

        assert "換行" in detail

    @pytest.mark.parametrize("name", ["S1", "s12", "Ｓ１", "S0"])
    def test_a_name_written_like_a_speaker_id(self, client, db_session, name):
        # 寫成 S 加數字的名稱會和沒取名字的說話者分不出來
        task = _task(db_session)

        detail = self._refused(_name(client, task.task_uuid, "S1", name), 400, db_session, task.task_uuid)

        assert "說話者編號" in detail

    @pytest.mark.parametrize("speaker", ["S5", "s0", "S00"])
    def test_a_speaker_the_task_does_not_have(self, client, db_session, speaker):
        task = _task(db_session)

        self._refused(_name(client, task.task_uuid, speaker, "王小明"), 404, db_session, task.task_uuid)

    @pytest.mark.parametrize("body", [{}, {"name": None}, {"name": 1}, {"name": "王小明", "x": 1}])
    def test_the_body_takes_only_a_name(self, client, db_session, body):
        task = _task(db_session)

        response = client.put(f"/api/v1/transcripts/{task.task_uuid}/speakers/S0/name", json=body)

        assert response.status_code == 422
        assert _records(db_session, task.task_uuid) == []

    def test_a_task_that_cannot_be_corrected(self, client, db_session):
        task = _task(db_session, status="PROCESSING")

        detail = self._refused(_name(client, task.task_uuid, "S0", "王小明"), 409, db_session, task.task_uuid)

        assert "還沒完成" in detail

    def test_unknown_or_malformed_task(self, client):
        assert _name(client, uuid.uuid4(), "S0", "王小明").status_code == 404
        assert _name(client, "not-a-uuid", "S0", "王小明").status_code == 400
