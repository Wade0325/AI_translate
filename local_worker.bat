@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
set HF_HOME=D:\AI_translate\models\hf_cache
REM Host-side GPU Celery worker for the "local" provider (VibeVoice + Qwen3-ASR).
REM Consumes only the local_asr queue; the Docker celery-worker keeps the default queue.
REM Requires the Docker stack running (dc.bat start) so Redis/Postgres ports are up.
REM Connection settings come from backend\.env (localhost URLs).
REM NOTE: duplicate-run protection is handled by visibility_timeout=12h in celery.py.
REM Do NOT add --prefetch-multiplier=1 here: combined with the solo pool it makes
REM the worker stop consuming the queue (verified 2026-07-11).

set "PYTHON=%~dp0backend\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [ERROR] backend\.venv not found. Create it first: python -m venv backend\.venv
    exit /b 1
)

cd /d "%~dp0backend"
"%PYTHON%" -m celery -A app.celery.celery:celery_app worker -Q local_asr --pool=solo -c 1 --loglevel=info
exit /b %ERRORLEVEL%
