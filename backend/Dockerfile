FROM python:3.11-slim

WORKDIR /app

# ffmpeg 供音訊轉檔（m4a 等壓縮格式先轉 wav 才能做 VAD）；build-essential 供部分套件編譯
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 先只複製 requirements.txt，讓依賴安裝層被 Docker 快取
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
