@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
REM VAD standalone test pipeline (uses backend\.venv, no Docker needed).
REM Put audio files into tests\audio_input\ then run:
REM   tests\vad_pipeline.bat            -> process all files (silence removal)
REM   tests\vad_pipeline.bat --split    -> also test silence-based splitting
REM   tests\vad_pipeline.bat foo.mp3    -> process one file only
REM Results land in tests\audio_output\{name}\ (listen to speech_only.wav).

set "PYTHON=%~dp0..\backend\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [ERROR] backend\.venv not found. Create it first: python -m venv backend\.venv
    exit /b 1
)

"%PYTHON%" "%~dp0vad_pipeline.py" %*
exit /b %ERRORLEVEL%
