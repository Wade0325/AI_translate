<#
build_release.ps1 — 產生 Windows 免安裝發布包（build\AI_Translate-<version>-win64.zip）

發布包為「小 zip」：不含 Python 依賴（torch 等由 AI_Translate.exe 首次啟動時
以隨包 uv 依 backend\requirements-standalone.txt 下載佈建），因此體積可控制在
GitHub Releases 的 2 GB 單檔上限內。

用法：
  .\build_release.ps1                       # 本機建置（版本 dev）
  .\build_release.ps1 -Version v1.2.3       # 指定版本（CI 由 tag 傳入）
  .\build_release.ps1 -SkipFrontend         # 跳過 vite build（沿用現有 dist）

要在 git 的工作目錄裡、裝好 git 才能建置：後端只取已 commit 的檔案（第 4 步）。
#>
param(
    [string]$Version = "dev",
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1 畫進度條時，Invoke-WebRequest 下載很慢（ffmpeg 的 zip 要 4 分鐘，關掉之後
# 和 curl 差不多），Expand-Archive 與 Compress-Archive 也會變慢。只在這個腳本裡有效，不影響呼叫端
$ProgressPreference = "SilentlyContinue"
$Root = $PSScriptRoot
$BuildDir = Join-Path $Root "build"
$CacheDir = Join-Path $BuildDir "cache"
$StageDir = Join-Path $BuildDir "AI_Translate"
# 發布包附的第三方授權全文（#274），說明在 tools\portable\THIRD_PARTY_NOTICES.txt
$LicensesDir = Join-Path $Root "tools\portable\licenses"

# 下載的檔案都釘版並驗 SHA-256（Get-Verified）；tests/unit/test_release_pins.py 檢查有釘住。
# Python embeddable：3.11.9 是 3.11 最後一個有 Windows 檔案的版本（之後的 3.11.x 只發原始碼）。
# SHA-256 是下載後自己算的：python.org 沒公布這個檔案的 SHA-256，只有 MD5 與大小，兩者都對得上，
# GPG 簽章也驗過（#266）
$PythonEmbedVersion = "3.11.9"   # 需與 requirements-standalone 的 wheel 支援版本相符
$PythonEmbedSha256 = "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"
$PythonEmbedAsset = "python-$PythonEmbedVersion-embed-amd64.zip"
$PythonEmbedUrl = "https://www.python.org/ftp/python/$PythonEmbedVersion/$PythonEmbedAsset"
# uv：和 CI（.github/workflows/ci.yml 的 docker job）同一版；SHA-256 抄自 release 附的
# uv-x86_64-pc-windows-msvc.zip.sha256，和下載後自己算的相同。升版時和 ci.yml 一起換，
# tests/unit/test_release_pins.py 檢查兩邊一致
$UvVersion = "0.12.23"
$UvSha256 = "75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90"
$UvAsset = "uv-x86_64-pc-windows-msvc.zip"
$UvUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/$UvAsset"
# ffmpeg：BtbN 的 LGPL build，和 CI（.github/workflows/ci.yml）同一個，釘版並驗 SHA-256（#17、#129）。
# 用月底的日期 tag 釘版（BtbN 只承諾月底版保留兩年）；升版時和 ci.yml 一起換，
# tests/unit/test_ffmpeg_pin.py 檢查兩邊一致
$FfmpegTag = "autobuild-2026-09-30-13-08"
$FfmpegBuild = "ffmpeg-n9.0.2-17-g2a571b6068"
$FfmpegSha256 = "6b264b9e6019103f601d98c292bd332fd87acf1c5e941ddff4fb71760fe63432"
$FfmpegAsset = "$FfmpegBuild-win64-lgpl-9.0.zip"
$FfmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/$FfmpegTag/$FfmpegAsset"
# 這個 build 的原始碼（#274）：FFmpeg 的 commit 就是 $FfmpegBuild 裡 -g 後面那一段的完整寫法；BtbN 建置腳本
# 的 commit 是 $FfmpegTag 這個 tag 指向的 commit。建置不用，發版時 tools/ffmpeg_sources.py 讀這兩個值，
# 把原始碼打包成 GitHub Release 的附件，tools/portable/THIRD_PARTY_NOTICES.txt 也寫著它們。
# 升版時和上面一起換，並更新 THIRD_PARTY_NOTICES.txt（tests/unit/test_third_party_notices.py 檢查）
$FfmpegCommit = "2a571b606854520cf89804d8030c8b328e621689"
$BtbnCommit = "6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b"

# 後端只打包這些路徑（白名單），而且只從 git 取已經 commit 的版本（第 4 步的 git archive，#266）。
# 執行需要的只有這些：Docker、型別檢查與開發用的檔案（Dockerfile、typings/、requirements-dev.txt
# 等）不打包。tools/portable_zip.py 也拿這份清單檢查 zip 的 backend/：保持一行一個雙引號字串的寫法
$BackendPaths = @(
    "backend/main.py",
    "backend/requirements-standalone.txt",
    "backend/app"
)

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Get-SHA256($path) { (Get-FileHash -Algorithm SHA256 $path).Hash.ToLowerInvariant() }

# 下載到 build\cache 並驗 SHA-256，回傳檔案路徑。快取裡已經有、雜湊也對時直接用；雜湊不符時
# （上次下載中斷、檔案壞掉或被換掉）刪掉重新下載，不沿用。新下載的仍然不符就刪掉並停止建置
function Get-Verified($url, $name, $sha256) {
    New-Item -ItemType Directory -Force $CacheDir | Out-Null
    $path = Join-Path $CacheDir $name
    if (Test-Path $path) {
        $cached = Get-SHA256 $path
        if ($cached -eq $sha256) { return $path }
        Write-Host "快取裡的 $name 的 SHA-256 不符（$cached），刪掉重新下載" -ForegroundColor Yellow
        Remove-Item -Force $path
    }
    Step "下載 $name"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    # 先下載到 .part，驗過才改名：中斷的下載不會以正式的檔名留在快取裡
    $part = "$path.part"
    Invoke-WebRequest -Uri $url -OutFile $part -UseBasicParsing
    $actual = Get-SHA256 $part
    if ($actual -ne $sha256) {
        Remove-Item -Force $part
        throw "$name 的 SHA-256 不符：預期 $sha256，實際 $actual（$url）"
    }
    Move-Item -Force $part $path
    return $path
}

# 下載來的元件自己附的授權檔，要和 tools\portable\licenses\ 裡 commit 的那份相同（#274）：升版後授權文字
# 變了就停下來，更新 licenses\ 與 THIRD_PARTY_NOTICES.txt 再建置。不計換行（Windows 的 checkout 是 CRLF）；
# 用 -cne：PowerShell 的 -ne 比較字串時不分大小寫
function Assert-SameText($actual, $expected) {
    $a = [IO.File]::ReadAllText($actual) -replace "`r`n", "`n"
    $e = [IO.File]::ReadAllText($expected) -replace "`r`n", "`n"
    if ($a -cne $e) {
        throw "$actual 和 $expected 的內容不同：元件升版後授權文字變了，更新 tools\portable\licenses\ 與 THIRD_PARTY_NOTICES.txt"
    }
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
$pyZip = Get-Verified $PythonEmbedUrl $PythonEmbedAsset $PythonEmbedSha256
$runtime = Join-Path $StageDir "runtime"
Expand-Archive -Path $pyZip -DestinationPath $runtime -Force
Assert-SameText (Join-Path $runtime "LICENSE.txt") (Join-Path $LicensesDir "python\LICENSE.txt")
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

# 快取的檔名帶版本：release 的檔名沒有版本，升版後不會誤用快取裡的舊版
$uvZip = Get-Verified $UvUrl "uv-$UvVersion-$UvAsset" $UvSha256
$uvTmp = Join-Path $BuildDir "uv-extract"
if (Test-Path $uvTmp) { Remove-Item -Recurse -Force $uvTmp }
Expand-Archive -Path $uvZip -DestinationPath $uvTmp -Force
$uvExe = Get-ChildItem -Path $uvTmp -Recurse -Filter "uv.exe" | Select-Object -First 1
if (-not $uvExe) { throw "uv 壓縮包中找不到 uv.exe" }
Copy-Item $uvExe.FullName (Join-Path $binDir "uv.exe")
# 雜湊只保證是當初釘的那個檔案；再確認它真的是 $UvVersion，免得升版時版本號和雜湊只換了一個
$uvReported = & (Join-Path $binDir "uv.exe") --version
if ($LASTEXITCODE -ne 0 -or "$uvReported" -notmatch "^uv $([regex]::Escape($UvVersion))(\s|$)") {
    throw "bin\uv.exe 回報的版本是「$uvReported」，應該是 $UvVersion"
}

$ffZip = Get-Verified $FfmpegUrl $FfmpegAsset $FfmpegSha256
$ffTmp = Join-Path $BuildDir "ffmpeg-extract"
if (Test-Path $ffTmp) { Remove-Item -Recurse -Force $ffTmp }
Expand-Archive -Path $ffZip -DestinationPath $ffTmp -Force
foreach ($exe in @("ffmpeg.exe", "ffprobe.exe")) {
    $src = Get-ChildItem -Path $ffTmp -Recurse -Filter $exe | Select-Object -First 1
    if (-not $src) { throw "ffmpeg 壓縮包中找不到 $exe" }
    Copy-Item $src.FullName (Join-Path $binDir $exe)
}
# BtbN 的 LGPL build 附的 LICENSE.txt 是 FFmpeg 的 COPYING.LGPLv3
Assert-SameText (Join-Path $ffTmp "$([IO.Path]::GetFileNameWithoutExtension($FfmpegAsset))\LICENSE.txt") (Join-Path $LicensesDir "ffmpeg\COPYING.LGPLv3.txt")

# ── 4. 後端源碼與前端 dist ────────────────────────────────────────────────
Step "複製 backend 源碼與 frontend/dist"
# 後端從 git 取 $BackendPaths 已 commit 的版本（git archive），不從工作目錄複製（#266）：
# 沒進版控的東西（執行期資料夾裡使用者的音檔、.env 的 API 金鑰、資料庫、虛擬環境與快取）
# 一律進不了發布包，不必逐項排除，也不會因為排除清單漏了一項就被打包。
# CI 建置前會在 backend/ 放進這些資料，建好後檢查 zip（tools/portable_zip.py，#256）：漏進來就紅燈
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "找不到 git：後端從 git 取檔，要在 git 的工作目錄裡、裝好 git 才能建置"
}
# 白名單裡有還沒 commit 的改動或新檔時停下來：發布包只會有已 commit 的版本，
# 繼續建置的話，打包出來的程式和工作目錄裡的不一樣
$uncommitted = git -C $Root status --porcelain --untracked-files=all -- $BackendPaths
if ($LASTEXITCODE -ne 0) { throw "git status 失敗：$Root 不是 git 的工作目錄？" }
if ($uncommitted) {
    throw ("後端有還沒 commit 的改動，發布包只取已 commit 的版本；先 commit 或 stash 再建置：`n" +
        ($uncommitted -join "`n"))
}
$backendZip = Join-Path $BuildDir "backend-archive.zip"
if (Test-Path $backendZip) { Remove-Item -Force $backendZip }
git -C $Root archive --format=zip -o $backendZip HEAD -- $BackendPaths
if ($LASTEXITCODE -ne 0) { throw "git archive 失敗：$($BackendPaths -join ', ')" }
Expand-Archive -Path $backendZip -DestinationPath $StageDir -Force
Copy-Tree (Join-Path $Root "frontend\dist") (Join-Path $StageDir "frontend\dist") @()
# 版本號只在建置時注入（#85）：寫進發布包的 backend\VERSION，後端讀它（backend/app/core/version.py）。
# PowerShell 5.1 的 utf8 會加 BOM；版本號只有 ASCII，所以用 ascii
Set-Content -Path (Join-Path $StageDir "backend\VERSION") -Value $Version -Encoding ascii

# 授權（#274）：Mimiji 自己的 LICENSE 與 NOTICE，以及第三方元件的聲明與授權全文（tools\portable\）。
# 加上 .txt，使用者雙擊就能用記事本開。THIRD_PARTY_NOTICES.txt 的 {VERSION} 換成版本號（指向這一版的
# GitHub Release，ffmpeg 的原始碼附在那裡），寫成帶 BOM、CRLF 的 UTF-8，舊版記事本才不會當成系統碼頁
Step "複製授權文件（LICENSE、NOTICE、THIRD_PARTY_NOTICES、licenses）"
Copy-Item (Join-Path $Root "LICENSE") (Join-Path $StageDir "LICENSE.txt")
Copy-Item (Join-Path $Root "NOTICE") (Join-Path $StageDir "NOTICE.txt")
$notices = [IO.File]::ReadAllText((Join-Path $Root "tools\portable\THIRD_PARTY_NOTICES.txt"), [Text.Encoding]::UTF8)
if (-not $notices.Contains("{VERSION}")) { throw "tools\portable\THIRD_PARTY_NOTICES.txt 沒有 {VERSION}" }
$notices = $notices.Replace("{VERSION}", $Version) -replace "`r?`n", "`r`n"
[IO.File]::WriteAllText((Join-Path $StageDir "THIRD_PARTY_NOTICES.txt"), $notices, (New-Object Text.UTF8Encoding $true))
Copy-Tree $LicensesDir (Join-Path $StageDir "licenses") @()

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
- Local 本機轉錄：需 NVIDIA GPU（16GB VRAM 可一次處理約 70 分鐘，顯存較小時自動切段）；
  首次使用前於 Settings 頁下載模型權重（預設模型約 3.7 GB；選用模型另需約 21 GB）

資料位置
--------
所有資料（資料庫、上傳暫存、模型權重）都在本資料夾的 data\ 之下；
升級新版時把舊版 data\ 複製過來即可保留紀錄。

更新
----
程式不會自己檢查或下載更新。目前的版本號在 Settings 頁的 About；
新版本請到 https://github.com/Wade0325/AI_translate/releases 下載。

疑難排解
--------
- 若防毒軟體攔截 AI_Translate.exe，可改用手動啟動：
    設定環境變數 APP_MODE=standalone 後執行
    runtime\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
    （工作目錄切到 backend\）
- 連接埠 8000 被占用時會自動改用其他埠，以視窗顯示的網址為準
"@

# ── 7. 結構檢查 ───────────────────────────────────────────────────────────
# CI 也拿這份清單檢查 zip（tools/portable_zip.py 直接讀這裡）：保持一行一個雙引號字串的寫法
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
    "backend\VERSION",
    "backend\requirements-standalone.txt",
    "frontend\dist\index.html",
    "LICENSE.txt",
    "NOTICE.txt",
    "THIRD_PARTY_NOTICES.txt",
    "licenses\ffmpeg\COPYING.LGPLv3.txt",
    "licenses\ffmpeg\COPYING.GPLv3.txt",
    "licenses\ffmpeg\libraries.txt",
    "licenses\ffmpeg\rust-crates.txt",
    "licenses\python\LICENSE.txt",
    "licenses\uv\LICENSE-MIT.txt",
    "licenses\uv\LICENSE-APACHE.txt",
    "licenses\uv\crates.txt",
    "licenses\frontend\npm-packages.txt"
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
