from typing import Dict, List, Optional
from .models import ModelPrice, PriceCalculationRequest, PriceCalculationResponse, CalculationItem

# 模型價格設定
# 將價格移至此處，使其與核心計算邏輯放在一起，並易於管理。
MODEL_PRICES: Dict[str, ModelPrice] = {
    "gemini-1.5-pro-latest": ModelPrice(input_price_per_token=0.00015, output_price_per_token=0.00015),
    "default": ModelPrice(input_price_per_token=0.00015, output_price_per_token=0.00015)
}


def calculate_price_flow(request: PriceCalculationRequest) -> PriceCalculationResponse:
    """
    執行計算價格和性能指標的工作流程。
    此流程會加總所有計費項目的 token，計算總成本，並傳遞性能指標。
    """
    model_price = MODEL_PRICES.get(request.model_name, MODEL_PRICES["default"])

    total_tokens = sum(item.tokens for item in request.items)

    cost = total_tokens * model_price.input_price_per_token

    # 產生詳細的成本細目
    breakdown = [
        {
            "task_name": item.task_name,
            "tokens": item.tokens,
            "cost": item.tokens * model_price.input_price_per_token
        }
        for item in request.items
    ]

    return PriceCalculationResponse(
        total_tokens=total_tokens,
        cost=cost,
        model_name=request.model_name,
        breakdown=breakdown,
        processing_time_seconds=request.processing_time_seconds,
        audio_duration_seconds=request.audio_duration_seconds
    )
