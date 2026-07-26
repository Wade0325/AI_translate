@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
set HF_HOME=D:\AI_translate\models\hf_cache
REM VibeVoice-ASR speaker diarization test pipeline (uses backend\.venv).
REM Put audio files into tests\audio_input\ then run:
REM   tests\diarization_pipeline.bat                 -> process all files
REM   tests\diarization_pipeline.bat foo.wav         -> one file only
REM   tests\diarization_pipeline.bat --gpu-mem 9GiB  -> lower GPU weight cap if OOM
REM Results land in tests\audio_output\{name}\ (listen to speaker_XX.wav).

set "PYTHON=%~dp0..\backend\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [ERROR] backend\.venv not found. Create it first: python -m venv backend\.venv
    exit /b 1
)

"%PYTHON%" "%~dp0diarization_pipeline.py" %*
exit /b %ERRORLEVEL%
