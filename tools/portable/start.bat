@echo off
rem Manual start for the portable build (#267): double-click this when antivirus blocks AI_Translate.exe.
rem It runs bin\start.py with the bundled Python; provisioning, the server and all messages live there.
rem Keep this file ASCII-only: cmd misreads the line after one that has multi-byte characters
rem (UTF-8 under chcp 65001) and runs the rest as commands (tests\unit\test_portable_start.py checks).
rem Usage: start.bat [port]   (default 8000)
if exist "%~dp0runtime\python.exe" goto :run
echo runtime\python.exe was not found. Please extract the whole zip again.
pause
exit /b 1

:run
"%~dp0runtime\python.exe" -I -X utf8 "%~dp0bin\start.py" %*
exit /b %ERRORLEVEL%
