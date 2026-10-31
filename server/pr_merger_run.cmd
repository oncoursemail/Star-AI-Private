@echo off
rem Litha fixes one failing PR (star.pr_fixer), then merges what passes (star.pr_merger).
rem Scheduled task "Litha PR merger", every 30 min. Off switch: %USERPROFILE%\.star\pr-merger\OFF
if exist "%USERPROFILE%\.star\pr-merger\OFF" exit /b 0
if not exist "%USERPROFILE%\.star\pr-merger" mkdir "%USERPROFILE%\.star\pr-merger"
cd /d "%~dp0.."
echo %date% %time% start >> "%USERPROFILE%\.star\pr-merger\run.log"
"%~1" -m star.pr_fixer --max 1 --python "%~1" >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
"%~1" -m star.pr_merger --apply >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
echo %date% %time% end rc=%errorlevel% >> "%USERPROFILE%\.star\pr-merger\run.log"
