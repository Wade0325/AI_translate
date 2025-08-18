@echo off
SETLOCAL

REM --- 將路徑變數的定義移至此處 ---
REM 定義相對於腳本位置的路徑
SET "SCRIPT_DIR=%~dp0"
SET "VENV_ACTIVATE_SCRIPT=%SCRIPT_DIR%backend\.venv\Scripts\activate.bat"
SET "VENV_DEACTIVATE_SCRIPT=%SCRIPT_DIR%backend\.venv\Scripts\deactivate.bat"
REM **** 修正 START ****
REM Celery 和 FastAPI 的工作目錄都應該是 backend
SET "BACKEND_DIR=%SCRIPT_DIR%backend"
REM **** 修正 END ****
SET "FRONTEND_APP_DIR=%SCRIPT_DIR%frontend"
REM --- 路徑變數定義結束 ---

REM 檢查第一個參數
IF /I "%1"=="celery" (
    echo Starting Celery...

    REM 檢查虛擬環境激活腳本是否存在
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

    REM **** 修正 START ****
    REM 檢查 backend 目錄是否存在
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
    REM 使用正確的應用程式路徑，並加上 -P gevent 參數
    celery -A app.celery.celery:celery_app worker -l INFO -P gevent
    REM **** 修正 END ****

    echo Celery process finished or was interrupted.
    echo Returning to original directory...
    popd
    
    GOTO DeactivateAndEnd

) ELSE IF /I "%1"=="app" (
    echo Starting FastAPI app...

    REM 檢查虛擬環境激活腳本是否存在
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

    REM **** 修正 START ****
    REM 檢查 backend 目錄是否存在
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
    REM **** 修正 END ****

    echo Starting FastAPI app: uvicorn main:app --reload
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

    echo FastAPI app process finished or was interrupted.
    echo Returning to original directory...
    popd

    GOTO DeactivateAndEnd

) ELSE IF /I "%1"=="react" (
    echo Starting React project...

    REM 檢查 Frontend 應用程式目錄是否存在
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
    
    REM React 專案不需要停用虛擬環境，直接跳到結束
    GOTO EndScript

) ELSE (
    echo Invalid or no parameter provided.
    echo To start Celery, run: %~n0 celery
    echo To start FastAPI app, run: %~n0 app
    echo To start React project, run: %~n0 react
    GOTO EndScript
)

:DeactivateAndEnd
REM 檢查 VIRTUAL_ENV 環境變數是否已定義 (activate.bat 通常會設置此變數)
IF DEFINED VIRTUAL_ENV (
  echo Deactivating virtual environment...
  CALL "%VENV_DEACTIVATE_SCRIPT%"
  IF ERRORLEVEL 1 (
      echo Failed to deactivate virtual environment.
  )
) ELSE (
  echo Virtual environment was not active or already deactivated.
)

:EndScript
ENDLOCAL
echo Script finished.
