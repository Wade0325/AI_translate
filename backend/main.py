from fastapi import FastAPI
from app.api import model_manager
from app.api import transcription  # 更改此處

from fastapi.middleware.cors import CORSMiddleware
from app.db.database import init_db

init_db()

app = FastAPI(title="AI Voice Transcription API", version="1.0.0")


# 更新路由設定
app.include_router(transcription.router, prefix="/api/v1/transcribe",
                   tags=["Transcription"])
app.include_router(model_manager.router,
                   prefix="/api/v1/model-manager",
                   tags=["Model Settings"])


origins = [
    "http://localhost:8000",
    "http://localhost:3000",
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["DELETE", "GET", "POST", "PUT"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
