<#
.SYNOPSIS
    AI_translate Docker 一鍵管理腳本（本機 Windows 單一環境）。

.DESCRIPTION
    包裝 docker compose 常用動作：
      * 自動偵測 docker compose v2 / 舊版 docker-compose v1
      * 啟動前檢查 Docker Desktop 是否已啟動、.env 是否存在
      * up 預設帶 --build -d，完成後顯示 ps 摘要

.EXAMPLE
    .\dc.ps1                 # build + up -d（第一次 / 改程式後）
    .\dc.ps1 start           # 只啟動，不 build（最快）
    .\dc.ps1 stop            # 停止但保留容器，下次 start 秒起
    .\dc.ps1 down            # 停止並移除容器
    .\dc.ps1 restart celery-worker
    .\dc.ps1 logs backend-service
    .\dc.ps1 rebuild         # --no-cache 重新 build 並重啟
    .\dc.ps1 ps
    .\dc.ps1 help
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'start', 'stop', 'down', 'restart', 'logs', 'rebuild', 'ps', 'status', 'help', '')]
    [string]$Action = 'up',

    [Parameter(Position = 1)]
    [string]$Service = '',

    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding           = [System.Text.Encoding]::UTF8
} catch { }

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptRoot

$ComposeFile = 'docker-compose.yml'
$EnvFile     = '.env'

function Write-Info ([string]$msg) { Write-Host "[INFO ] $msg" -ForegroundColor Cyan }
function Write-Ok   ([string]$msg) { Write-Host "[ OK  ] $msg" -ForegroundColor Green }
function Write-Err  ([string]$msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Show-Help {
    Write-Host @"
============================================================
  AI_translate Docker 一鍵管理腳本
============================================================

用法：
  .\dc.ps1 [Action] [Service] [-NoBuild]

Action（預設 up）：
  up        build + up -d            例：.\dc.ps1
  start     只啟動，不 build          例：.\dc.ps1 start
  stop      只停止，保留容器          例：.\dc.ps1 stop
  down      停止並移除容器            例：.\dc.ps1 down
  restart   重啟服務（可指定服務）     例：.\dc.ps1 restart celery-worker
  logs      追蹤 logs                例：.\dc.ps1 logs backend-service
  rebuild   --no-cache 重 build + up  例：.\dc.ps1 rebuild
  ps/status 顯示容器狀態
  help      顯示說明

網址：前端 http://localhost:5173  ｜  API 文件 http://localhost:8000/docs
"@
}

function Resolve-ComposeCommand {
    $null = & docker compose version 2>$null
    if ($LASTEXITCODE -eq 0) { return @('docker', 'compose') }

    $legacy = Get-Command docker-compose -ErrorAction SilentlyContinue
    if ($legacy) { return @('docker-compose') }

    throw "找不到 docker compose (v2) 或 docker-compose (v1)，請先安裝 Docker Desktop。"
}

function Test-DockerRunning {
    $null = & docker info 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker 引擎未啟動。請先打開 Docker Desktop，等出現綠色 'Engine running' 再執行。"
    }
}

function Invoke-Compose([string[]]$ComposeArgs) {
    $all = @() + $composeCmd + @('--env-file', $EnvFile, '-f', $ComposeFile) + $ComposeArgs
    Write-Info ("執行: " + ($all -join ' '))
    & $all[0] $all[1..($all.Length - 1)]
    if ($LASTEXITCODE -ne 0) { throw "命令執行失敗 (exit=$LASTEXITCODE): $($all -join ' ')" }
}

function Show-Endpoints {
    Write-Ok "Frontend -> http://localhost:5173"
    Write-Ok "API 文件 -> http://localhost:8000/docs"
}

if ($Action -eq 'help') { Show-Help; exit 0 }
if ($Action -eq '')     { $Action = 'up' }

try {
    Test-DockerRunning
    $composeCmd = Resolve-ComposeCommand

    if (-not (Test-Path (Join-Path $ScriptRoot $EnvFile))) {
        throw "$EnvFile 不存在。請複製 .env.example 為 .env 並填入 POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB。"
    }

    Write-Info "Action = $Action | Compose = $ComposeFile | Env = $EnvFile"

    switch ($Action) {
        'up' {
            $upArgs = @('up', '-d')
            if (-not $NoBuild) { $upArgs += '--build' }
            Invoke-Compose $upArgs
            Write-Ok "服務已啟動，現在狀態:"
            Invoke-Compose @('ps')
            Show-Endpoints
            Write-Info "看即時 log:  .\dc.ps1 logs"
        }
        'start' {
            Invoke-Compose @('up', '-d', '--no-build')
            Write-Ok "服務已啟動，現在狀態:"
            Invoke-Compose @('ps')
            Show-Endpoints
        }
        'stop' {
            Invoke-Compose @('stop')
            Write-Ok "已停止容器（保留，下次 .\dc.ps1 start 秒起）"
        }
        'down' {
            Invoke-Compose @('down')
            Write-Ok "已停止並移除容器。"
        }
        'restart' {
            $rsArgs = @('restart')
            if ($Service) { $rsArgs += $Service }
            Invoke-Compose $rsArgs
            Write-Ok ("已重啟: " + $(if ($Service) { $Service } else { '所有服務' }))
        }
        'logs' {
            $logArgs = @('logs', '--tail=200', '-f')
            if ($Service) { $logArgs += $Service }
            Write-Info "Ctrl+C 結束 follow"
            Invoke-Compose $logArgs
        }
        'rebuild' {
            Write-Info "Step 1/3: build --no-cache"
            Invoke-Compose @('build', '--no-cache')
            Write-Info "Step 2/3: down"
            Invoke-Compose @('down')
            Write-Info "Step 3/3: up -d"
            Invoke-Compose @('up', '-d')
            Write-Ok "Rebuild 完成。狀態:"
            Invoke-Compose @('ps')
        }
        { $_ -eq 'ps' -or $_ -eq 'status' } {
            Invoke-Compose @('ps')
        }
        default {
            Write-Err "未知 Action: $Action"
            Show-Help
            exit 1
        }
    }
}
catch {
    Write-Err $_.Exception.Message
    exit 1
}
