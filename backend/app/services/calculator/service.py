import logging
import sys
from .models import PriceCalculationRequest, PriceCalculationResponse, CalculationItem
from .flows import calculate_price_flow
from typing import List, Optional
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class CalculatorService:
    """
    提供價格估算和性能度量的服務窗口。
    此服務的職責是根據傳入的數據計算費用和匯總性能指標。
    """

    def calculate_metrics(
        self,
        items: List[CalculationItem],
        model: str,
        processing_time_seconds: Optional[float] = None,
        audio_duration_seconds: Optional[float] = None
    ) -> PriceCalculationResponse:
        """
        根據計費項目、模型名稱和性能數據計算所有指標。

        Args:
            items: 計費項目的列表。
            model: 使用的模型名稱。
            processing_time_seconds: 任務總處理時間（秒）。
            audio_duration_seconds: 原始音訊總時長（秒）。

        Returns:
            包含成本、token、性能指標和詳細細目的回應物件。
        """
        total_input_tokens = sum(item.input_tokens for item in items)
        total_output_tokens = sum(item.output_tokens for item in items)
        logger.info(f"執行計算指標，模型: {model}")
        logger.info(
            f"輸入 Tokens: {total_input_tokens}, 輸出 Tokens: {total_output_tokens} (來自 {len(items)} 個項目)")
        logger.info(
            f"輸入指標 - 處理時間: {processing_time_seconds:.4f}s, 音訊時長: {audio_duration_seconds:.4f}s")

        request = PriceCalculationRequest(
            items=items,
            model=model,
            processing_time_seconds=processing_time_seconds,
            audio_duration_seconds=audio_duration_seconds
        )

        response = calculate_price_flow(request)

        logger.info(f"計算完成")
        logger.info(f"輸出費用: {response.cost:.6f}")
        logger.info(f"輸出總 Tokens: {response.total_tokens}")
        if response.processing_time_seconds is not None:
            logger.info(f"輸出處理時間: {response.processing_time_seconds:.4f}s")
        if response.audio_duration_seconds is not None:
            logger.info(f"輸出音訊時長: {response.audio_duration_seconds:.4f}s")

        return response
