@echo off
chcp 65001 > nul
REM AI_translate Docker 一鍵管理腳本（cmd.exe / 雙擊用包裝）
REM 真正邏輯在 dc.ps1，這個檔只是把參數轉交給 PowerShell。
REM
REM 用法範例:
REM   dc                          -> build + up -d
REM   dc start                    -> 只啟動，不 build
REM   dc stop                     -> 停止但保留容器
REM   dc down                     -> 停止並移除容器
REM   dc restart celery-worker
REM   dc logs backend-service
REM   dc rebuild
REM   dc help

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dc.ps1" %*
exit /b %ERRORLEVEL%
