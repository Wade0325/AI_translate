# AI 語音轉錄工具

這是一個利用 AI 技術進行語音轉錄的專案。前端使用 React，後端使用 Python FastAPI。

## ✨ 功能特色

- **語音上傳**: 支援上傳音訊檔案。
- **語音分離 (VAD)**: 使用 Silero VAD 自動偵測語音活動。
- **語音轉錄**: 使用 Google Gemini 模型進行語音轉文字。
- **字幕生成**: 將轉錄結果生成為字幕檔案。

## 🛠️ 技術棧

- **前端**: React, Vite, Ant Design, Axios
- **後端**: Python, FastAPI, Uvicorn
- **AI / ML**: PyTorch, Silero VAD, Google Gemini
- **容器化**: Docker


### 使用 Docker 執行 (建議)

1.  **Clone 專案庫**:
    ```bash
    git clone <your-repository-url>
    cd <repository-name>
    ```


3.  **啟動服務**:
    在專案根目錄下執行以下指令：
    ```bash
    docker-compose up --build
    ```

4.  **開啟應用**:
    - 前端介面: [http://localhost:8081](http://localhost:8081)
    - 後端 API 文件: [http://localhost:8088/docs](http://localhost:8088/docs)
