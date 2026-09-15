@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
REM ffmpeg-based audio denoise test script (no Docker/venv needed, just ffmpeg on PATH).
REM Put audio files into tests\audio_input\ then run:
REM   tests\denoise.bat                       -> denoise the example file (我的錄音 17.m4a)
REM   tests\denoise.bat foo.mp3                -> denoise tests\audio_input\foo.mp3
REM   tests\denoise.bat "C:\path\to\file.wav"  -> denoise an absolute/relative path directly
REM Result lands in tests\audio_output\{name}\denoised{ext}.

set "SCRIPT_DIR=%~dp0"
set "INPUT=%~1"
if "%INPUT%"=="" set "INPUT=我的錄音 17.m4a"

set "IN_PATH=%INPUT%"
if not exist "%IN_PATH%" set "IN_PATH=%SCRIPT_DIR%audio_input\%INPUT%"
if not exist "%IN_PATH%" (
    echo [ERROR] input file not found: %INPUT%
    exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [ERROR] ffmpeg not found on PATH.
    exit /b 1
)

for %%F in ("%IN_PATH%") do (
    set "BASENAME=%%~nF"
    set "EXT=%%~xF"
)
set "OUT_DIR=%SCRIPT_DIR%audio_output\!BASENAME!"
if not exist "!OUT_DIR!" mkdir "!OUT_DIR!"
set "OUT_PATH=!OUT_DIR!\denoised!EXT!"

echo [INFO] Denoising: "%IN_PATH%"
echo [INFO] Output:    "!OUT_PATH!"

REM highpass cuts low-frequency rumble; afftdn does the actual FFT-based noise reduction.
REM -nostats -loglevel error keeps output to final result/errors only (no \r progress spam).
ffmpeg -y -nostats -loglevel error -i "%IN_PATH%" -af "highpass=f=100,afftdn=nr=12" "!OUT_PATH!"
if errorlevel 1 (
    echo [ERROR] ffmpeg failed.
    exit /b 1
)

echo [DONE] "!OUT_PATH!"
exit /b 0
