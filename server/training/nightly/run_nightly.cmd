@echo off
rem STAR nightly self-training (scheduled task "STAR nightly training", 00:30 local, below-normal priority).
rem usage: run_nightly.cmd <training venv python.exe>
rem Off switch: create %USERPROFILE%\.star\nightly\OFF (skips the night) or STOP (stops a running night now).
cd /d "%~dp0..\.."
if exist "%USERPROFILE%\.star\nightly\OFF" (
  echo %date% %time% skipped: OFF file >> "%USERPROFILE%\.star\nightly\task.log"
  exit /b 0
)
del /q "%USERPROFILE%\.star\nightly\STOP" 2>nul
echo %date% %time% start >> "%USERPROFILE%\.star\nightly\task.log"
"%~1" -m training.nightly.gpu_hold --holder nightly-training --minutes 435 --until 07:45 --min-idle 120 ^
  --note "nightly self-training (harvest, QLoRA, eval)" --log "%USERPROFILE%\.star\nightly\night.log" ^
  -- "%~1" -m training.nightly.nightly run >> "%USERPROFILE%\.star\nightly\task.log" 2>&1
echo %date% %time% end rc=%errorlevel% >> "%USERPROFILE%\.star\nightly\task.log"
