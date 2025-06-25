# 使用官方 Python 映像
FROM python:3.11-slim

# 設定工作目錄
WORKDIR /app

# 安裝系統依賴，以防某些 Python 套件需要
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 複製 requirements.txt 並安裝依賴
# 這一步會被 Docker 快取，只有在 requirements.txt 變更時才會重新執行
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# 複製整個後端應用程式的程式碼
COPY . .

# 容器將會監聽的 port
EXPOSE 8088 