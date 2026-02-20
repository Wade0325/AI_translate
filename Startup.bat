@echo off
SETLOCAL

REM --- 路徑變數定義 ---
SET "SCRIPT_DIR=%~dp0"
SET "VENV_ACTIVATE_SCRIPT=%SCRIPT_DIR%backend\.venv\Scripts\activate.bat"
SET "BACKEND_DIR=%SCRIPT_DIR%backend"
SET "FRONTEND_APP_DIR=%SCRIPT_DIR%frontend"
REM --- 路徑變數定義結束 ---

REM 如果沒有參數，啟動所有服務
IF "%1"=="" (
    echo ============================================
    echo   Starting All Services in Separate Windows
    echo ============================================
    echo.

    REM 檢查必要的目錄和檔案是否存在
    IF NOT EXIST "%VENV_ACTIVATE_SCRIPT%" (
        echo Error: Virtual environment not found at "%VENV_ACTIVATE_SCRIPT%"
        echo Please create virtual environment first.
        GOTO EndScript
    )
    IF NOT EXIST "%BACKEND_DIR%" (
        echo Error: Backend directory not found at "%BACKEND_DIR%"
        GOTO EndScript
    )
    IF NOT EXIST "%FRONTEND_APP_DIR%" (
        echo Error: Frontend directory not found at "%FRONTEND_APP_DIR%"
        GOTO EndScript
    )

    echo [1/3] Starting Celery Worker...
    start "Celery Worker" cmd /k "cd /d "%BACKEND_DIR%" && call "%VENV_ACTIVATE_SCRIPT%" && echo Starting Celery Worker... && celery -A app.celery.celery:celery_app worker -l INFO -P gevent"

    REM 稍微延遲一下，避免同時啟動造成資源競爭
    timeout /t 2 /nobreak > nul

    echo [2/3] Starting FastAPI Server...
    start "FastAPI Server" cmd /k "cd /d "%BACKEND_DIR%" && call "%VENV_ACTIVATE_SCRIPT%" && echo Starting FastAPI Server... && uvicorn main:app --reload --host 0.0.0.0 --port 8000"

    timeout /t 2 /nobreak > nul

    echo [3/3] Starting React Frontend...
    start "React Frontend" cmd /k "cd /d "%FRONTEND_APP_DIR%" && echo Starting React Frontend... && npm run dev"

    echo.
    echo ============================================
    echo   All services started successfully!
    echo ============================================
    echo.
    echo   - Celery Worker:  Running in separate window
    echo   - FastAPI Server: http://localhost:8000
    echo   - React Frontend: http://localhost:5173
    echo.
    echo   Close this window or press any key to exit.
    pause > nul
    GOTO EndScript
)

REM 檢查第一個參數 (保留單獨啟動功能)
IF /I "%1"=="celery" (
    echo Starting Celery...

    IF NOT EXIST "%VENV_ACTIVATE_SCRIPT%" (
        echo Error: Virtual environment activation script not found at "%VENV_ACTIVATE_SCRIPT%"
        GOTO EndScript
    )
    echo Activating virtual environment from "%VENV_ACTIVATE_SCRIPT%"
    CALL "%VENV_ACTIVATE_SCRIPT%"
    IF ERRORLEVEL 1 (
        echo Failed to activate virtual environment.
        GOTO EndScript
    )

    IF NOT EXIST "%BACKEND_DIR%" (
        echo Error: Backend directory not found at "%BACKEND_DIR%"
        GOTO DeactivateAndEnd
    )
    echo Changing directory to "%BACKEND_DIR%"
    pushd "%BACKEND_DIR%"
    IF ERRORLEVEL 1 (
        echo Failed to change directory to "%BACKEND_DIR%"
        GOTO DeactivateAndEnd
    )

    echo Starting Celery worker: celery -A app.celery.celery:celery_app worker -l INFO -P gevent
    celery -A app.celery.celery:celery_app worker -l INFO -P gevent

    echo Celery process finished or was interrupted.
    echo Returning to original directory...
    popd
    
    GOTO DeactivateAndEnd

) ELSE IF /I "%1"=="app" (
    echo Starting FastAPI app...

    IF NOT EXIST "%VENV_ACTIVATE_SCRIPT%" (
        echo Error: Virtual environment activation script not found at "%VENV_ACTIVATE_SCRIPT%"
        GOTO EndScript
    )
    echo Activating virtual environment from "%VENV_ACTIVATE_SCRIPT%"
    CALL "%VENV_ACTIVATE_SCRIPT%"
    IF ERRORLEVEL 1 (
        echo Failed to activate virtual environment.
        GOTO EndScript
    )

    IF NOT EXIST "%BACKEND_DIR%" (
        echo Error: Backend directory not found at "%BACKEND_DIR%"
        GOTO DeactivateAndEnd
    )
    echo Changing directory to "%BACKEND_DIR%"
    pushd "%BACKEND_DIR%"
    IF ERRORLEVEL 1 (
        echo Failed to change directory to "%BACKEND_DIR%"
        GOTO DeactivateAndEnd
    )

    echo Starting FastAPI app: uvicorn main:app --reload
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

    echo FastAPI app process finished or was interrupted.
    echo Returning to original directory...
    popd

    GOTO DeactivateAndEnd

) ELSE IF /I "%1"=="react" (
    echo Starting React project...

    IF NOT EXIST "%FRONTEND_APP_DIR%" (
        echo Error: Frontend app directory not found at "%FRONTEND_APP_DIR%"
        GOTO EndScript
    )
    echo Changing directory to "%FRONTEND_APP_DIR%"
    pushd "%FRONTEND_APP_DIR%"
    IF ERRORLEVEL 1 (
        echo Failed to change directory to "%FRONTEND_APP_DIR%"
        GOTO EndScript
    )

    echo Starting React project: npm run dev
    npm run dev

    echo React project process finished or was interrupted.
    echo Returning to original directory...
    popd
    
    GOTO EndScript

) ELSE (
    echo.
    echo ============================================
    echo   Startup Script Usage
    echo ============================================
    echo.
    echo   %~n0          - Start ALL services (each in separate window)
    echo   %~n0 celery   - Start Celery worker only
    echo   %~n0 app      - Start FastAPI server only
    echo   %~n0 react    - Start React frontend only
    echo.
    GOTO EndScript
)

:DeactivateAndEnd
IF DEFINED VIRTUAL_ENV (
  echo Deactivating virtual environment...
  CALL "%SCRIPT_DIR%backend\.venv\Scripts\deactivate.bat"
  IF ERRORLEVEL 1 (
      echo Failed to deactivate virtual environment.
  )
) ELSE (
  echo Virtual environment was not active or already deactivated.
)

:EndScript
ENDLOCAL
echo Script finished.
