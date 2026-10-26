@echo off
rem STAR Camera driver install: double-click on STAR's own PC. Asks for administrator rights, then runs install-camera.ps1
rem (PowerShell scripts may be blocked on this PC, so the policy is bypassed for this file only).
rem   install-camera.cmd              install or repair the "STAR Camera" virtual webcam
rem   install-camera.cmd -Uninstall   remove it
net session >nul 2>&1
if errorlevel 1 (
  if "%~1"=="" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  ) else (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
  )
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-camera.ps1" %*
pause
