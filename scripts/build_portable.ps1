param(
    [string]$Version = "1.1.0",
    [string]$OutputRoot = "",
    [string]$PythonRoot = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path $PSScriptRoot -Parent
Push-Location $RepoRoot
try {
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $RepoRoot "dist"
}
if (-not $PythonRoot) {
    $pythonExe = (Get-Command python -ErrorAction Stop).Source
    $PythonRoot = (& $pythonExe -c "import sys; print(sys.base_prefix)").Trim()
}
if (-not (Test-Path -LiteralPath (Join-Path $PythonRoot "python.exe"))) {
    throw "PythonRoot does not contain python.exe: $PythonRoot"
}

$AppRoot = Join-Path $OutputRoot "Claude-Sentinel-$Version-win64-portable"
$ZipPath = "$AppRoot.zip"
if (Test-Path -LiteralPath $AppRoot) {
    Remove-Item -LiteralPath $AppRoot -Recurse -Force
}
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
New-Item -ItemType Directory -Path $AppRoot -Force | Out-Null

$dirs = @("sentinel", "tutorials", "docs")
foreach ($name in $dirs) {
    Copy-Item -LiteralPath (Join-Path $RepoRoot $name) -Destination $AppRoot -Recurse -Force
}
$files = @(
    "README.md",
    "README.en.md",
    "README.ja-JP.md",
    "LICENSE",
    "LICENSE-MIT",
    "LICENSING.md",
    "NOTICE",
    "AUTHORS.md",
    "GOVERNANCE.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "THIRD_PARTY_NOTICES.md",
    "requirements.txt",
    "pyproject.toml",
    "run_sentinel.bat",
    "run_sentinel_web.bat",
    "build_desktop_exe.bat",
    "create_desktop_shortcut.ps1"
)
foreach ($name in $files) {
    $source = Join-Path $RepoRoot $name
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $AppRoot -Force
    }
}

$pythonDest = Join-Path $AppRoot "python"
$exclude = @(
    (Join-Path $PythonRoot "Lib\site-packages"),
    (Join-Path $PythonRoot "Lib\test"),
    (Join-Path $PythonRoot "Lib\idlelib"),
    (Join-Path $PythonRoot "Lib\ensurepip"),
    (Join-Path $PythonRoot "Lib\venv"),
    (Join-Path $PythonRoot "Lib\pydoc_data"),
    (Join-Path $PythonRoot "Lib\turtledemo"),
    (Join-Path $PythonRoot "Doc"),
    (Join-Path $PythonRoot "include"),
    (Join-Path $PythonRoot "libs"),
    (Join-Path $PythonRoot "Scripts")
)
$robocopyArgs = @($PythonRoot, $pythonDest, "/E", "/XD") + $exclude + @("/XF", "NEWS.txt", "*.pdb", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
& robocopy @robocopyArgs
if ($LASTEXITCODE -ge 8) {
    throw "robocopy failed with exit code $LASTEXITCODE"
}
$pythonLicense = Join-Path $PythonRoot "LICENSE.txt"
if (Test-Path -LiteralPath $pythonLicense) {
    Copy-Item -LiteralPath $pythonLicense -Destination (Join-Path $pythonDest "LICENSE.txt") -Force
}

Get-ChildItem -Path $AppRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }

$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $csc)) {
    $csc = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe"
}
if (-not (Test-Path -LiteralPath $csc)) {
    throw ".NET Framework csc.exe was not found"
}
$exePath = Join-Path $AppRoot "ClaudeSentinel.exe"
$launcherSource = Join-Path $RepoRoot "launcher\ClaudeSentinel.cs"
& $csc /nologo /target:winexe "/out:$exePath" /r:System.Windows.Forms.dll $launcherSource
if ($LASTEXITCODE -ne 0) {
    throw "launcher build failed with exit code $LASTEXITCODE"
}

$portableReadme = @(
    "Claude Environment Sentinel $Version - Windows x64 portable",
    "===========================================================",
    "1. Extract the whole folder; do not copy only ClaudeSentinel.exe.",
    "2. Double-click ClaudeSentinel.exe to start the desktop app.",
    "3. Run run_sentinel_web.bat for the local control console (127.0.0.1:8790).",
    "4. The bundled python folder is the runtime; no system Python is required.",
    "5. This build is unsigned; Windows SmartScreen may warn.",
    "6. Snapshots, logs and settings are stored under backups/, logs/ and state/.",
    "7. Read README.md and docs/anti-ban-guide.md; no account outcome is promised."
)
$portableReadme | Set-Content -LiteralPath (Join-Path $AppRoot "PORTABLE-README.txt") -Encoding UTF8

& (Join-Path $pythonDest "python.exe") -c "import tkinter, sentinel; print('portable runtime ok')"
if ($LASTEXITCODE -ne 0) {
    throw "portable runtime import check failed"
}

Compress-Archive -Path (Join-Path $AppRoot "*") -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Host ""
Write-Host "Portable folder: $AppRoot"
Write-Host "Portable ZIP:    $ZipPath"
Write-Host "ZIP size MB:     $([math]::Round((Get-Item -LiteralPath $ZipPath).Length / 1MB, 1))"
}
finally {
    Pop-Location
}
