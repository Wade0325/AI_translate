<#
build_release.ps1 — 產生 Windows 免安裝發布包（build\AI_Translate-<version>-win64.zip）

發布包為「小 zip」：不含 Python 依賴（torch 等由 AI_Translate.exe 首次啟動時
以隨包 uv 依 backend\requirements-standalone.txt 下載佈建），因此體積可控制在
GitHub Releases 的 2 GB 單檔上限內。

用法：
  .\build_release.ps1                       # 本機建置（版本 dev）
  .\build_release.ps1 -Version v1.2.3       # 指定版本（CI 由 tag 傳入）
  .\build_release.ps1 -SkipFrontend         # 跳過 vite build（沿用現有 dist）
#>
param(
    [string]$Version = "dev",
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$BuildDir = Join-Path $Root "build"
$CacheDir = Join-Path $BuildDir "cache"
$StageDir = Join-Path $BuildDir "AI_Translate"

$PythonEmbedVersion = "3.11.9"   # 需與 requirements-standalone 的 wheel 支援版本相符
$PythonEmbedUrl = "https://www.python.org/ftp/python/$PythonEmbedVersion/python-$PythonEmbedVersion-embed-amd64.zip"
$UvUrl = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
$FfmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip"

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Get-Cached($url, $name) {
    New-Item -ItemType Directory -Force $CacheDir | Out-Null
    $path = Join-Path $CacheDir $name
    if (-not (Test-Path $path)) {
        Step "下載 $name"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $path -UseBasicParsing
    }
    return $path
}

function Copy-Tree($src, $dst, $extraArgs) {
    robocopy $src $dst /E /NFL /NDL /NJH /NJS @extraArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy $src -> $dst 失敗 (code $LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
}

# ── 0. 清理 staging ────────────────────────────────────────────────────────
if (Test-Path $StageDir) { Remove-Item -Recurse -Force $StageDir }
New-Item -ItemType Directory -Force $StageDir | Out-Null

# ── 1. 前端建置 ────────────────────────────────────────────────────────────
if (-not $SkipFrontend) {
    Step "建置前端 (vite build)"
    Push-Location (Join-Path $Root "frontend")
    try {
        if (-not (Test-Path "node_modules")) {
            npm ci
            if ($LASTEXITCODE -ne 0) { throw "npm ci 失敗" }
        }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "vite build 失敗" }
    }
    finally { Pop-Location }
}
if (-not (Test-Path (Join-Path $Root "frontend\dist\index.html"))) {
    throw "frontend\dist\index.html 不存在 — 請先執行 npm run build"
}

# ── 2. Python embeddable runtime ──────────────────────────────────────────
Step "佈署 Python $PythonEmbedVersion embeddable runtime"
$pyZip = Get-Cached $PythonEmbedUrl "python-$PythonEmbedVersion-embed-amd64.zip"
$runtime = Join-Path $StageDir "runtime"
Expand-Archive -Path $pyZip -DestinationPath $runtime -Force
# 啟用 site-packages（內容由首次啟動的 uv 佈建）；_pth 不可帶 BOM
Set-Content -Path (Join-Path $runtime "python311._pth") -Encoding ascii -Value @(
    "python311.zip",
    ".",
    "Lib\site-packages",
    "import site"
)
New-Item -ItemType Directory -Force (Join-Path $runtime "Lib\site-packages") | Out-Null

# ── 3. uv 與 ffmpeg ───────────────────────────────────────────────────────
Step "佈署 uv 與 ffmpeg/ffprobe"
$binDir = Join-Path $StageDir "bin"
New-Item -ItemType Directory -Force $binDir | Out-Null

$uvZip = Get-Cached $UvUrl "uv-win64.zip"
$uvTmp = Join-Path $BuildDir "uv-extract"
if (Test-Path $uvTmp) { Remove-Item -Recurse -Force $uvTmp }
Expand-Archive -Path $uvZip -DestinationPath $uvTmp -Force
$uvExe = Get-ChildItem -Path $uvTmp -Recurse -Filter "uv.exe" | Select-Object -First 1
if (-not $uvExe) { throw "uv 壓縮包中找不到 uv.exe" }
Copy-Item $uvExe.FullName (Join-Path $binDir "uv.exe")

$ffZip = Get-Cached $FfmpegUrl "ffmpeg-win64.zip"
$ffTmp = Join-Path $BuildDir "ffmpeg-extract"
if (Test-Path $ffTmp) { Remove-Item -Recurse -Force $ffTmp }
Expand-Archive -Path $ffZip -DestinationPath $ffTmp -Force
foreach ($exe in @("ffmpeg.exe", "ffprobe.exe")) {
    $src = Get-ChildItem -Path $ffTmp -Recurse -Filter $exe | Select-Object -First 1
    if (-not $src) { throw "ffmpeg 壓縮包中找不到 $exe" }
    Copy-Item $src.FullName (Join-Path $binDir $exe)
}

# ── 4. 後端源碼與前端 dist ────────────────────────────────────────────────
Step "複製 backend 源碼與 frontend/dist"
Copy-Tree (Join-Path $Root "backend") (Join-Path $StageDir "backend") @(
    "/XD", ".venv", "__pycache__", "temp_uploads", "vad_artifacts",
    "persistent_uploads", ".cache", ".pytest_cache",
    "/XF", ".env", "*.pyc", "*.db"
)
Copy-Tree (Join-Path $Root "frontend\dist") (Join-Path $StageDir "frontend\dist") @()

# ── 5. 編譯 C# launcher ───────────────────────────────────────────────────
Step "編譯 AI_Translate.exe（內建 csc）"
$csc = Join-Path $env:windir "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { throw "找不到內建 csc.exe（需要 .NET Framework 4.x）" }
$launcherExe = Join-Path $StageDir "AI_Translate.exe"
$launcherSrc = Join-Path $Root "tools\launcher.cs"
& $csc /nologo /optimize "/out:$launcherExe" $launcherSrc
if ($LASTEXITCODE -ne 0) { throw "launcher 編譯失敗" }

# ── 6. README.txt ─────────────────────────────────────────────────────────
Set-Content -Path (Join-Path $StageDir "README.txt") -Encoding utf8 -Value @"
AI_Translate $Version — Windows 免安裝版
==========================================

使用方式
--------
1. 將整個資料夾解壓到任意位置（建議路徑不含中文與空白）
2. 雙擊 AI_Translate.exe
3. 首次啟動會自動下載執行環境（約 3.5 GB，含 PyTorch），
   視網速需要數分鐘到數十分鐘；中斷後重開即續傳
4. 就緒後會自動開啟瀏覽器；關閉黑色視窗即停止程式

功能需求
--------
- Gemini 雲端轉錄：於 Settings 頁填入 Google Gemini API Key 即可使用
- Local 本機轉錄：需 NVIDIA GPU（建議 16GB VRAM）；
  首次使用前於 Settings 頁下載模型權重（約 25 GB，總磁碟需求約 35 GB）

資料位置
--------
所有資料（資料庫、上傳暫存、模型權重）都在本資料夾的 data\ 之下；
升級新版時把舊版 data\ 複製過來即可保留紀錄。

疑難排解
--------
- 若防毒軟體攔截 AI_Translate.exe，可改用手動啟動：
    設定環境變數 APP_MODE=standalone 後執行
    runtime\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
    （工作目錄切到 backend\）
- 連接埠 8000 被占用時會自動改用其他埠，以視窗顯示的網址為準
"@

# ── 7. 結構檢查 ───────────────────────────────────────────────────────────
Step "檢查發布包結構"
$required = @(
    "AI_Translate.exe",
    "README.txt",
    "runtime\python.exe",
    "runtime\python311._pth",
    "bin\uv.exe",
    "bin\ffmpeg.exe",
    "bin\ffprobe.exe",
    "backend\main.py",
    "backend\requirements-standalone.txt",
    "frontend\dist\index.html"
)
foreach ($rel in $required) {
    if (-not (Test-Path (Join-Path $StageDir $rel))) { throw "發布包缺少 $rel" }
}

# ── 8. 打包 ───────────────────────────────────────────────────────────────
$zipName = "AI_Translate-$Version-win64.zip"
$zipPath = Join-Path $BuildDir $zipName
Step "壓縮 $zipName"
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Compress-Archive -Path $StageDir -DestinationPath $zipPath
$sizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host ""
Write-Host "完成：$zipPath（$sizeMB MB）" -ForegroundColor Green
