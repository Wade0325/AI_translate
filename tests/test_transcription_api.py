import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.app.services.transcription.models import TranscriptionResponse

# client fixture is assumed to be available from a conftest.py file,
# similar to your existing tests.


def test_transcribe_media_success(client: TestClient):
    """
    測試 /transcribe 端點的成功路徑。
    應成功 "轉錄" 檔案並返回 200 OK。
    """
    # 1. 模擬 transcription_service.transcribe_file 方法
    # 這是我們單元測試的核心，防止對實際服務的呼叫。
    mock_response_data = TranscriptionResponse(
        task_uuid=uuid.uuid4(),
        transcripts={"lrc": "[00:01.00] Test transcript.",
                     "txt": "Test transcript."},
        tokens_used=123,
        cost=0.00456,
        model="gemini-test-model",
        source_language="en-US",
        processing_time_seconds=5.5,
        audio_duration_seconds=10.1,
        cost_breakdown=[]
    )

    # 要 patch 的路徑是該物件被 *使用* 的地方，而不是它被定義的地方。
    with patch('app.api.transcription.transcription_service.transcribe_file', return_value=mock_response_data) as mock_transcribe:

        # 2. 準備測試請求資料
        # 我們可以使用一個簡單的記憶體內類檔案物件。
        file_content = b"fake audio data"
        files = {'file': ('test.mp3', file_content, 'audio/mpeg')}
        data = {'source_lang': 'en-US', 'model': 'gemini-test-model'}

        # 3. 發起 API 呼叫
        response = client.post("/api/v1/transcribe", files=files, data=data)

        # 4. 斷言結果
        assert response.status_code == 200

        response_json = response.json()
        assert response_json["task_uuid"] == str(mock_response_data.task_uuid)
        assert response_json["model"] == mock_response_data.model
        assert response_json["tokens_used"] == mock_response_data.tokens_used
        assert "transcripts" in response_json

        # 斷言服務被正確地呼叫了一次
        mock_transcribe.assert_called_once()
        call_args = mock_transcribe.call_args[1]
        assert call_args['model'] == 'gemini-test-model'
        assert call_args['source_lang'] == 'en-US'
        assert call_args['original_filename'] == 'test.mp3'


def test_transcribe_media_unsupported_file_type(client: TestClient):
    """
    測試上傳不支援的 MIME 類型的檔案時，應返回 400 錯誤。
    """
    with patch('app.api.transcription.transcription_service.transcribe_file') as mock_transcribe:

        file_content = b'{"key": "value"}'
        # 使用不支援的類型 'application/json'
        files = {'file': ('test.json', file_content, 'application/json')}
        data = {'source_lang': 'en-US', 'model': 'gemini-test-model'}

        response = client.post("/api/v1/transcribe", files=files, data=data)

        assert response.status_code == 400
        assert "不支援的檔案格式" in response.json()["detail"]

        # 確保實際的轉錄服務從未被呼叫
        mock_transcribe.assert_not_called()


def test_transcribe_media_service_exception(client: TestClient):
    """
    測試如果轉錄服務引發例外，錯誤會被正確傳遞。
    """
    # 模擬服務引發一個通用例外
    with patch('app.api.transcription.transcription_service.transcribe_file', side_effect=Exception("Service failed")) as mock_transcribe:

        file_content = b"fake audio data"
        files = {'file': ('test.mp3', file_content, 'audio/mpeg')}
        data = {'source_lang': 'en-US', 'model': 'gemini-test-model'}

        # TestClient 的設計是會重新引發伺服器端的例外。
        # 因此，我們捕捉這個例外來驗證流程是否如預期般中斷。
        try:
            client.post("/api/v1/transcribe", files=files, data=data)
            # 如果沒有引發例外，就強制失敗
            assert False, "Expected an exception to be raised"
        except Exception as e:
            # 斷言引發的是我們模擬的例外
            assert str(e) == "Service failed"

        # 驗證即使失敗，服務仍然被呼叫了
        mock_transcribe.assert_called_once()
