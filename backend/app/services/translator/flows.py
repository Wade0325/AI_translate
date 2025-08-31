from google.genai import Client as GeminiGenaiClient

from app.provider.google.gemini import translate_text
from app.utils.logger import setup_logger
from .models import TranslationTaskResult

logger = setup_logger(__name__)


def _perform_translation(
    client: GeminiGenaiClient,
    model: str,
    prompt: str,
    text_to_translate: str
) -> TranslationTaskResult:
    """執行實際的翻譯 API 呼叫"""
    try:
        result = translate_text(
            client=client,
            model=model,
            prompt=prompt,
            text_to_translate=text_to_translate
        )

        return TranslationTaskResult(
            success=result["success"],
            translated_text=result["translated_text"],
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            total_tokens=result.get("total_tokens", 0)
        )

    except Exception as e:
        logger.error(f"翻譯流程 _perform_translation 發生未預期的錯誤: {e}", exc_info=True)
        return TranslationTaskResult(
            success=False,
            translated_text=f"[[翻譯流程錯誤: {str(e)}]]",
            total_tokens=0
        )
