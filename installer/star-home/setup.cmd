@echo off
rem STAR Home setup: double-click on STAR's own PC (signed in as her Windows account). Asks for administrator rights,
rem then runs setup.ps1 (PowerShell scripts may be blocked on this PC, so the policy is bypassed for this file only).
rem   setup.cmd              install or update
rem   setup.cmd -Uninstall   remove the task and desktop files
net session >nul 2>&1
if errorlevel 1 (
  if "%~1"=="" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  ) else (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
  )
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
pause
