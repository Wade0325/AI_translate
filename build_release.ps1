<#
build_release.ps1 — 產生 Windows 免安裝發布包（build\Mimiji-<version>-win64.zip）

發布包為「小 zip」：不含 Python 依賴（torch 等由 Mimiji.exe 首次啟動時
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
# 產品名稱（#26）：發布包的資料夾、exe 與 zip 的檔名都用它（Mimiji\Mimiji.exe、Mimiji-<版本>-win64.zip）。
# 啟動器的視窗標題與 exe 的產品名稱寫在 tools\launcher.cs 的 AppName；tools/portable_zip.py 檢查 zip 的
# 名稱，tests/unit/test_portable_zip.py 檢查各處一致
$ProductName = "Mimiji"
$StageDir = Join-Path $BuildDir $ProductName
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

# exe 的檔案版本（#277）：Windows 的版本資訊只收 4 個數字，建置時注入的版本號（#85）卻可能是
# v0.1.0-rc.1、dev 這類文字，所以照下面換成數字：
#   - 寫成 vX.Y.Z（v 可省略，後面可以接 -rc.1、-beta.1 或 +…）：取 X.Y.Z，第四個數字一律是 0。
#     預發布的標記不進檔案版本：v0.1.0-rc.1 與 v0.1.0 都是 0.1.0.0
#   - 其他（dev、ci，或不是上面的寫法）：0.0.0.0
# 完整的版本號照原樣寫進產品版本，「內容 → 詳細資料」看得到。X、Y、Z 有一個超過 65534 時停止建置
# （組件版本每一段最大 65534），不默默寫成別的數字。只認 0-9：.NET 的 \d 連全形與其他文字的數字也算
function ConvertTo-FileVersion([string]$version) {
    if ($version -notmatch '^v?([0-9]+)\.([0-9]+)\.([0-9]+)([-+].*)?$') { return "0.0.0.0" }
    $parts = foreach ($digits in $Matches[1], $Matches[2], $Matches[3]) {
        if ($digits.Length -gt 5 -or [int]$digits -gt 65534) {
            throw "版本號 $version 裡的 $digits 超過 65534，exe 的版本資訊放不下"
        }
        [int]$digits
    }
    return "$($parts -join '.').0"
}

# 和 tools\launcher.cs 一起編譯的 C# 檔：組件版本、檔案版本與產品版本（#277）。內建 csc 沒有從命令列給版本號
# 的參數，所以建置時產生這個檔；產品名稱、檔案描述與著作權固定寫在 launcher.cs。版本號放進 C# 的逐字字串
# （@"…"），裡面的 " 寫成 ""
function New-VersionInfoSource([string]$version) {
    $number = ConvertTo-FileVersion $version
    $text = $version.Replace('"', '""')
    return (@(
        "// Generated by build_release.ps1 (#277). Not in version control.",
        "[assembly: System.Reflection.AssemblyVersion(""$number"")]",
        "[assembly: System.Reflection.AssemblyFileVersion(""$number"")]",
        "[assembly: System.Reflection.AssemblyInformationalVersion(@""$text"")]",
        ""
    ) -join "`r`n")
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

# 首次佈建時，啟動器先用 runtime\python.exe 執行它把 torch 下載到本機（斷線後可以接著下載，#303），
# 再讓 uv 從那裡安裝
Copy-Item (Join-Path $Root "tools\portable\prefetch_wheels.py") (Join-Path $binDir "prefetch_wheels.py")

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
# 圖示與版本資訊（#277）：/win32icon 嵌進 tools\portable\mimiji.ico（換圖示時換掉這個檔即可：要有 16、32、48
# 與 256 像素）；版本號寫在 build\launcher-version.cs（New-VersionInfoSource）一起編譯。csc 照這些組件屬性
# 產生 Windows 的版本資訊，「內容 → 詳細資料」顯示的就是它們
Step "編譯 $ProductName.exe（內建 csc，帶圖示與版本資訊）"
$csc = Join-Path $env:windir "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { throw "找不到內建 csc.exe（需要 .NET Framework 4.x）" }
$launcherExe = Join-Path $StageDir "$ProductName.exe"
$launcherSrc = Join-Path $Root "tools\launcher.cs"
$launcherIcon = Join-Path $Root "tools\portable\mimiji.ico"
$versionSrc = Join-Path $BuildDir "launcher-version.cs"
[IO.File]::WriteAllText($versionSrc, (New-VersionInfoSource $Version), (New-Object Text.UTF8Encoding $true))
& $csc /nologo /optimize "/win32icon:$launcherIcon" "/out:$launcherExe" $launcherSrc $versionSrc
if ($LASTEXITCODE -ne 0) { throw "launcher 編譯失敗" }

# ── 6. README.txt 與手動啟動（start.bat、bin\start.py）──────────────────
# 內容在 tools\portable\（#267）。不論 checkout 的換行是什麼，一律寫成 CRLF：記事本與 cmd 都認得。
# README.txt 寫成帶 BOM 的 UTF-8，舊版記事本才不會當成系統碼頁；start.bat 只有 ASCII、不帶 BOM，
# cmd 會把 BOM 當成第一行指令的一部分。不用 Set-Content：PowerShell 5.1 與 7 的 utf8 一個帶 BOM、一個不帶。
# start.bat 用隨包的 Python 執行 bin\start.py，佈建、啟動與中文訊息都在那裡（cmd 讀錯中文行）
Step "寫入 README.txt 與手動啟動"
function Write-PortableText($name, $text, [bool]$bom) {
    $text = $text -replace "`r?`n", "`r`n"
    [IO.File]::WriteAllText((Join-Path $StageDir $name), $text, (New-Object Text.UTF8Encoding $bom))
}
$portableDir = Join-Path $Root "tools\portable"
$readme = [IO.File]::ReadAllText((Join-Path $portableDir "README.txt"), [Text.Encoding]::UTF8)
if (-not $readme.Contains("{VERSION}")) { throw "tools\portable\README.txt 沒有 {VERSION}" }
Write-PortableText "README.txt" ($readme.Replace("{VERSION}", $Version)) $true
Write-PortableText "start.bat" ([IO.File]::ReadAllText((Join-Path $portableDir "start.bat"), [Text.Encoding]::UTF8)) $false
Copy-Item (Join-Path $portableDir "start.py") (Join-Path $binDir "start.py")

# ── 7. 結構檢查 ───────────────────────────────────────────────────────────
# CI 也拿這份清單檢查 zip（tools/portable_zip.py 直接讀這裡）：保持一行一個雙引號字串的寫法
Step "檢查發布包結構"
$required = @(
    "Mimiji.exe",
    "README.txt",
    "start.bat",
    "bin\start.py",
    "runtime\python.exe",
    "runtime\python311._pth",
    "bin\uv.exe",
    "bin\prefetch_wheels.py",
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
$zipName = "$ProductName-$Version-win64.zip"
$zipPath = Join-Path $BuildDir $zipName
Step "壓縮 $zipName"
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Compress-Archive -Path $StageDir -DestinationPath $zipPath
$sizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host ""
Write-Host "完成：$zipPath（$sizeMB MB）" -ForegroundColor Green
