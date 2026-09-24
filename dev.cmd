@echo off
rem Thin wrapper so cmd.exe can run "dev <command>". Propagates dev.ps1 exit code.
where pwsh >nul 2>nul
if %ERRORLEVEL% equ 0 (
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %*
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %*
)
exit /b %ERRORLEVEL%
