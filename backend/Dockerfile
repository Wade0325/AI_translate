FROM python:3.11-slim

WORKDIR /app

# ffmpeg 供音訊轉檔（m4a 等壓縮格式先轉 wav 才能做 VAD）；build-essential 供部分套件編譯
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 先只複製依賴清單，讓依賴安裝層被 Docker 快取。requirements.txt 以 -r 引用
# requirements-base.txt 與 requirements-ml.txt，所以要一起複製
COPY requirements*.txt ./
RUN pip install --no-cache-dir --upgrade pip

# INSTALL_ML=true（預設，dc.bat 的建置）裝完整依賴；CI 傳 false，只裝 base、不裝 torch 系列。
# 完整依賴在 CI 只解析版本、不安裝，改這一段要在本機重建確認（docs/agents/merging.md 的例外）
ARG INSTALL_ML=true
RUN case "$INSTALL_ML" in \
        true) req=requirements.txt ;; \
        false) req=requirements-base.txt ;; \
        *) echo "INSTALL_ML 只能是 true 或 false，收到：$INSTALL_ML" >&2; exit 1 ;; \
    esac \
    && pip install --no-cache-dir -r "$req"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
