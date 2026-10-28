"""MOSS-Transcribe-Diarize：單次推論同時產生說話者、時間戳與文字。

輸出格式為 ``[起秒][S01]文字[迄秒]`` 連續序列；這裡轉成與 VibeVoice 相同的
``{Start, End, Speaker, Content}`` 片段，下游的 Qwen3-ASR／對齊器流程共用。

模型程式碼來自固定 commit 的 ``moss-transcribe-diarize`` 套件（不走
``trust_remote_code``），權重固定 HF revision（``weights.REPO_REVISIONS``）。
torch / transformers 一律延遲匯入：只有主機 GPU worker 與免安裝模式的執行緒池會用到。

Windows：torch 沒有 Flash SDPA，memory-efficient kernel 又不接受 ``enable_gqa``，
transformers 5.x 在無遮罩時送 GQA → 退回 math kernel，prefill 顯存 O(L²)
（37.6 分鐘音檔要配置 53 GiB）。因此註冊 ``sdpa_win`` 注意力實作繞過（lab E7）。
"""

from __future__ import annotations

import copy
import gc
import re
from collections import deque
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from app.core.config import get_settings
from app.provider.local.weights import (
    MOSS_MODEL_ID,
    load_pretrained,
    notice_if_missing,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

ATTN_IMPLEMENTATION = "sdpa_win"
SAMPLE_RATE = 16000
MAX_LENGTH = 131072                # 模型上下文上限（prompt + 生成）
AUDIO_TOKENS_PER_SECOND = 12.5     # Whisper 50 Hz → 編碼器 stride 2 → 4 倍時間合併
OUTPUT_TOKENS_PER_SECOND = 12      # 生成預算；實測中文對話約 6、日文 ASMR 約 5 token/秒
MARKER_TOKENS_PER_SECOND = 2.0     # 每 2 秒一個時間標記，最多 4 位數
_EXPECTED_OUTPUT_TOKENS_PER_SECOND = 8.0  # 決定單次長度時保留的生成空間（實測 5–6）
# 每秒音訊在一次推論中佔用的 token（prompt＋預留生成）；上下文與顯存估算共用
_PASS_TOKENS_PER_SECOND = (AUDIO_TOKENS_PER_SECOND + MARKER_TOKENS_PER_SECOND
                           + _EXPECTED_OUTPUT_TOKENS_PER_SECOND)

# 單次可處理長度的顯存估算（lab E7 實測兩點線性擬合：37.6 分 6.53 GiB、51.8 分 8.05 GiB）
_WEIGHTS_GIB = 1.67
_GIB_PER_K_TOKENS = 0.111
_VRAM_HEADROOM_GIB = 2.5           # 桌面與其他程式佔用、配置器碎片
_MIN_VRAM_SINGLE_PASS_SECONDS = 300.0  # 實測 275 秒峰值 2.32 GiB，4 GB 卡即可容納

_NUM = r"\d+(?:\.\d+)?"
# 結束時間戳後面必須緊接下一段的「[起][Sxx]」或輸出結尾，文字裡的 [3]、[2024] 才不會被誤認
_SEGMENT_RE = re.compile(
    rf"\[({_NUM})\]\[S(\d+)\](.*?)\[({_NUM})\](?=\s*(?:\[{_NUM}\]\[S\d+\]|\Z))", re.S)
# 沒有說話者標籤的輸出（上游 issue #40、#61，#134）只剩時間戳可以切段。MOSS 的時間戳都帶兩位
# 小數（例如 [0.48]、[2.00]），文字裡的 [3]、[2024] 是整數，不會被當成時間戳
_TIME = r"\d+\.\d+"
_UNTAGGED_SEGMENT_RE = re.compile(
    rf"\[({_TIME})\](.*?)\[({_TIME})\](?=\s*(?:\[{_TIME}\]|\Z))", re.S)
# 帶標籤的段落裡夾著「[迄][起]」：後面沒有標籤的段落被併進了前一段
_UNTAGGED_BOUNDARY_RE = re.compile(rf"\[({_TIME})\]\s*\[({_TIME})\]")
# 進度回報只看段落開頭（後面接說話者標籤）的時間戳
_SEGMENT_START_RE = re.compile(rf"\[({_NUM})\]\[S\d+\]")

_attention_registered = False


# ─── Windows 注意力 ──────────────────────────────────────────────────────

def _repeat_kv(x, n_rep: int):
    b, h, s, d = x.shape
    return x[:, :, None, :, :].expand(b, h, n_rep, s, d).reshape(b, h * n_rep, s, d)


def sdpa_win_attention(module, query, key, value, attention_mask,
                       dropout=0.0, scaling=None, is_causal=None, **kwargs):
    """與 transformers 的 sdpa 介面相同，但避開 GQA 退回 math kernel 的路徑。

    * prefill（q_len>1）：KV 展開成與 query 相同頭數 → memory-efficient kernel
      （L=45000 多約 0.5 GiB，預設路徑會 OOM）
    * decode（q_len==1）：批次矩陣乘法、不複製 KV cache（L=45000 每層 0.63 ms，
      預設 GQA 路徑 5.6 ms）
    """
    import torch
    import torch.nn.functional as F

    groups = int(getattr(module, "num_key_value_groups", 1) or 1)
    if is_causal is None:
        is_causal = getattr(module, "is_causal", True)
    b, h, q_len, d = query.shape

    # 遮罩須能沿 group 維度廣播：單一 query、長度與 KV 相同的 (b, 1, 1, L)；其他形狀走 SDPA
    mask_ok = attention_mask is None or (
        attention_mask.dim() == 4 and attention_mask.shape[1] == 1
        and attention_mask.shape[-2] == 1 and attention_mask.shape[-1] == key.shape[-2])
    if groups > 1 and q_len == 1 and mask_ok:
        # query 頭的排列是 kv*groups+g（與 repeat_kv 一致），reshape 後逐組對應 KV 頭
        q = query.reshape(b, key.shape[1], groups, d)
        scores = torch.matmul(q, key.transpose(-1, -2)).float()
        scores = scores * (scaling if scaling is not None else d ** -0.5)
        if attention_mask is not None:  # (b, 1, 1, L)，沿 group 維度廣播
            if attention_mask.dtype == torch.bool:
                scores = scores.masked_fill(~attention_mask, float("-inf"))
            else:
                scores = scores + attention_mask.float()
        probs = torch.softmax(scores, dim=-1).to(value.dtype)
        out = torch.matmul(probs, value).reshape(b, h, 1, d)
    else:
        if groups > 1:
            key = _repeat_kv(key, groups)
            value = _repeat_kv(value, groups)
        causal = bool(q_len > 1 and attention_mask is None and is_causal)
        out = F.scaled_dot_product_attention(
            query, key, value, attn_mask=attention_mask, dropout_p=dropout, scale=scaling,
            is_causal=causal)
    return out.transpose(1, 2).contiguous(), None


def _register_attention() -> None:
    global _attention_registered
    if _attention_registered:
        return
    from transformers import AttentionInterface, AttentionMaskInterface
    from transformers.masking_utils import sdpa_mask

    AttentionInterface.register(ATTN_IMPLEMENTATION, sdpa_win_attention)
    # 遮罩沿用 sdpa 的實作：無 padding 時回傳 None，不會實體化 L×L 遮罩
    AttentionMaskInterface.register(ATTN_IMPLEMENTATION, sdpa_mask)
    _attention_registered = True


# ─── 長度預算 ────────────────────────────────────────────────────────────

def max_new_tokens_for(duration_seconds: float) -> int:
    """模型預設 5120 只夠短檔；依長度放寬（下限 2048）。上下文剩餘空間由
    generation_budget 依實際 prompt 長度再收斂。"""
    duration = max(float(duration_seconds), 0.0)
    return int(max(2048, duration * OUTPUT_TOKENS_PER_SECOND + 1024))


def generation_budget(prompt_len: int, duration_seconds: float) -> int:
    """本次 generate 的 max_new_tokens：長度預算與上下文剩餘空間取小。

    剩餘空間連一段像樣的輸出都放不下時直接報錯，而不是生成到一半被截斷
    （只會在停用切段又送入超長音檔時發生）。
    """
    room = MAX_LENGTH - int(prompt_len)
    if room < 1024:
        raise ValueError(
            f"音檔過長（{duration_seconds / 60:.0f} 分鐘），超過 MOSS 單次可處理的上下文；"
            "請勿將 local_moss_single_pass_max_seconds 設為 0")
    return min(max_new_tokens_for(duration_seconds), room)


def _total_vram_gib() -> Optional[float]:
    try:
        import torch
        if torch.cuda.is_available():
            return float(torch.cuda.get_device_properties(0).total_memory) / 2**30
    except Exception:
        pass
    return None


def single_pass_limit_seconds() -> float:
    """不查顯卡的單次長度上限（秒）：設定值（使用者給多少就用多少）與上下文上限
    （prompt 加預留的生成空間不超過 131072 token，約 96 分）取小；0＝停用切段。

    列模型能力時用這個：API 行程（Docker 模式的 API 容器沒有顯卡）不 import torch。
    """
    cap = float(get_settings().local_moss_single_pass_max_seconds)
    if cap <= 0:
        return 0.0  # 與 long_audio_split_threshold_seconds 相同：0＝停用切段（使用者自負風險）
    return min(cap, (MAX_LENGTH - 1024) / _PASS_TOKENS_PER_SECOND)


def max_single_pass_seconds() -> float:
    """這台機器上 MOSS 單次推論能處理的最長音檔（秒）；更長的檔分段轉錄。

    依這張顯卡的容量算（:func:`single_pass_seconds_for_vram`）。會 import torch，只在真的要
    轉錄的行程呼叫。
    """
    return single_pass_seconds_for_vram(_total_vram_gib())


def single_pass_seconds_for_vram(total_gib: Optional[float]) -> float:
    """顯卡記憶體共 ``total_gib`` GiB 時，MOSS 單次推論能處理的最長音檔（秒）。

    :func:`single_pass_limit_seconds` 再依顯卡容量收斂（16 GB 約 79 分、12 GB 約 52 分、
    8 GB 約 26 分；估算值至少 300 秒——實測 275 秒峰值 2.32 GiB，4 GB 卡即可容納）。
    查不到容量（None）時不收斂。
    """
    limit = single_pass_limit_seconds()
    if limit <= 0:
        return limit
    if total_gib is not None:
        usable_k_tokens = (total_gib - _VRAM_HEADROOM_GIB - _WEIGHTS_GIB) / _GIB_PER_K_TOKENS
        by_vram = usable_k_tokens * 1000 / _PASS_TOKENS_PER_SECOND
        limit = min(limit, max(_MIN_VRAM_SINGLE_PASS_SECONDS, by_vram))
    return limit


# ─── 輸出解析 ────────────────────────────────────────────────────────────

def parse_output(text: str) -> List[dict]:
    """``[起][Sxx]文字[迄]`` → ``[{Start, End, Speaker, Content}]``。

    說話者 S01 → 0、S02 → 1（與 VibeVoice 的編號一致）；空文字與迄 < 起的片段丟棄。
    沒有說話者標籤的段落沿用前一段的說話者，前面沒有時當成第一位（#134）。
    """
    text = text or ""
    # 第一個說話者標籤之前（整份都沒有標籤時就是全部）沒有說話者可以沿用，當成第一位
    first_tag = _SEGMENT_START_RE.search(text)
    head = text[:first_tag.start()] if first_tag else text
    pieces = [(float(m[1]), 0, m[2], float(m[3])) for m in _UNTAGGED_SEGMENT_RE.finditer(head)]
    untagged = len(pieces)
    if first_tag:
        for m in _SEGMENT_RE.finditer(text, first_tag.start()):
            split = _split_untagged(float(m[1]), m[3], float(m[4]))
            untagged += len(split) - 1
            pieces.extend((start, max(int(m[2]) - 1, 0), body, end) for start, body, end in split)
    if untagged:
        logger.warning(f"MOSS 輸出有 {untagged} 段沒有說話者標籤，沿用前一位說話者")
    return [{"Start": start, "End": end, "Speaker": speaker, "Content": body.strip()}
            for start, speaker, body, end in pieces if body.strip() and end >= start]


def _split_untagged(start: float, body: str, end: float) -> List[Tuple[float, str, float]]:
    """把併進這一段的、沒有說話者標籤的段落拆出來：``A[迄][起]B`` → ``A``、``B``。"""
    pieces = []
    last = 0
    for boundary in _UNTAGGED_BOUNDARY_RE.finditer(body):
        pieces.append((start, body[last:boundary.start()], float(boundary[1])))
        start, last = float(boundary[2]), boundary.end()
    pieces.append((start, body[last:], end))
    return pieces


def latest_segment_start(text: str) -> Optional[float]:
    """文字中最後一個段落開頭（後面接說話者標籤）的時間戳；文字內的 [2024] 等不算。"""
    starts = _SEGMENT_START_RE.findall(text or "")
    return float(starts[-1]) if starts else None


def _make_progress_streamer(tokenizer, duration: float, status_callback: Callable[[str], None],
                            every: int = 256):
    """生成過程中從最近的段落時間戳回報進度（每整分鐘最多一次）。"""
    from transformers.generation.streamers import BaseStreamer

    total_minutes = max(int(round(duration / 60)), 1)

    class _ProgressStreamer(BaseStreamer):
        def __init__(self):
            self._seen_prompt = False
            self._tail: deque = deque(maxlen=64)
            self._count = 0
            self._last_minute = -1

        def put(self, value):
            if not self._seen_prompt:  # 第一次是整段 prompt
                self._seen_prompt = True
                return
            ids = value.reshape(-1).tolist() if hasattr(value, "reshape") else list(value)
            self._tail.extend(ids)
            self._count += len(ids)
            if self._count % every >= len(ids):
                return
            start = latest_segment_start(
                tokenizer.decode(list(self._tail), skip_special_tokens=True))
            if start is None:
                return
            minute = int(start // 60)
            if minute != self._last_minute:
                self._last_minute = minute
                status_callback(f"本機模型：MOSS 轉錄中 {minute}/{total_minutes} 分鐘...")

        def end(self):
            return None

    return _ProgressStreamer()


# ─── 推論 ────────────────────────────────────────────────────────────────

def transcribe(
    wav_path: Path,
    *,
    stopping_criteria=None,
    status_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[List[dict], str]:
    """對 16 kHz mono wav 跑 MOSS，回傳 (片段, 未解析的輸出文字)。

    stopping_criteria 由呼叫端傳入（取消旗標）；被中途停下時輸出不完整，
    呼叫端必須先檢查取消再使用結果。
    """
    import soundfile as sf
    import torch
    try:
        from moss_transcribe_diarize import (
            MossTranscribeDiarizeForConditionalGeneration,
            MossTranscribeDiarizeProcessor,
        )
    except ImportError as e:
        raise RuntimeError(
            "缺少 moss-transcribe-diarize 套件，請依 backend/requirements-standalone.txt 安裝"
            "（av 與 moss-transcribe-diarize 兩行）") from e

    _register_attention()
    duration = float(sf.info(str(wav_path)).duration)
    notice_if_missing(MOSS_MODEL_ID, "MOSS", status_callback)
    processor = load_pretrained(MOSS_MODEL_ID, MossTranscribeDiarizeProcessor.from_pretrained)
    model = None
    try:
        # 照官方 README：dtype="auto" 載入後再轉 bf16（直接指定 dtype 反而 OOM，上游 issue #20）
        model = load_pretrained(
            MOSS_MODEL_ID,
            lambda path: MossTranscribeDiarizeForConditionalGeneration.from_pretrained(
                path, dtype="auto", attn_implementation=ATTN_IMPLEMENTATION),
        ).to(dtype=torch.bfloat16).to("cuda").eval()
        # 推論放在獨立函式裡：返回時輸入特徵、輸出等 GPU 張量都已離開作用域，
        # 下面的 empty_cache 才真的釋放得掉
        text = _generate(model, processor, wav_path, duration, stopping_criteria, status_callback)
    finally:
        del model
        gc.collect()
        torch.cuda.empty_cache()

    return parse_output(text), text


def _generate(model, processor, wav_path: Path, duration: float,
              stopping_criteria, status_callback) -> str:
    import torch
    from moss_transcribe_diarize.inference_utils import (
        DEFAULT_PROMPT,
        build_transcription_messages,
        prepare_inputs,
    )

    device = torch.device("cuda")
    messages = build_transcription_messages(str(wav_path), DEFAULT_PROMPT)
    with torch.amp.autocast("cuda", dtype=torch.bfloat16):
        inputs = prepare_inputs(processor, messages, max_length=MAX_LENGTH,
                                device=device).to(device)
    # generate 的輸出含完整輸入序列（包括任何 padding），以輸入長度切出生成部分
    prompt_len = int(inputs["input_ids"].shape[1])
    max_new_tokens = generation_budget(prompt_len, duration)
    logger.info(f"MOSS 輸入 {prompt_len} tokens（音檔 {duration:.0f}s），"
                f"max_new_tokens={max_new_tokens}")

    generation_config = copy.deepcopy(model.generation_config)
    generation_config.max_new_tokens = max_new_tokens
    generation_config.do_sample = False
    streamer = (_make_progress_streamer(processor.tokenizer, duration, status_callback)
                if status_callback else None)
    with torch.inference_mode(), torch.amp.autocast("cuda", dtype=torch.bfloat16):
        output_ids = model.generate(
            input_ids=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
            input_features=inputs["input_features"],
            audio_feature_lengths=inputs["audio_feature_lengths"],
            audio_chunk_mapping=inputs["audio_chunk_mapping"],
            generation_config=generation_config,
            stopping_criteria=stopping_criteria,
            streamer=streamer,
        )
    generated = output_ids[0][prompt_len:]
    if int(generated.numel()) >= max_new_tokens:
        logger.warning(f"MOSS 生成達 max_new_tokens={max_new_tokens} 上限，結尾可能被截斷")
    return processor.tokenizer.decode(generated, skip_special_tokens=True).strip()
