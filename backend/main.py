from fastapi import FastAPI
from app.api import transcribe
from app.api import model_manager

from fastapi.middleware.cors import CORSMiddleware
from app.db.database import init_db

init_db()

app = FastAPI()


app.include_router(transcribe.router, prefix="/transcribe",
                   tags=["Transcription"])
app.include_router(model_manager.router, prefix="/settings",
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
