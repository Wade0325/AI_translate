<#
.SYNOPSIS
    AI_translate Docker 一鍵管理腳本 (build + up + down + logs ...)

.DESCRIPTION
    包裝 docker compose 常用動作，自動：
      * 偵測 docker compose v2 / 舊版 docker-compose v1
      * 切換 dev / prod 對應的 compose 檔
      * 前置檢查 Docker Desktop 是否啟動、.env.prod 是否存在
      * up 預設帶 --build -d，並在完成後顯示 ps 摘要

.EXAMPLE
    .\dc.ps1                       # prod build + up -d (預設)
    .\dc.ps1 up dev                # dev build + up -d
    .\dc.ps1 up prod -NoBuild      # prod up -d，跳過 build
    .\dc.ps1 down                  # prod down
    .\dc.ps1 down dev              # dev down
    .\dc.ps1 logs                  # prod 全部服務 logs -f
    .\dc.ps1 logs prod backend-service
    .\dc.ps1 restart prod celery-worker
    .\dc.ps1 rebuild               # prod --no-cache rebuild + up -d
    .\dc.ps1 ps                    # 查看狀態
    .\dc.ps1 help                  # 顯示說明
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'start', 'stop', 'down', 'restart', 'logs', 'rebuild', 'ps', 'status', 'help', '')]
    [string]$Action = 'up',

    [Parameter(Position = 1)]
    [ValidateSet('dev', 'prod', '')]
    [string]$Mode = 'prod',

    [Parameter(Position = 2)]
    [string]$Service = '',

    [switch]$Follow,
    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'

# 確保中文輸出在 Windows console 不亂碼
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding           = [System.Text.Encoding]::UTF8
} catch { }

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptRoot

