@echo off
setlocal
cd /d "%~dp0"
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
  echo .NET Framework C# compiler was not found.
  echo ClaudeSentinel.exe cannot be built on this machine.
  pause
  exit /b 1
)
echo Building ClaudeSentinel.exe...
"%CSC%" /nologo /target:winexe /out:"%~dp0ClaudeSentinel.exe" /r:System.Windows.Forms.dll "%~dp0launcher\ClaudeSentinel.cs"
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)
echo Built: %~dp0ClaudeSentinel.exe
echo You can double-click it, or run create_desktop_shortcut.ps1 to create a desktop shortcut.
pause
endlocal
