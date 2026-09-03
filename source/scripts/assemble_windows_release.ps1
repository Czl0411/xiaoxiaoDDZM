param(
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$sourceRoot = Join-Path $ProjectRoot "source"
$builtApp = Join-Path $sourceRoot "dist\DZMM群聊机器人"
$browserRoot = Join-Path $ProjectRoot "ms-playwright"
$releaseRoot = Join-Path $ProjectRoot "release"
$releaseApp = Join-Path $releaseRoot "DZMM群聊机器人"
$portableZip = Join-Path $releaseRoot "DZMMBot-Portable-win64.zip"

if (-not (Test-Path -LiteralPath $builtApp)) {
    throw "PyInstaller output not found: $builtApp"
}
if (-not (Test-Path -LiteralPath $browserRoot)) {
    throw "Playwright browser directory not found: $browserRoot"
}

if (Test-Path -LiteralPath $releaseApp) {
    Remove-Item -LiteralPath $releaseApp -Recurse -Force
}
if (Test-Path -LiteralPath $portableZip) {
    Remove-Item -LiteralPath $portableZip -Force
}
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
Copy-Item -LiteralPath $builtApp -Destination $releaseApp -Recurse -Force
Copy-Item -LiteralPath $browserRoot -Destination (Join-Path $releaseApp "ms-playwright") -Recurse -Force
Copy-Item -LiteralPath (Join-Path $sourceRoot "发布版使用说明.txt") -Destination $releaseApp -Force
& tar.exe -a -c -f $portableZip -C $releaseRoot (Split-Path -Leaf $releaseApp)
if ($LASTEXITCODE -ne 0) {
    throw "Creating portable ZIP failed with exit code $LASTEXITCODE"
}

Write-Output "portable_zip=$portableZip"
