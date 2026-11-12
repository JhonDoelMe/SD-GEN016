<#
.SYNOPSIS
    Автоматичний цикл випуску Android APK для SD-GEN016:
    1. Піднімає та синхронізує версію (version.json, Gradle, Frontend, SW, Backend).
    2. Синхронізує Capacitor-ресурси та збирає підписаний release APK.
    3. Верифікує v2/v3 підпис через apksigner.
    4. Копіює фінальний APK у build-apk/ і автоматично завантажує на OTA-сервер.
#>

param(
    [ValidateSet("patch", "minor", "major", "none")]
    [string]$Bump = "patch",
    [string]$SetVersion = "",
    [int]$VersionCode = 0,
    [string]$Changelog = "",
    [switch]$Mandatory = $false,
    [int]$MinSupportedCode = -1,
    [switch]$Replace = $false,
    [switch]$SkipBuild = $false
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

# 1. Bump & sync version
$bumpArgs = @("scripts/bump-version.js", "--bump", $Bump)
if ($SetVersion) { $bumpArgs += @("--set", $SetVersion) }
if ($VersionCode -gt 0) { $bumpArgs += @("--code", "$VersionCode") }

Write-Host "`n[1/4] Синхронізація версії..." -ForegroundColor Cyan
$verJsonRaw = & node @bumpArgs
if ($LASTEXITCODE -ne 0) { throw "Не вдалося оновити версію." }
$verInfo = $verJsonRaw | ConvertFrom-Json
$verName = $verInfo.versionName
$verCode = [int]$verInfo.versionCode
Write-Host "  Версія релізу: v$verName (versionCode $verCode)" -ForegroundColor Green

$outApkDir = Join-Path $RepoRoot "build-apk"
if (-not (Test-Path $outApkDir)) { New-Item -ItemType Directory -Path $outApkDir | Out-Null }
$finalApkPath = Join-Path $outApkDir "sd-gen016-v$verName-release.apk"

# 2. Sync Capacitor + Build Release APK + Verify Signature
if (-not $SkipBuild) {
    if (-not $env:JAVA_HOME) {
        $jdkCandidates = Get-ChildItem -Path "C:\Program Files\Android\openjdk", "C:\Program Files\Android\Android Studio\jbr", "C:\Program Files\Java" -Filter "java.exe" -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($jdkCandidates) {
            $env:JAVA_HOME = (Split-Path (Split-Path $jdkCandidates.FullName -Parent) -Parent)
            $env:PATH = "$(Split-Path $jdkCandidates.FullName -Parent);$env:PATH"
            Write-Host "  Автовизначено JAVA_HOME: $env:JAVA_HOME" -ForegroundColor DarkGray
        }
    }

    Write-Host "`n[2/4] Синхронізація Capacitor-ресурсів та збірка Release APK..." -ForegroundColor Cyan
    & npm run sync:android
    if ($LASTEXITCODE -ne 0) { throw "Помилка sync:android" }

    Push-Location (Join-Path $RepoRoot "android")
    try {
        & .\gradlew.bat assembleRelease
        if ($LASTEXITCODE -ne 0) { throw "Помилка gradlew assembleRelease" }
    } finally {
        Pop-Location
    }

    $rawReleaseApk = Join-Path $RepoRoot "android\app\build\outputs\apk\release\app-release.apk"
    if (-not (Test-Path $rawReleaseApk)) {
        throw "Зібраний APK не знайдено: $rawReleaseApk"
    }
    Copy-Item -Path $rawReleaseApk -Destination $finalApkPath -Force

    Write-Host "`n[3/4] Перевірка APK підпису..." -ForegroundColor Cyan
    $localProps = Join-Path $RepoRoot "android\local.properties"
    $sdkDir = ""
    if (Test-Path $localProps) {
        $sdkLine = Get-Content $localProps | Where-Object { $_ -match '^sdk\.dir=' } | Select-Object -First 1
        if ($sdkLine) {
            $sdkDir = $sdkLine.Substring(8).Replace("\\", "\").Replace("\:", ":").Trim()
        }
    }
    if (-not $sdkDir -and $env:ANDROID_HOME) { $sdkDir = $env:ANDROID_HOME }
    if ($sdkDir) {
        $btRoot = Join-Path $sdkDir "build-tools"
        $apksigner = Get-ChildItem -Path $btRoot -Filter "apksigner.bat" -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($apksigner) {
            & $apksigner.FullName verify --print-certs $finalApkPath
            if ($LASTEXITCODE -ne 0) { throw "Перевірка підпису apksigner провалилась!" }
        }
    }
} else {
    if (-not (Test-Path $finalApkPath)) {
        throw "APK не знайдено для -SkipBuild: $finalApkPath"
    }
}

# 3. Prepare Changelog
if (-not $Changelog) {
    $gitLogs = & git log -n 5 --pretty=format:"- %s" 2>$null
    if ($LASTEXITCODE -eq 0 -and $gitLogs) {
        $Changelog = ($gitLogs -join "`n")
    } else {
        $Changelog = "Реліз Android APK v$verName"
    }
}

# 4. Upload APK to standalone OTA Server
Write-Host "`n[4/4] Завантаження v$verName (build $verCode) на OTA-сервер ($OtaBaseUrl)..." -ForegroundColor Cyan

$curlArgs = @(
    "-sS", "-w", "`n%{http_code}",
    "-X", "POST",
    "-H", "X-OTA-Admin-Token: $OtaToken",
    "-F", "file=@$finalApkPath",
    "-F", "version_code=$verCode",
    "-F", "version_name=$verName",
    "-F", "changelog=$Changelog",
    "-F", "is_mandatory=$($Mandatory.IsPresent.ToString().ToLower())",
    "-F", "replace=$($Replace.IsPresent.ToString().ToLower())"
)
if ($MinSupportedCode -ge 0) {
    $curlArgs += @("-F", "min_supported_version_code=$MinSupportedCode")
}
$curlArgs += "$OtaBaseUrl/api/releases"

$rawResponse = & curl.exe @curlArgs
if ($LASTEXITCODE -ne 0) {
    throw "Помилка мережі при завантаженні APK на OTA-сервер."
}

$lines = $rawResponse -split "`r?`n"
$httpCode = $lines[-1].Trim()
$bodyText = ($lines[0..($lines.Length - 2)] -join "`n").Trim()

if ($httpCode -ne "201" -and $httpCode -ne "200") {
    throw "OTA-сервер повернув HTTP $httpCode`: $bodyText"
}

$uploaded = $bodyText | ConvertFrom-Json
Write-Host "`n✅ Реліз успішно опубліковано на OTA!" -ForegroundColor Green
Write-Host "   Файл: $($uploaded.file_name) ($([math]::Round($uploaded.file_size / 1MB, 2)) МБ)"
Write-Host "   SHA-256: $($uploaded.sha256)"
Write-Host "   Фіксована сторінка (для пересилки): $($uploaded.landing_url)" -ForegroundColor Yellow
Write-Host "   Пряме фіксоване посилання APK:     $($uploaded.download_url)" -ForegroundColor Yellow
