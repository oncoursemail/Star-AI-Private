@echo off
rem STAR Home setup: double-click on STAR's own PC (signed in as her Windows account). Asks for administrator rights,
rem then runs setup.ps1 (PowerShell scripts may be blocked on this PC, so the policy is bypassed for this file only).
rem   setup.cmd              install or update everything (see the top of setup.ps1 for -Root -DryRun -Yes -Skip -Only -Grounder)
rem   setup.cmd -DryRun      print every step, change nothing (no administrator rights needed)
rem   setup.cmd -Uninstall   remove the task and desktop files
rem A dry run changes nothing, so it needs no administrator rights.
echo %* | findstr /i /c:"-DryRun" >nul && goto run
net session >nul 2>&1
if errorlevel 1 (
  if "%~1"=="" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  ) else (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
  )
  exit /b
)
:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
pause
