import logging
import sys
from pathlib import Path


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

    # 自訂 formatter 以實現路徑顯示和對齊
    class PathAlignedFormatter(logging.Formatter):
        def format(self, record):
            # 從 logger name 中提取路徑資訊
            if hasattr(record, 'name') and record.name:
                # 例如: app.services.vad.flows -> vad/flows.py
                name_parts = record.name.split('.')
                if len(name_parts) >= 3 and name_parts[0] == 'app':
                    # 取最後兩層: services.vad.flows -> vad/flows
                    if len(name_parts) >= 4:
                        path_display = f"{name_parts[-2]}/{record.filename}"
                    else:
                        path_display = f"{name_parts[-1]}/{record.filename}"
                else:
                    path_display = record.filename
            else:
                path_display = record.filename

            # 建立 path:lineno 字串並左對齊到 25 字元
            file_line = f"{path_display}:{record.lineno}"
            record.path_aligned = f"{file_line:<25}"
            return super().format(record)

    # 使用自訂格式
    path_formatter = PathAlignedFormatter(
        '%(asctime)s - %(levelname)s - [%(path_aligned)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    handler.setFormatter(path_formatter)
    logger.addHandler(handler)

    # 防止向上傳播，避免重複輸出
    logger.propagate = False

    return logger
