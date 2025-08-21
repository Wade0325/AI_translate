from typing import Dict, List, Optional
from .models import ModelPrice, PriceCalculationRequest, PriceCalculationResponse, CalculationItem

# 模型價格設定（每百萬 token）
MODEL_PRICES: Dict[str, ModelPrice] = {
    "gemini-2.5-flash": ModelPrice(
        input_text=0.30,
        input_audio=1.00,
        output_text=2.50
    ),
    "gemini-1.5-pro-latest": ModelPrice(
        input_text=1.25,  # 假設價格，請根據官方文件更新
        input_audio=2.50,  # 假設價格
        output_text=10.00  # 假設價格
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
    total_tokens = 0
    breakdown = []

    for item in request.items:
        item_cost = 0.0
        item_tokens = item.input_tokens + item.output_tokens
        total_tokens += item_tokens

        # 計算輸入成本
        if item.content_type == 'audio':
            item_cost += (item.input_tokens / 1_000_000) * \
                model_price.input_audio
        else:  # 預設為 text
            item_cost += (item.input_tokens / 1_000_000) * \
                model_price.input_text

        # 計算輸出成本
        item_cost += (item.output_tokens / 1_000_000) * model_price.output_text

        total_cost += item_cost

        breakdown.append({
            "task_name": item.task_name,
            "input_tokens": item.input_tokens,
            "output_tokens": item.output_tokens,
            "content_type": item.content_type,
            "cost": item_cost
        })

    return PriceCalculationResponse(
        total_tokens=total_tokens,
        cost=total_cost,
        model=request.model,
        breakdown=breakdown,
        processing_time_seconds=request.processing_time_seconds,
        audio_duration_seconds=request.audio_duration_seconds
    )
