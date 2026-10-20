<#
OpenCaster setup for Windows.  Double-click setup.bat (it runs this).

  1. Finds Python 3.11 or newer (offers to install it with winget if missing).
  2. Creates a private Python environment outside this folder, so OneDrive
     doesn't sync it: %LOCALAPPDATA%\OpenCaster\venv by default.
  3. Installs (or updates) the packages in requirements.txt.
  4. Adds "OpenCaster" shortcuts to the Desktop and Start Menu, plus an
     "OpenCaster (troubleshoot)" one that keeps a console open for errors.

Safe to run again: it updates the packages and remakes the shortcuts.

  setup.ps1 [-VenvDir DIR] [-ShortcutDir DIR] [-NoShortcuts] [-NoLaunch] [-Yes]
#>
param(
    [string]$VenvDir = (Join-Path $env:LOCALAPPDATA "OpenCaster\venv"),
    [string]$ShortcutDir = "",      # put both shortcuts here instead of Desktop + Start Menu
    [switch]$NoShortcuts,
    [switch]$NoLaunch,
    [switch]$Yes                    # answer yes to every question
)

$ErrorActionPreference = "Stop"
$Repo = $PSScriptRoot
$MinVersion = [version]"3.11"

function Say([string]$text, [string]$color = "Gray") { Write-Host $text -ForegroundColor $color }
function Step([string]$text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Fail([string]$text) {
    Write-Host ""; Write-Host "Setup stopped: $text" -ForegroundColor Red
    exit 1
}
function Ask([string]$question) {
    if ($Yes) { return $true }
    $answer = Read-Host "$question [Y/n]"
    return ($answer -eq "" -or $answer -match "^[Yy]")
}
function AskExplicit([string]$question) {
    # Installing software or opening a browser needs a typed "y", even with -Yes.
    $answer = Read-Host "$question [y/N]"
    return ($answer -match "^[Yy]")
}

# -- 1. Python ------------------------------------------------------------------

function Test-Python([string]$exe, [string[]]$pre = @()) {
    # Returns @{Version; Path} for a usable interpreter, else $null.
    if (-not $exe) { return $null }
    # The Microsoft Store's python.exe stub opens the Store.  (py.exe in
    # WindowsApps is fine: the Python Install Manager puts the launcher there.)
    if ($exe -like "*\WindowsApps\python*.exe") { return $null }
    try {
        $out = & $exe @pre -c "import sys; print('%d.%d' % sys.version_info[:2]); print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out -and $out.Count -ge 2) {
            $v = [version]$out[0]
            if ($v -ge $MinVersion) { return @{ Version = $v; Path = $out[1] } }
        }
    } catch { }
    return $null
}

function Find-Python {
    $launchers = @()
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { $launchers += $cmd.Source }
    $launchers += (Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher\py.exe")
    $launchers += (Join-Path $env:windir "py.exe")
    foreach ($py in ($launchers | Select-Object -Unique)) {
        if (-not (Test-Path $py)) { continue }
        # Versions with the widest package support first, then anything newer.
        foreach ($v in @("3.13", "3.12", "3.14", "3.11")) {
            $found = Test-Python $py @("-$v")
            if ($found) { return $found }
        }
        $found = Test-Python $py @("-3")
        if ($found) { return $found }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        $found = Test-Python $cmd.Source
        if ($found) { return $found }
    }
    foreach ($dir in @("Python313", "Python312", "Python314", "Python311")) {
        $found = Test-Python (Join-Path $env:LOCALAPPDATA "Programs\Python\$dir\python.exe")
        if ($found) { return $found }
    }
    # The Python Install Manager's runtimes
    $managed = Get-ChildItem (Join-Path $env:LOCALAPPDATA "Python\pythoncore-3.*\python.exe") -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending
    foreach ($exe in $managed) {
        $found = Test-Python $exe.FullName
        if ($found) { return $found }
    }
    return $null
}

Say "OpenCaster setup" "Yellow"
Say "Folder: $Repo"

Step "Looking for Python $MinVersion or newer"
$python = Find-Python
if (-not $python) {
    Say "Python $MinVersion+ isn't installed." "Yellow"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget -and (AskExplicit "Install Python 3.13 now with winget (Microsoft's installer)?")) {
        & $winget.Source install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
        $python = Find-Python
    }
    if (-not $python) {
        Say "Install Python from https://www.python.org/downloads/ (tick 'Add python.exe to PATH')," "Yellow"
        Say "then run setup.bat again." "Yellow"
        if (AskExplicit "Open the Python download page now?") { Start-Process "https://www.python.org/downloads/" }
        Fail "Python $MinVersion or newer is needed."
    }
}
Say "Using Python $($python.Version) at $($python.Path)" "Green"

