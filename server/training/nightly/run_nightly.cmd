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
rem Second harvest card: STAR's PC 4060 through its mesh node (its busy guard decides; the node address is in
rem config.json "harvest_nodes"). Runs beside the owner-PC night until ~07:40 on the other half of the pool.
start "" /b /belownormal "%~1" -m training.nightly.nightly harvest --name starpc --shard 1/2 --prompts 1500 ^
  --max-hours 7.1 >> "%USERPROFILE%\.star\nightly\harvest-starpc.log" 2>&1
"%~1" -m training.nightly.gpu_hold --holder nightly-training --minutes 435 --until 07:45 --min-idle 120 ^
  --note "nightly self-training (harvest, QLoRA, eval)" --log "%USERPROFILE%\.star\nightly\night.log" ^
  -- "%~1" -m training.nightly.nightly run --shard 0/2 >> "%USERPROFILE%\.star\nightly\task.log" 2>&1
echo %date% %time% end rc=%errorlevel% >> "%USERPROFILE%\.star\nightly\task.log"
