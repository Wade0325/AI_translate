import os
import shutil
import uuid
from pathlib import Path
from typing import List, Dict

from fastapi import APIRouter, WebSocket, UploadFile, File, Form, HTTPException

router = APIRouter()

TEMP_UPLOAD_DIR = Path("temp_uploads")
TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# file_metadata_store: Dict[str, Dict] = {}


@router.post("/upload")
async def upload_file_for_transcription(
    file: UploadFile = File(...),
    formats: List[str] = Form(...)
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    file_id = str(uuid.uuid4())
    file_extension = Path(file.filename).suffix
    saved_file_name = f"{file_id}{file_extension}"
    saved_path = TEMP_UPLOAD_DIR / saved_file_name

    print(
        f"Attempting to save uploaded file: {file.filename} with formats: {formats}")

    try:
        with open(saved_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        print(
            f"File '{file.filename}' (saved as '{saved_file_name}') uploaded successfully to '{saved_path}'. Formats: {formats}")
    except Exception as e:
        print(f"Error saving file '{file.filename}': {e}")
        raise HTTPException(
            status_code=500, detail=f"Could not save file '{file.filename}': {e}")
    finally:
        if file.file:
            file.file.close()

    return {
        "message": f"File '{file.filename}' uploaded successfully with formats {formats}.",
        "saved_filename_on_server": saved_file_name,
        "requested_formats": formats
    }
