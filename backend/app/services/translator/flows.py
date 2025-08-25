import time
import uuid
from google.genai import Client as GeminiGenaiClient

from app.provider.google.gemini import GeminiClient, translate_text
from app.services.calculator.models import CalculationItem
from app.services.calculator.service import CalculatorService
from app.utils.logger import setup_logger
from .models import TranslationRequest, TranslationTaskResult, TranslationResponse

logger = setup_logger(__name__)


def _perform_translation(
    client: GeminiGenaiClient,
    model: str,
    prompt: str,
    text_to_translate: str
) -> TranslationTaskResult:
    """執行實際的翻譯 API 呼叫"""
    try:
        # 將 API 呼叫委託給 gemini.py 中的輔助函式
        result = translate_text(
            client=client,
            model=model,
            prompt=prompt,
            text_to_translate=text_to_translate
        )

        # 將回傳的字典轉換為 TranslationTaskResult 物件
        return TranslationTaskResult(
            success=result["success"],
            translated_text=result["translated_text"],
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            total_tokens_used=result.get("total_tokens", 0)
        )

    except Exception as e:
        logger.error(f"翻譯流程 _perform_translation 發生未預期的錯誤: {e}", exc_info=True)
        return TranslationTaskResult(
            success=False,
            translated_text=f"[[翻譯流程錯誤: {str(e)}]]",
            total_tokens_used=0
        )


def translation_flow(request: TranslationRequest) -> TranslationResponse:
    """
    處理翻譯請求的主流程
    """
    start_time = time.time()
    task_uuid = uuid.uuid4()
    logger.info(
        f"開始翻譯任務 {task_uuid}，來源語言: {request.source_lang}，目標語言: {request.target_lang}")

    # 1. 初始化 Gemini Client
    client = GeminiClient(api_key=request.api_key)

    # 2. 建立 Prompt
    prompt = request.prompt
    if not prompt:
        prompt = f"Translate the following text from {request.source_lang} to {request.target_lang}. Your response should contain only the translated text, without any additional explanations, introductions, or formatting."

    # 3. 執行翻譯
    result = _perform_translation(
        client=client,
        model=request.model,
        prompt=prompt,
        text_to_translate=request.text
    )

    # 4. 計算費用
    calculator = CalculatorService()
    calc_item = CalculationItem(
        model=request.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens
    )
    cost, cost_breakdown = calculator.calculate_cost([calc_item])

    processing_time = time.time() - start_time

    # 5. 建立並回傳回應
    response_payload = {
        "task_uuid": task_uuid,
        "translated_text": result.translated_text if result.success else f"翻譯失敗: {result.translated_text}",
        "tokens_used": result.total_tokens_used,
        "cost": cost,
        "model": request.model,
        "source_language": request.source_lang,
        "target_language": request.target_lang,
        "processing_time_seconds": processing_time,
        "cost_breakdown": cost_breakdown
    }

    response = TranslationResponse(**response_payload)

    logger.info(
        f"翻譯任務 {task_uuid} 完成，耗時: {processing_time:.2f} 秒，費用: ${cost:.6f}")

    return response
