import logging
import sys


def setup_logger(name: str = None) -> logging.Logger:
    """
    設定統一的 logger 配置

    Args:
        name: logger 名稱，如果為 None 則使用呼叫模組的名稱

    Returns:
        配置好的 logger 實例
    """
    logger = logging.getLogger(name)

    # 如果 logger 已經有 handlers，直接返回（避免重複設定）
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    # 建立 console handler
    handler = logging.StreamHandler(sys.stdout)

    # 建立統一的格式
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # 防止向上傳播，避免重複輸出
    logger.propagate = False

    return logger