# -- 2. Environment -------------------------------------------------------------

Step "Preparing the OpenCaster environment"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
$VenvPyw = Join-Path $VenvDir "Scripts\pythonw.exe"
if (Test-Path $VenvPy) {
    $existing = Test-Python $VenvPy
    if (-not $existing) {
        Say "The existing environment is broken or too old; rebuilding it." "Yellow"
        Remove-Item -Recurse -Force $VenvDir
    }
}
if (-not (Test-Path $VenvPy)) {
    Say "Creating $VenvDir"
    New-Item -ItemType Directory -Force (Split-Path $VenvDir) | Out-Null
    & $python.Path -m venv $VenvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPy)) { Fail "couldn't create the environment in $VenvDir." }
} else {
    Say "Reusing $VenvDir"
}

# -- 3. Packages ----------------------------------------------------------------

Step "Installing packages (the first time downloads a few hundred MB)"
& $VenvPy -m pip install --upgrade pip --disable-pip-version-check --quiet
if ($LASTEXITCODE -ne 0) { Fail "couldn't update pip (check your internet connection)." }
& $VenvPy -m pip install --upgrade --disable-pip-version-check -r (Join-Path $Repo "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "package installation failed - see the messages above." }

$imports = $false
try {
    & $VenvPy -c "import bleak, numpy, scipy, PySide6.QtMultimedia, PySide6.QtSvg" 2>$null
    $imports = ($LASTEXITCODE -eq 0)
} catch { }
if (-not $imports) { Fail "the packages installed but don't import - try running setup again." }
Say "Packages ready." "Green"

# -- 4. Shortcuts ---------------------------------------------------------------

$Gui = Join-Path $Repo "OpenCaster_GUI.py"
$Icon = Join-Path $Repo "opencaster\gui\assets\opencaster.ico"

function New-Shortcut([string]$path, [string]$target, [string]$arguments, [string]$description) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $target
    $link.Arguments = $arguments
    $link.WorkingDirectory = $Repo
    $link.Description = $description
    if (Test-Path $Icon) { $link.IconLocation = "$Icon,0" }
    $link.Save()
}

if (-not $NoShortcuts) {
    Step "Adding shortcuts"
    if ($ShortcutDir) {
        $folders = @($ShortcutDir)
    } else {
        $folders = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
    }
    foreach ($folder in $folders) {
        New-Item -ItemType Directory -Force $folder | Out-Null
        New-Shortcut (Join-Path $folder "OpenCaster.lnk") $VenvPyw "`"$Gui`"" "Cast spells with your Magic Caster wand"
        Say "  $folder\OpenCaster.lnk"
    }
    # A console that stays open, so startup errors can be read.
    $trouble = $folders[-1]
    New-Shortcut (Join-Path $trouble "OpenCaster (troubleshoot).lnk") "$env:ComSpec" "/k `"`"$VenvPy`" `"$Gui`"`"" "OpenCaster with a console window for error messages"
    Say "  $trouble\OpenCaster (troubleshoot).lnk"
}

# -- Done -----------------------------------------------------------------------

Step "Checks"
$bt = Get-PnpDevice -Class Bluetooth -Status OK -ErrorAction SilentlyContinue
if (-not $bt) {
    Say "No working Bluetooth adapter found. The wand needs Bluetooth LE - turn it on in Settings." "Yellow"
} else {
    Say "Bluetooth adapter found." "Green"
}
if (-not (Test-Path (Join-Path $Repo "media\spellbook.json"))) {
    Say "Optional: put spellbook.json and the media pack in $Repo\media for each spell's own" "Yellow"
    Say "light, sounds and videos (casting works without them)." "Yellow"
}

Write-Host ""
Say "Setup complete. Start OpenCaster from the shortcut, or run:" "Green"
Say "  `"$VenvPy`" `"$Gui`""
if (-not $NoLaunch -and (Ask "Start OpenCaster now?")) {
    Start-Process -FilePath $VenvPyw -ArgumentList "`"$Gui`"" -WorkingDirectory $Repo
}