# ---------- 工具函式 ----------
function Write-Info  ([string]$msg) { Write-Host "[INFO ] $msg" -ForegroundColor Cyan }
function Write-Ok    ([string]$msg) { Write-Host "[ OK  ] $msg" -ForegroundColor Green }
function Write-Warn  ([string]$msg) { Write-Host "[WARN ] $msg" -ForegroundColor Yellow }
function Write-Err   ([string]$msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Show-Help {
    Write-Host @"
============================================================
  AI_translate Docker 一鍵管理腳本
============================================================

用法:
  .\dc.ps1 [Action] [Mode] [Service] [-Follow] [-NoBuild]

Action (預設 up):
  up        build + up -d           例: .\dc.ps1 up dev
  start     只啟動(不 build/不重建)  例: .\dc.ps1 start          ← 最常用「我只是要執行」
  stop     只停止(不移除容器)        例: .\dc.ps1 stop           ← 與 start 對應，秒起
  down      停止並移除容器          例: .\dc.ps1 down prod
  restart   重啟服務(可指定服務)     例: .\dc.ps1 restart prod celery-worker
  logs      追蹤 logs (預設 -f)     例: .\dc.ps1 logs prod backend-service
  rebuild   --no-cache rebuild + up 例: .\dc.ps1 rebuild prod
  ps/status 顯示容器狀態           例: .\dc.ps1 ps
  help      顯示說明

Mode (預設 prod):
  prod  -> docker-compose.prod.yml (需要 .env.prod)
  dev   -> docker-compose.dev.yml

旗標:
  -NoBuild   up 時不執行 build
  -Follow    強制 follow logs (logs 動作預設已開)

常用範例:
  .\dc.ps1                                # 一鍵 build+up prod (有改程式 / 第一次部署)
  .\dc.ps1 start                          # 我只是要執行 prod (不 build、最快)
  .\dc.ps1 stop                           # 收工關機前停掉 (容器不刪、下次 start 秒起)
  .\dc.ps1 up dev                         # 一鍵 build+up dev
  .\dc.ps1 logs prod celery-worker        # 看 celery log
  .\dc.ps1 restart prod celery-worker     # 改完 celery 程式重啟
  .\dc.ps1 rebuild                        # 強制 no-cache 重新 build
  .\dc.ps1 down                           # 停掉 prod 全部容器(會移除容器)
"@
}

# ---------- 前置檢查 ----------
function Resolve-ComposeCommand {
    # 優先用 v2 (docker compose)；退回 v1 (docker-compose)
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

function Resolve-ComposeFile([string]$mode) {
    $file = if ($mode -eq 'dev') { 'docker-compose.dev.yml' } else { 'docker-compose.prod.yml' }
    $path = Join-Path $ScriptRoot $file
    if (-not (Test-Path $path)) { throw "找不到 compose 檔案: $path" }

    # prod 必須要有 .env.prod，否則 ${POSTGRES_USER} 變數會展開為空字串
    if ($mode -eq 'prod') {
        $envFile = Join-Path $ScriptRoot '.env.prod'
        if (-not (Test-Path $envFile)) {
            throw ".env.prod 不存在於 $envFile。請依 README 建立，至少包含 POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB / GOOGLE_API_KEY。"
        }
    }
    return $file
}

function Invoke-Compose {
    param(
        [string[]]$ComposeCmd,
        [string]$ComposeFile,
        [string]$EnvFile,
        [string[]]$ComposeArgs
    )
    $prefix = @() + $ComposeCmd
    if ($EnvFile) { $prefix += @('--env-file', $EnvFile) }
    $prefix += @('-f', $ComposeFile)
    $all = $prefix + $ComposeArgs
    Write-Info ("執行: " + ($all -join ' '))
    & $all[0] $all[1..($all.Length - 1)]
    $code = $LASTEXITCODE
    if ($code -ne 0) { throw "命令執行失敗 (exit=$code): $($all -join ' ')" }
}

# ---------- 主流程 ----------
if ($Action -eq 'help' -or $Action -eq '') {
    if ($Action -eq 'help') { Show-Help; exit 0 }
    $Action = 'up'
}

try {
    Test-DockerRunning
    $composeCmd  = Resolve-ComposeCommand
    $composeFile = Resolve-ComposeFile -mode $Mode

    # 兩個 compose 檔目前都 reference .env.prod 的變數做替換，所以都自動帶 --env-file
    $envFile = ''
    $envFileCandidate = Join-Path $ScriptRoot '.env.prod'
    if (Test-Path $envFileCandidate) { $envFile = '.env.prod' }

    Write-Info "Mode = $Mode | Compose file = $composeFile | EnvFile = $(if($envFile){$envFile}else{'(none)'}) | Action = $Action"

    switch ($Action) {
        'up' {
            $upArgs = @('up', '-d')
            if (-not $NoBuild) { $upArgs += '--build' }
            Invoke-Compose -ComposeCmd $composeCmd -ComposeFile $composeFile -EnvFile $envFile -ComposeArgs $upArgs
            Write-Ok "服務已啟動，現在狀態:"
            Invoke-Compose -ComposeCmd $composeCmd -ComposeFile $composeFile -EnvFile $envFile -ComposeArgs @('ps')
            Write-Host ""
            if ($Mode -eq 'prod') {
                Write-Ok "Frontend  -> http://localhost  (Nginx)"
            } else {
                Write-Ok "Frontend  -> http://localhost:5173 (Vite dev)"
                Write-Ok "Backend   -> http://localhost:8000"
            }
            Write-Info "看即時 log:  .\dc.ps1 logs $Mode"
        }

        'start' {
            # up -d --no-build 已能涵蓋:
            #  - 容器已存在且正在跑 -> no-op
            #  - 容器已存在但停止   -> 啟動
            #  - 容器不存在但 image 存在 -> 建立並啟動 (不 build)
            #  - image 也不存在     -> 報錯，提示要先 .\dc.ps1 up
            Invoke-Compose -ComposeCmd $composeCmd -ComposeFile $composeFile -EnvFile $envFile -ComposeArgs @('up', '-d', '--no-build')
            Write-Ok "服務已啟動，現在狀態:"
            Invoke-Compose -ComposeCmd $composeCmd -ComposeFile $composeFile -EnvFile $envFile -ComposeArgs @('ps')
            if ($Mode -eq 'prod') {
                Write-Ok "Frontend  -> http://localhost  (Nginx)"
            } else {
                Write-Ok "Frontend  -> http://localhost:5173 (Vite dev)"
                Write-Ok "Backend   -> http://localhost:8000"
            }
        }

        'stop' {
            Invoke-Compose -ComposeCmd $composeCmd -ComposeFile $composeFile -EnvFile $envFile -ComposeArgs @('stop')
            Write-Ok "已停止 $Mode 環境的容器（容器保留，下次 .\dc.ps1 start 秒起）"
        }

        'down' {
            Invoke-Compose -ComposeCmd $composeCmd -ComposeFile $composeFile -EnvFile $envFile -ComposeArgs @('down')
            Write-Ok "已停止並移除 $Mode 環境的容器。"
        }

        'restart' {
            $rsArgs = @('restart')
            if ($Service) { $rsArgs += $Service }
            Invoke-Compose -ComposeCmd $composeCmd -ComposeFile $composeFile -EnvFile $envFile -ComposeArgs $rsArgs
            Write-Ok ("已重啟: " + ($(if ($Service) { $Service } else { '所有服務' })))
        }

        'logs' {
            $logArgs = @('logs', '--tail=200', '-f')
            if ($Service) { $logArgs += $Service }
            Write-Info "Ctrl+C 結束 follow"
            Invoke-Compose -ComposeCmd $composeCmd -ComposeFile $composeFile -EnvFile $envFile -ComposeArgs $logArgs
        }

        'rebuild' {
            Write-Info "Step 1/3: docker compose build --no-cache"
            Invoke-Compose -ComposeCmd $composeCmd -ComposeFile $composeFile -EnvFile $envFile -ComposeArgs @('build', '--no-cache')

            Write-Info "Step 2/3: docker compose down"
            Invoke-Compose -ComposeCmd $composeCmd -ComposeFile $composeFile -EnvFile $envFile -ComposeArgs @('down')

            Write-Info "Step 3/3: docker compose up -d"
            Invoke-Compose -ComposeCmd $composeCmd -ComposeFile $composeFile -EnvFile $envFile -ComposeArgs @('up', '-d')

            Write-Ok "Rebuild 完成。狀態:"
            Invoke-Compose -ComposeCmd $composeCmd -ComposeFile $composeFile -EnvFile $envFile -ComposeArgs @('ps')
        }

        { $_ -eq 'ps' -or $_ -eq 'status' } {
            Invoke-Compose -ComposeCmd $composeCmd -ComposeFile $composeFile -EnvFile $envFile -ComposeArgs @('ps')
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
