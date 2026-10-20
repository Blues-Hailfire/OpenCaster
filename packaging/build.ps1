<#
Build the Windows release: OpenCaster.exe in a folder, zipped.

  packaging\build.ps1 [-Version v1.0.0] [-OutDir DIR] [-VenvDir DIR] [-Python EXE]

Uses its own build environment (requirements.txt + PyInstaller) and writes
outside the repository by default, so OneDrive doesn't sync ~400 MB of
build files:  %LOCALAPPDATA%\OpenCaster\release\
  OpenCaster\                      the app folder (OpenCaster.exe inside)
  OpenCaster-<version>-windows.zip what to upload to a GitHub release
GitHub Actions runs the same steps on a version tag (.github/workflows/release.yml).
#>
param(
    [string]$Version = "dev",
    [string]$OutDir = (Join-Path $env:LOCALAPPDATA "OpenCaster\release"),
    [string]$VenvDir = (Join-Path $env:LOCALAPPDATA "OpenCaster\build-venv"),
    [string]$Python = ""
)

# Native tools (pip, PyInstaller) log to stderr; Windows PowerShell 5.1 turns
# redirected stderr into errors, so exit codes are checked instead.
$ErrorActionPreference = "Continue"
$Repo = Split-Path $PSScriptRoot

function Fail([string]$text) { Write-Host "Build stopped: $text" -ForegroundColor Red; exit 1 }

if (-not $Python) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) { Fail "Python launcher (py) not found; pass -Python C:\path\to\python.exe" }
    $Python = $py.Source
    $PyArgs = @("-3")
} else {
    $PyArgs = @()
}

$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "Creating the build environment in $VenvDir"
    & $Python @PyArgs -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Fail "couldn't create $VenvDir" }
}
& $VenvPy -m pip install --upgrade --disable-pip-version-check --quiet pip
& $VenvPy -m pip install --upgrade --disable-pip-version-check -r (Join-Path $Repo "requirements.txt") pyinstaller
if ($LASTEXITCODE -ne 0) { Fail "package installation failed" }

$Dist = Join-Path $OutDir "dist"
$Work = Join-Path $OutDir "work"
& $VenvPy -m PyInstaller --noconfirm --clean --distpath $Dist --workpath $Work (Join-Path $PSScriptRoot "opencaster.spec")
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller failed" }

$App = Join-Path $Dist "OpenCaster"
Copy-Item (Join-Path $PSScriptRoot "README.txt"), (Join-Path $PSScriptRoot "THIRD_PARTY_NOTICES.txt") $App -Force -ErrorAction Stop
# The spell manifest gives each spell its own wand light and haptics; the
# media pack (sounds, videos) is never shipped - users add it to media\.
$Manifest = Join-Path $Repo "media\spellbook.json"
if (Test-Path $Manifest) {
    New-Item -ItemType Directory -Force (Join-Path $App "media") -ErrorAction Stop | Out-Null
    Copy-Item $Manifest (Join-Path $App "media") -Force -ErrorAction Stop
}
$Zip = Join-Path $OutDir "OpenCaster-$Version-windows.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path $App -DestinationPath $Zip -ErrorAction Stop
Write-Host ""
Write-Host "Built $App\OpenCaster.exe" -ForegroundColor Green
Write-Host "Zip:  $Zip ($([math]::Round((Get-Item $Zip).Length / 1MB)) MB)" -ForegroundColor Green
