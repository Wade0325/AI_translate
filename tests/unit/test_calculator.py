"""
單元測試：費用計算服務
測試範圍：calculator/flows.py 與 calculator/service.py
"""
import pytest
from app.services.calculator.models import (
    CalculationItem,
    PriceCalculationRequest,
    ModelPrice,
)
from app.services.calculator.flows import calculate_price_flow, MODEL_PRICES
from app.services.calculator.service import CalculatorService


# ─── MODEL_PRICES 定義 ───────────────────────────────────────────────────────

class TestModelPricesDefinition:
    def test_default_price_exists(self):
        assert "default" in MODEL_PRICES

    def test_gemini_flash_price_exists(self):
        assert "gemini-2.5-flash" in MODEL_PRICES

    def test_prices_are_positive(self):
        for model_name, price in MODEL_PRICES.items():
            assert price.input_text > 0, f"{model_name} input_text should be positive"
            assert price.input_audio > 0, f"{model_name} input_audio should be positive"
            assert price.output_text > 0, f"{model_name} output_text should be positive"

    def test_audio_price_higher_than_text_input(self):
        """音訊輸入通常比文字輸入貴"""
        for model_name, price in MODEL_PRICES.items():
            assert price.input_audio >= price.input_text, (
                f"{model_name}: audio input should cost >= text input"
            )


# ─── calculate_price_flow ────────────────────────────────────────────────────

class TestCalculatePriceFlow:
    def _make_request(self, items, model="gemini-2.5-flash", **kwargs):
        return PriceCalculationRequest(items=items, model=model, **kwargs)

    def test_single_text_item_cost(self):
        items = [CalculationItem(
            task_name="test",
            input_tokens=1_000_000,
            output_tokens=0,
            content_type="text",
        )]
        req = self._make_request(items)
        result = calculate_price_flow(req)
        # 1M text input tokens = $0.30 for gemini-2.5-flash
        assert abs(result.cost - 0.30) < 1e-6

    def test_single_audio_item_cost(self):
        items = [CalculationItem(
            task_name="audio_test",
            input_tokens=1_000_000,
            output_tokens=0,
            content_type="audio",
        )]
        req = self._make_request(items)
        result = calculate_price_flow(req)
        # 1M audio input tokens = $1.00 for gemini-2.5-flash
        assert abs(result.cost - 1.00) < 1e-6

    def test_output_tokens_cost(self):
        items = [CalculationItem(
            task_name="output_test",
            input_tokens=0,
            output_tokens=1_000_000,
            content_type="text",
        )]
        req = self._make_request(items)
        result = calculate_price_flow(req)
        # 1M output tokens = $2.50 for gemini-2.5-flash
        assert abs(result.cost - 2.50) < 1e-6

    def test_total_tokens_sum(self):
        items = [
            CalculationItem(task_name="t1", input_tokens=100, output_tokens=50, content_type="text"),
            CalculationItem(task_name="t2", input_tokens=200, output_tokens=80, content_type="audio"),
        ]
        req = self._make_request(items)
        result = calculate_price_flow(req)
        assert result.total_tokens == 430

    def test_zero_tokens_returns_zero_cost(self):
        items = [CalculationItem(task_name="zero", input_tokens=0, output_tokens=0)]
        req = self._make_request(items)
        result = calculate_price_flow(req)
        assert result.cost == 0.0
        assert result.total_tokens == 0

    def test_multiple_items_cost_sum(self):
        items = [
            CalculationItem(task_name="t1", input_tokens=500_000, output_tokens=0, content_type="text"),
            CalculationItem(task_name="t2", input_tokens=500_000, output_tokens=0, content_type="text"),
        ]
        req = self._make_request(items)
        result = calculate_price_flow(req)
        # 1M total text input = $0.30
        assert abs(result.cost - 0.30) < 1e-6

    def test_unknown_model_uses_default_price(self):
        items = [CalculationItem(
            task_name="t",
            input_tokens=1_000_000,
            output_tokens=0,
            content_type="text",
        )]
        req = self._make_request(items, model="unknown-model-xyz")
        result = calculate_price_flow(req)
        default_cost = MODEL_PRICES["default"].input_text
        assert abs(result.cost - default_cost) < 1e-6

    def test_response_has_breakdown(self):
        items = [
            CalculationItem(task_name="task1", input_tokens=1000, output_tokens=500, content_type="text"),
            CalculationItem(task_name="task2", input_tokens=2000, output_tokens=1000, content_type="audio"),
        ]
        req = self._make_request(items)
        result = calculate_price_flow(req)
        assert result.breakdown is not None
        assert len(result.breakdown) == 2
        assert result.breakdown[0]["task_name"] == "task1"
        assert result.breakdown[1]["task_name"] == "task2"

    def test_processing_time_preserved(self):
        items = [CalculationItem(task_name="t", input_tokens=100, output_tokens=50)]
        req = self._make_request(items, processing_time_seconds=12.5)
        result = calculate_price_flow(req)
        assert result.processing_time_seconds == 12.5

    def test_audio_duration_preserved(self):
        items = [CalculationItem(task_name="t", input_tokens=100, output_tokens=50)]
        req = self._make_request(items, audio_duration_seconds=60.0)
        result = calculate_price_flow(req)
        assert result.audio_duration_seconds == 60.0

    def test_input_output_cost_sum_equals_total_cost(self):
        items = [
            CalculationItem(task_name="mixed", input_tokens=100_000, output_tokens=50_000, content_type="text"),
        ]
        req = self._make_request(items)
        result = calculate_price_flow(req)
        assert abs(result.input_cost + result.output_cost - result.cost) < 1e-9

    def test_model_name_in_response(self):
        items = [CalculationItem(task_name="t", input_tokens=100, output_tokens=50)]
        req = self._make_request(items, model="gemini-2.5-flash")
        result = calculate_price_flow(req)
        assert result.model == "gemini-2.5-flash"


# ─── CalculatorService ───────────────────────────────────────────────────────

class TestCalculatorService:
    def setup_method(self):
        self.service = CalculatorService()

    def test_calculate_metrics_returns_response(self):
        from app.services.calculator.models import PriceCalculationResponse
        items = [CalculationItem(task_name="t", input_tokens=1000, output_tokens=500)]
        result = self.service.calculate_metrics(
            items=items,
            model="gemini-2.5-flash",
            processing_time_seconds=5.0,
            audio_duration_seconds=30.0,
        )
        assert isinstance(result, PriceCalculationResponse)

    def test_calculate_metrics_sums_tokens(self):
        items = [
            CalculationItem(task_name="a", input_tokens=1000, output_tokens=500),
            CalculationItem(task_name="b", input_tokens=2000, output_tokens=1000),
        ]
        result = self.service.calculate_metrics(
            items=items,
            model="gemini-2.5-flash",
            processing_time_seconds=1.0,
            audio_duration_seconds=10.0,
        )
        assert result.total_tokens == 4500

    def test_calculate_metrics_preserves_processing_time(self):
        items = [CalculationItem(task_name="t", input_tokens=100, output_tokens=50)]
        result = self.service.calculate_metrics(
            items=items,
            model="gemini-2.5-flash",
            processing_time_seconds=42.0,
            audio_duration_seconds=120.0,
        )
        assert result.processing_time_seconds == 42.0
