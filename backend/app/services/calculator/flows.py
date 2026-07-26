from typing import Dict
from .models import ModelPrice, PriceCalculationRequest, PriceCalculationResponse

# 模型價格設定（每百萬 token）；不在表內的模型套用 default。
# 注意：此表需涵蓋 frontend/src/constants/modelConfig.js 中所有可選模型，
# 否則該模型會以 default（flash 級）價格入帳，且不會出現在 Billing 頁的計費表。
MODEL_PRICES: Dict[str, ModelPrice] = {
    "gemini-3.5-flash": ModelPrice(
        input_text=1.50,
        input_audio=1.50,
        output_text=9.00
    ),
    # 依 Gemini 3 Pro 級（<=200k prompt）定價；官方調價時請同步更新
    "gemini-3.1-pro-preview": ModelPrice(
        input_text=2.00,
        input_audio=2.00,
        output_text=12.00
    ),
    "gemini-2.5-pro": ModelPrice(
        input_text=1.25,
        input_audio=1.25,
        output_text=10.00
    ),
    "gemini-2.5-flash": ModelPrice(
        input_text=0.30,
        input_audio=1.00,
        output_text=2.50
    ),
    # 本地模型不產生 API 費用
    "vibevoice-qwen3-asr": ModelPrice(
        input_text=0.0,
        input_audio=0.0,
        output_text=0.0
    ),
    "default": ModelPrice(
        input_text=0.30,
        input_audio=1.00,
        output_text=2.50
    )
}


def calculate_price_flow(request: PriceCalculationRequest) -> PriceCalculationResponse:
    """
    執行計算價格和性能指標的工作流程。
    此流程會根據每個計費項目的內容類型和 token 數計算成本。
    """
    model_price = MODEL_PRICES.get(request.model, MODEL_PRICES["default"])

    total_cost = 0.0
    total_input_cost = 0.0
    total_output_cost = 0.0
    total_tokens = 0
    breakdown = []

    for item in request.items:
        item_tokens = item.input_tokens + item.output_tokens
        total_tokens += item_tokens

        if item.content_type == 'audio':
            item_input_cost = (item.input_tokens / 1_000_000) * \
                model_price.input_audio
        else:
            item_input_cost = (item.input_tokens / 1_000_000) * \
                model_price.input_text

        item_output_cost = (item.output_tokens / 1_000_000) * model_price.output_text
        item_cost = item_input_cost + item_output_cost

        total_input_cost += item_input_cost
        total_output_cost += item_output_cost
        total_cost += item_cost

        breakdown.append({
            "task_name": item.task_name,
            "input_tokens": item.input_tokens,
            "output_tokens": item.output_tokens,
            "content_type": item.content_type,
            "cost": item_cost,
            "input_cost": item_input_cost,
            "output_cost": item_output_cost,
        })

    return PriceCalculationResponse(
        total_tokens=total_tokens,
        cost=total_cost,
        input_cost=total_input_cost,
        output_cost=total_output_cost,
        model=request.model,
        breakdown=breakdown,
        processing_time_seconds=request.processing_time_seconds,
        audio_duration_seconds=request.audio_duration_seconds
    )
