"""假的 google-genai 用戶端：只實作 Gemini 轉接器用到的 files、models 與 batches。

回傳真的 ``google.genai.types`` 物件、拋真的 ``google.genai.errors``，行為照 Gemini API：

- 上傳的檔案處理完（ACTIVE）才能拿來轉錄，還在處理中就回 400；
- 回應的 header ``x-gemini-service-tier`` 是實際用到的處理模式；
- 批次每查一次就往下一個狀態走；成功結束時，每個請求一份回應，順序和送出時相同。
  沒有另外指定的請求，回應的文字是 ``[00:00.00]<這個請求的提示詞>``；
  送出時請求引用的檔案不在遠端，那個請求回錯誤。

測試從 ``stored`` 看遠端還留著哪些檔案。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Union

from google.genai import errors, types


def _error(cls, code: int, status: str, message: str):
    return cls(code, {"error": {"code": code, "message": message, "status": status}})


def unavailable() -> errors.ServerError:
    """503：模型超載，可以重試。"""
    return _error(errors.ServerError, 503, "UNAVAILABLE", "The model is overloaded.")


def rate_limited() -> errors.ClientError:
    """429：配額用完，可以重試。"""
    return _error(errors.ClientError, 429, "RESOURCE_EXHAUSTED", "Resource has been exhausted.")


def invalid_argument(message: str = "Request contains an invalid argument.") -> errors.ClientError:
    """400：重試也不會好。"""
    return _error(errors.ClientError, 400, "INVALID_ARGUMENT", message)


@dataclass
class Reply:
    """一次成功的回應。"""

    text: str = "[00:01.00]こんにちは"
    input_tokens: int = 1000
    output_tokens: int = 200
    served: Optional[str] = None
    """實際用到的處理模式；None 表示照請求的處理模式。"""


@dataclass
class Blocked:
    """被安全機制阻擋：回應沒有 candidates。"""

    reason: types.BlockedReason = types.BlockedReason.PROHIBITED_CONTENT


Outcome = Union[Reply, Blocked, Exception]
"""generate_content 的一次結果：回應、被阻擋，或拋出這個例外。"""

BatchOutcome = Union[Reply, Blocked, types.JobError]
"""批次裡一個請求的結果：回應、被阻擋，或這個請求的錯誤。"""


def _response(outcome: Union[Reply, Blocked], tier: Optional[str]) -> types.GenerateContentResponse:
    headers = {"x-gemini-service-tier": tier} if tier else {}
    if isinstance(outcome, Blocked):
        return types.GenerateContentResponse(
            prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=outcome.reason),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100, total_token_count=100),
            sdk_http_response=types.HttpResponse(headers=headers),
        )
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(
            role="model", parts=[types.Part(text=outcome.text)]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=outcome.input_tokens,
            candidates_token_count=outcome.output_tokens,
            total_token_count=outcome.input_tokens + outcome.output_tokens,
        ),
        sdk_http_response=types.HttpResponse(headers=headers),
    )


class FakeGenaiClient:
    def __init__(self) -> None:
        self.files = _Files(self)
        self.models = _Models(self)
        self.batches = _Batches(self)
        self.stored: Dict[str, types.File] = {}
        """遠端還留著的檔案，key 是檔名。"""
        self.processing_polls = 0
        """上傳之後還要再查幾次才處理完。"""
        self.processing_fails = False
        """處理的結果是 FAILED 而不是 ACTIVE。"""
        self.failing: Dict[str, Exception] = {}
        """操作名稱（例如 ``"files.upload"``）→ 這個操作每次都拋的錯。"""
        self.replies: List[Outcome] = []
        """generate_content 依序的結果；用完之後都回 ``Reply()``。"""
        self.overloaded: Set[str] = set()
        """這些處理模式（``"flex"``、``"standard"``）的請求一律回 503。"""
        self.tier_header = True
        """回應帶不帶 ``x-gemini-service-tier``（google-genai 1.69 以前讀不到）。"""
        self.batch_states: List[str] = ["JOB_STATE_SUCCEEDED"]
        """每查一次批次依序回報的狀態，停在最後一個。"""
        self.batch_outcomes: Dict[int, BatchOutcome] = {}
        """批次裡第 i 個請求的結果；沒指定的照提示詞回應。"""
        self._ids = itertools.count(1)
        self._polls_left: Dict[str, int] = {}
        self._jobs: Dict[str, List[types.InlinedResponse]] = {}
        self._job_polls: Dict[str, int] = {}

    def _check(self, operation: str) -> None:
        if operation in self.failing:
            raise self.failing[operation]


class _Files:
    def __init__(self, client: FakeGenaiClient):
        self._client = client

    def upload(self, *, file: Any, config: Dict[str, Any]) -> types.File:
        self._client._check("files.upload")
        name = f"files/{next(self._client._ids)}"
        processing = self._client.processing_polls > 0
        uploaded = types.File(
            name=name,
            display_name=config.get("display_name"),
            mime_type=config.get("mime_type"),
            size_bytes=len(file.read()),
            uri=f"https://generativelanguage.googleapis.com/v1beta/{name}",
            state=types.FileState.PROCESSING if processing else types.FileState.ACTIVE,
        )
        self._client.stored[name] = uploaded
        self._client._polls_left[name] = self._client.processing_polls
        return uploaded.model_copy()

    def get(self, *, name: str) -> types.File:
        self._client._check("files.get")
        stored = self._client.stored[name]
        left = self._client._polls_left[name] - 1
        self._client._polls_left[name] = left
        if left <= 0 and stored.state == types.FileState.PROCESSING:
            stored.state = (types.FileState.FAILED if self._client.processing_fails
                            else types.FileState.ACTIVE)
        return stored.model_copy()

    def delete(self, *, name: str) -> None:
        self._client._check("files.delete")
        if self._client.stored.pop(name, None) is None:
            raise _error(errors.ClientError, 404, "NOT_FOUND", f"File {name} not found.")


class _Models:
    def __init__(self, client: FakeGenaiClient):
        self._client = client

    def generate_content(self, *, model: str, contents: List[Any],
                         config: types.GenerateContentConfig) -> types.GenerateContentResponse:
        tier = "flex" if config.service_tier == "flex" else "standard"
        for part in contents:
            if isinstance(part, types.File):
                stored = self._client.stored.get(part.name or "")
                if stored is None or stored.state != types.FileState.ACTIVE:
                    raise _error(errors.ClientError, 400, "FAILED_PRECONDITION",
                                 f"The File {part.name} is not in an ACTIVE state.")
        if tier in self._client.overloaded:
            raise unavailable()
        outcome = self._client.replies.pop(0) if self._client.replies else Reply()
        if isinstance(outcome, Exception):
            raise outcome
        served = outcome.served if isinstance(outcome, Reply) and outcome.served else tier
        return _response(outcome, served if self._client.tier_header else None)


class _Batches:
    def __init__(self, client: FakeGenaiClient):
        self._client = client

    def create(self, *, model: str, src: List[Any], config: Any = None) -> types.BatchJob:
        self._client._check("batches.create")
        name = f"batches/{next(self._client._ids)}"
        # SDK 收 InlinedRequest 或同樣形狀的 dict；檔案在送出時就要在遠端
        self._client._jobs[name] = [self._respond(i, types.InlinedRequest.model_validate(r))
                                    for i, r in enumerate(src)]
        self._client._job_polls[name] = 0
        config = types.CreateBatchJobConfig.model_validate(config or {})
        return types.BatchJob(name=name, display_name=config.display_name, model=model,
                              state=types.JobState.JOB_STATE_PENDING)

    def get(self, *, name: str) -> types.BatchJob:
        self._client._check("batches.get")
        states = self._client.batch_states
        polls = self._client._job_polls[name]
        self._client._job_polls[name] = polls + 1
        state = types.JobState(states[min(polls, len(states) - 1)])
        dest = None
        if state == types.JobState.JOB_STATE_SUCCEEDED:
            dest = types.BatchJobDestination(inlined_responses=self._client._jobs[name])
        return types.BatchJob(name=name, state=state, dest=dest)

    def _respond(self, index: int, request: types.InlinedRequest) -> types.InlinedResponse:
        parts = request.contents[0].parts
        prompt = next(p.text for p in parts if p.text)
        uri = next(p.file_data.file_uri for p in parts if p.file_data)
        if not any(f.uri == uri for f in self._client.stored.values()):
            return types.InlinedResponse(error=types.JobError(code=5, message=f"File {uri} not found."))
        outcome = self._client.batch_outcomes.get(index, Reply(text=f"[00:00.00]{prompt}"))
        if isinstance(outcome, types.JobError):
            return types.InlinedResponse(error=outcome)
        return types.InlinedResponse(response=_response(outcome, None))
