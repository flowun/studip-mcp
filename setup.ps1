# Stud.IP MCP setup: venv, dependencies, password, test, Claude Desktop config entry to paste.
# Run:  powershell -ExecutionPolicy Bypass -File setup.ps1 [-User <studip-username>]
# Re-run without asking for the password again:  ... -File setup.ps1 -KeepPassword
# The username is remembered in .studip_user (git-ignored) after the first run.
# Use a specific Python for the venv:  ... -File setup.ps1 -Python C:\path\to\python.exe
param(
    [string]$User = "",
    [string]$Python = "",
    [switch]$KeepPassword
)
$ErrorActionPreference = "Stop"
$dir      = $PSScriptRoot
$venv     = Join-Path $dir ".venv"
$py       = Join-Path $venv "Scripts\python.exe"
$server   = Join-Path $dir "studip_mcp.py"
$userFile = Join-Path $dir ".studip_user"

function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)." } }

# Find a real Python >= 3.10 (skips the Microsoft Store "python" alias). Returns the command as an array.
function Find-Python {
    $cands = @()
    if ($Python) { $cands += ,@($Python) }
    if (Get-Command py -ErrorAction SilentlyContinue) { $cands += ,@("py", "-3") }
    foreach ($name in "python", "python3") {
        Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue |
            Where-Object { $_.Source -notlike "*\WindowsApps\*" } |
            ForEach-Object { $cands += ,@($_.Source) }
    }
    $globs = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe",
        "$env:USERPROFILE\anaconda3\python.exe",
        "$env:USERPROFILE\miniconda3\python.exe",
        "$env:LOCALAPPDATA\anaconda3\python.exe",
        "$env:ProgramData\anaconda3\python.exe"
    )
    foreach ($g in $globs) {
        Get-ChildItem $g -ErrorAction SilentlyContinue | Sort-Object FullName -Descending |
            ForEach-Object { $cands += ,@($_.FullName) }
    }
    foreach ($c in $cands) {
        $exe = $c[0]; $rest = @($c | Select-Object -Skip 1)
        try {
            & $exe @rest -c "import sys, venv; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return ,$c }
        } catch { }
    }
    throw "No Python 3.10+ found. Install it from python.org, or pass one with -Python C:\path\to\python.exe"
}

if (-not $User -and (Test-Path $userFile)) { $User = (Get-Content $userFile -Raw).Trim() }
if (-not $User) { $User = (Read-Host "Stud.IP username").Trim() }
if (-not $User) { throw "A Stud.IP username is required." }
Set-Content -Path $userFile -Value $User -NoNewline -Encoding UTF8

if (-not (Test-Path $py)) {
    $base = Find-Python
    $baseExe = $base[0]; $baseArgs = @($base | Select-Object -Skip 1)
    Write-Host "[1/5] Creating virtual environment in $venv (using $($base -join ' '))"
    if (Test-Path $venv) { Remove-Item $venv -Recurse -Force }  # leftover from a failed run
    & $baseExe @baseArgs -m venv $venv
    Check "Creating the venv"
} else {
    Write-Host "[1/5] Virtual environment exists"
}

Write-Host "[2/5] Installing dependencies"
& $py -m pip install --quiet --upgrade pip; Check "pip upgrade"
& $py -m pip install --quiet -r (Join-Path $dir "requirements.txt"); Check "pip install"

$env:STUDIP_USER = $User
if (-not $KeepPassword) {
    Write-Host "[3/5] Storing Stud.IP password in Windows Credential Manager"
    & $py $server --set-password; Check "Storing the password"
} else {
    Write-Host "[3/5] Keeping stored password"
}

Write-Host "[4/5] Testing connection (current courses)"
& $py $server --test; Check "Connection test"

Write-Host "[5/5] Creating the Claude Desktop config entry"
$entry = (& $py $server --print-config) -join "`r`n"; Check "Creating the config entry"
$copied = ""
try { Set-Clipboard -Value $entry; $copied = " (already copied to the clipboard)" } catch { }

Write-Host ""
Write-Host "Done. Last step: add this entry to Claude Desktop's config$($copied):"
Write-Host ""
Write-Host $entry
Write-Host ""
Write-Host "1. In Claude Desktop open Settings -> Developer -> Edit Config to find claude_desktop_config.json."
Write-Host "2. Quit Claude Desktop completely (tray icon -> Quit). While it runs, it can overwrite the file."
Write-Host '3. Open the file in a text editor and paste the entry inside "mcpServers": { ... },'
Write-Host '   separated from other entries by a comma. If there is no "mcpServers" yet, add'
Write-Host '   "mcpServers": { <entry> },  right after the first {. Save the file.'
Write-Host "4. Start Claude Desktop again."
Write-Host "Run this script again with -KeepPassword to print the entry again."
