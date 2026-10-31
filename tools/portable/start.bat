@echo off
chcp 65001 > nul
setlocal
rem AI_Translate 的手動啟動（#267）：防毒軟體攔下 AI_Translate.exe 時，改雙擊這個檔案。
rem 做的事和 AI_Translate.exe（tools\launcher.cs）相同：第一次執行時佈建執行環境，再以免安裝模式
rem 啟動伺服器，設的環境變數也相同（tests\unit\test_portable_start_bat.py 檢查兩邊一致）。
rem 不同的是不會自動改用空的埠，也不會自動開啟瀏覽器。
rem 用法：start.bat [埠號]，省略時用 8000。
rem build_release.ps1 把這個檔案改成 CRLF 換行、不帶 BOM 的 UTF-8 放進發布包：帶 BOM 時 cmd 會讀錯
rem 第一行；中文要等第二行的 chcp 65001 之後才讀得對，所以第一、二行只能是 ASCII。

set "ROOT=%~dp0"
set "PYTHON=%ROOT%runtime\python.exe"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"

if not exist "%PYTHON%" goto :incomplete
if not exist "%ROOT%backend\main.py" goto :incomplete

rem ── 首次佈建：和啟動器同一個指令、同一個完成標記 ─────────────────────────
if exist "%ROOT%runtime\.provisioned" goto :run
if not exist "%ROOT%bin\uv.exe" goto :incomplete
echo ═══════════════════════════════════════════════════════
echo  首次啟動：正在下載執行環境（約 3.5 GB，含 PyTorch）
echo  過程視網速需要數分鐘到數十分鐘；中斷後重開會續傳。
echo  沒有 NVIDIA 顯卡的電腦也會下載這些，只用 Gemini 時大部分用不到。
echo ═══════════════════════════════════════════════════════
cd /d "%ROOT%"
"%ROOT%bin\uv.exe" pip install --python "%PYTHON%" --target "%ROOT%runtime\Lib\site-packages" -r "%ROOT%backend\requirements-standalone.txt"
if errorlevel 1 goto :provision_failed
> "%ROOT%runtime\.provisioned" echo %DATE% %TIME%
echo 執行環境佈建完成。

rem ── 啟動伺服器：環境變數和啟動器設的相同 ─────────────────────────────────
:run
set "APP_MODE=standalone"
set "AIT_DATA_DIR=%ROOT%data"
set "AIT_FFMPEG_DIR=%ROOT%bin"
set "AIT_STATIC_DIR=%ROOT%frontend\dist"
set "HF_HOME=%ROOT%data\models\hf_cache"
set "PYTHONIOENCODING=utf-8"

echo 正在啟動 AI_Translate 伺服器（port %PORT%）...
echo 首次啟動需載入模型函式庫，可能需要一兩分鐘，請稍候。
echo 視窗出現「Uvicorn running on http://127.0.0.1:%PORT%」之後，用瀏覽器開啟這個網址。
echo 關閉此視窗即停止 AI_Translate。
echo.
cd /d "%ROOT%backend"
"%PYTHON%" -m uvicorn main:app --host 127.0.0.1 --port %PORT%
if errorlevel 1 goto :server_failed
exit /b 0

:incomplete
echo 找不到 runtime\python.exe、bin\uv.exe 或 backend\ — 請確認 zip 已完整解壓。
goto :fail

:provision_failed
echo.
echo 執行環境佈建失敗（多半是網路中斷）。已下載的部分會保留，
echo 重新執行 start.bat 即可續傳。
goto :fail

:server_failed
echo.
echo 伺服器已停止（結束代碼 %ERRORLEVEL%），請檢視上方日誌；日誌檔在 data\logs。
echo 埠 %PORT% 被占用時，在這個資料夾開啟命令提示字元，執行 start.bat 8001 換一個埠。
goto :fail

:fail
echo 按任意鍵關閉...
pause > nul
exit /b 1
