param([string]$Version = "0.1.0")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python -m unittest discover -s tests -v
python -m PyInstaller --noconfirm --clean cloakbrowser-profile-manager.spec

$PackageName = "CloakBrowser-Profile-Manager-v$Version-win-x64"
$Stage = Join-Path $Root "dist\$PackageName"
Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item $Stage -ItemType Directory | Out-Null
New-Item (Join-Path $Stage "binaries") -ItemType Directory | Out-Null
New-Item (Join-Path $Stage "profiles") -ItemType Directory | Out-Null
Copy-Item "dist\CloakBrowser-Profile-Manager.exe" $Stage
Copy-Item README.md,LICENSE,THIRD_PARTY_NOTICES.md $Stage
Set-Content (Join-Path $Stage "Install-Browser.cmd") '@echo off
"%~dp0CloakBrowser-Profile-Manager.exe" --install-browser
pause'

$Zip = Join-Path $Root "dist\$PackageName.zip"
Remove-Item $Zip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path "$Stage\*" -DestinationPath $Zip -CompressionLevel Optimal
$Hash = (Get-FileHash $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content (Join-Path $Root "dist\SHA256SUMS.txt") "$Hash  $PackageName.zip"
Write-Output $Zip