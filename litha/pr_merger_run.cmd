@echo off
rem Litha fixes one failing PR (litha.pr_fixer), merges what passes (litha.pr_merger), promotes star/next to main
rem only when every release check has a receipt for the exact head (litha.pr_promote).
rem Other repos (repos.json): she resolves up to 2 conflicting PRs each, then reviews and merges what is green.
rem Scheduled task "Litha PR merger", every 10 min. Off switch: %USERPROFILE%\.star\pr-merger\OFF
if exist "%USERPROFILE%\.star\pr-merger\OFF" exit /b 0
if not exist "%USERPROFILE%\.star\pr-merger" mkdir "%USERPROFILE%\.star\pr-merger"
cd /d "%~dp0.."
echo %date% %time% start >> "%USERPROFILE%\.star\pr-merger\run.log"
"%~1" -m litha.pr_fixer --max 1 --python "%~1" >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
"%~1" -m litha.pr_merger --apply >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
"%~1" -m litha.pr_promote --apply >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
"%~1" -m litha.pr_fixer --others 2 --python "%~1" >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
"%~1" -m litha.pr_merger --apply --others >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
echo %date% %time% end rc=%errorlevel% >> "%USERPROFILE%\.star\pr-merger\run.log"
