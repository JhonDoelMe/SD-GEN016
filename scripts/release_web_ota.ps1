<#
.SYNOPSIS
    Швидкий випуск Web-OTA бандлу (HTML/JS/CSS ZIP) для SD-GEN016 Android без перезбірки APK:
    1. За бажанням піднімає версію (versionName + versionCode/webBuild).
    2. Синхронізує Web-асети через `npm run sync:android` (включаючи /frontend/ сумісність).
    3. Пакує `android/app/src/main/assets/public/` у ZIP і публікує на OTA-сервер (/ota/api/web/releases).
#>

param(
    [ValidateSet("patch", "minor", "major", "none")]
    [string]$Bump = "patch",
    [string]$SetVersion = "",
    [int]$WebBuild = 0,
    [int]$MinNativeCode = 27,
    [string]$Changelog = "",
    [switch]$Mandatory = $false,
    [switch]$Replace = $false
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Load-DotEnvFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $idx = $trimmed.IndexOf("=")
        if ($idx -lt 1) { continue }
        $k = $trimmed.Substring(0, $idx).Trim()
        $v = $trimmed.Substring($idx + 1).Trim().Trim('"').Trim("'")
        if (-not [Environment]::GetEnvironmentVariable($k)) {
            [Environment]::SetEnvironmentVariable($k, $v)
        }
    }
}

Load-DotEnvFile (Join-Path $RepoRoot ".ota.env")

$OtaBaseUrl = [Environment]::GetEnvironmentVariable("OTA_BASE_URL")
if (-not $OtaBaseUrl) { $OtaBaseUrl = "https://sdgen.pp.ua/ota" }
$OtaBaseUrl = $OtaBaseUrl.TrimEnd("/")

$OtaToken = [Environment]::GetEnvironmentVariable("OTA_ADMIN_TOKEN")
if (-not $OtaToken) {
    throw "OTA_ADMIN_TOKEN не знайдено. Задайте його у файлі .ota.env або змінній оточення OTA_ADMIN_TOKEN."
}

$bumpArgs = @("scripts/bump-version.js", "--bump", $Bump)
if ($SetVersion) { $bumpArgs += @("--set", $SetVersion) }
if ($WebBuild -gt 0) { $bumpArgs += @("--code", "$WebBuild") }

Write-Host "`n[1/3] Синхронізація версії Web-OTA..." -ForegroundColor Cyan
$verJsonRaw = & node @bumpArgs
if ($LASTEXITCODE -ne 0) { throw "Не вдалося оновити версію." }
$verInfo = $verJsonRaw | ConvertFrom-Json
$verName = $verInfo.versionName
$targetWebBuild = [int]$verInfo.versionCode
Write-Host "  Версія Web-OTA: v$verName (web_build $targetWebBuild, min_native $MinNativeCode)" -ForegroundColor Green

Write-Host "`n[2/3] Синхронізація та пакування Web-бандлу..." -ForegroundColor Cyan
& npm run sync:android
if ($LASTEXITCODE -ne 0) { throw "Помилка npm run sync:android" }

$publicDir = Join-Path $RepoRoot "android\app\src\main\assets\public"
if (-not (Test-Path (Join-Path $publicDir "index.html"))) {
    throw "Не знайдено index.html у $publicDir"
}

$outDir = Join-Path $RepoRoot "build-apk"
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
$zipPath = Join-Path $outDir "sd-gen016-web-v$verName.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

$pyScript = @"
import pathlib, zipfile
root = pathlib.Path(r'$publicDir')
out = pathlib.Path(r'$zipPath')
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for p in sorted(root.rglob('*')):
        if p.is_file():
            zf.write(p, p.relative_to(root).as_posix())
"@
& python -c $pyScript
if ($LASTEXITCODE -ne 0) { throw "Помилка створення ZIP-бандлу" }

$zipSizeKb = [Math]::Round((Get-Item $zipPath).Length / 1024, 1)
Write-Host "  Створено бандл: $zipPath ($zipSizeKb КБ)" -ForegroundColor Green

Write-Host "`n[3/3] Публікація Web-OTA на $OtaBaseUrl..." -ForegroundColor Cyan
$uploadUrl = "$OtaBaseUrl/api/web/releases"
$curlArgs = @(
    "-sS", "-w", "`n%{http_code}",
    "-X", "POST",
    "-H", "X-OTA-Admin-Token: $OtaToken",
    "-F", "file=@$zipPath",
    "-F", "web_build=$targetWebBuild",
    "-F", "version_name=$verName",
    "-F", "min_native_version_code=$MinNativeCode",
    "-F", "is_mandatory=$($Mandatory.IsPresent.ToString().ToLower())",
    "-F", "replace=$($Replace.IsPresent.ToString().ToLower())"
)
if ($Changelog) { $curlArgs += @("-F", "changelog=$Changelog") }
$curlArgs += $uploadUrl

$rawResponse = & curl.exe @curlArgs
if ($LASTEXITCODE -ne 0) {
    throw "Помилка мережі при публікації Web-OTA."
}
$lines = $rawResponse -split "`r?`n"
$httpCode = $lines[-1].Trim()
$bodyText = ($lines[0..($lines.Length - 2)] -join "`n").Trim()
if ($httpCode -ne "201" -and $httpCode -ne "200") {
    throw "OTA-сервер повернув HTTP $httpCode`: $bodyText"
}
$resp = $bodyText | ConvertFrom-Json
Write-Host "✅ Web-OTA бандл v$($resp.version_name) (web_build $($resp.web_build)) опубліковано!" -ForegroundColor Green
Write-Host "   SHA-256: $($resp.sha256)" -ForegroundColor DarkGray
