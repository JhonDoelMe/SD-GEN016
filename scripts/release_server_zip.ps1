<#
.SYNOPSIS
    Збірка та публікація серверного інсталяційного ZIP-архіву (Zero-.env) на сторінку OTA (/ota/api/server/releases).
    Дозволяє поширювати актуальні серверні збірки напряму через https://sdgen.pp.ua/ota/ без ручного створення релізів на Git-хостингах.
#>

param(
    [string]$Changelog = "",
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

$verInfo = Get-Content (Join-Path $RepoRoot "version.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$verName = $verInfo.versionName
$verCode = [int]$verInfo.versionCode

Write-Host "`n[1/2] Збірка чистого інсталяційного ZIP (v$verName, build $verCode)..." -ForegroundColor Cyan
& python scripts/build_install_zip.py
if ($LASTEXITCODE -ne 0) { throw "Не вдалося зібрати інсталяційний ZIP." }

$zipPath = Join-Path $RepoRoot "dist\sd-gen016-v$verName-install.zip"
if (-not (Test-Path $zipPath)) {
    throw "Не знайдено архів: $zipPath"
}

Write-Host "`n[2/2] Публікація серверного інсталяційного ZIP на $OtaBaseUrl..." -ForegroundColor Cyan
$uploadUrl = "$OtaBaseUrl/api/server/releases"
$curlArgs = @(
    "-sS", "-w", "`n%{http_code}",
    "-X", "POST",
    "-H", "X-OTA-Admin-Token: $OtaToken",
    "-F", "file=@$zipPath",
    "-F", "version_code=$verCode",
    "-F", "version_name=$verName",
    "-F", "replace=$($Replace.IsPresent.ToString().ToLower())"
)
if ($Changelog) { $curlArgs += @("--form-string", "changelog=$Changelog") }
$curlArgs += $uploadUrl

$rawResponse = & curl.exe @curlArgs
if ($LASTEXITCODE -ne 0) {
    throw "Помилка мережі при публікації серверного пакета."
}
$lines = $rawResponse -split "`r?`n"
$httpCode = $lines[-1].Trim()
$bodyText = ($lines[0..($lines.Length - 2)] -join "`n").Trim()
if ($httpCode -ne "201" -and $httpCode -ne "200") {
    throw "OTA-сервер повернув HTTP $httpCode`: $bodyText"
}
$resp = $bodyText | ConvertFrom-Json
Write-Host "✅ Серверний інсталяційний пакет v$($resp.version_name) (build $($resp.version_code)) опубліковано!" -ForegroundColor Green
Write-Host "   URL: $($resp.download_url)" -ForegroundColor DarkGray
Write-Host "   SHA-256: $($resp.sha256)" -ForegroundColor DarkGray
