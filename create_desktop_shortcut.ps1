$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $root "ClaudeSentinel.exe"
if (-not (Test-Path -LiteralPath $target)) {
    Write-Error "ClaudeSentinel.exe not found. Run build_desktop_exe.bat first."
    exit 1
}
$desktop = [Environment]::GetFolderPath("Desktop")
$linkPath = Join-Path $desktop "Claude Environment Sentinel.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($linkPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = "$target,0"
$shortcut.Description = "Claude Environment Sentinel"
$shortcut.Save()
Write-Output "Desktop shortcut created: $linkPath"
