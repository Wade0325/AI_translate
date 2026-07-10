@echo off
chcp 65001 > nul
REM AI_translate Docker one-click helper (cmd.exe / double-click wrapper).
REM Real logic lives in dc.ps1; this file just forwards args to PowerShell.
REM
REM Usage:
REM   dc                          -> build + up -d
REM   dc start                    -> start without rebuild
REM   dc stop                     -> stop but keep containers
REM   dc down                     -> stop and remove containers
REM   dc restart celery-worker
REM   dc logs backend-service
REM   dc rebuild
REM   dc help

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dc.ps1" %*
exit /b %ERRORLEVEL%
