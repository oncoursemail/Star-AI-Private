@echo off
rem Litha fixes failing PRs (litha.pr_fixer: 1 at a time while the owner is at the PC, 3 at once when away,
rem one CI rerun per run), merges what passes (litha.pr_merger), promotes star/next to main
rem only when every release check has a receipt for the exact head (litha.pr_promote).
rem Other repos (repos.json): she resolves up to 2 conflicting PRs each, then reviews and merges what is green.
rem Scheduled task "Litha PR merger", every 10 min. Off switch: %USERPROFILE%\.star\pr-merger\OFF
if exist "%USERPROFILE%\.star\pr-merger\OFF" exit /b 0
rem Paused by the owner (her face, python -m litha.face): the whole run waits until the PAUSED file is gone.
if exist "%USERPROFILE%\.star\pr-merger\PAUSED" echo %date% %time% paused by the owner >> "%USERPROFILE%\.star\pr-merger\run.log"
if exist "%USERPROFILE%\.star\pr-merger\PAUSED" exit /b 0
if not exist "%USERPROFILE%\.star\pr-merger" mkdir "%USERPROFILE%\.star\pr-merger"
cd /d "%~dp0.."
echo %date% %time% start >> "%USERPROFILE%\.star\pr-merger\run.log"
rem litha.self_update first: this checkout fast-forwards to a green star/next, rolled back if she cannot start
rem (a change to this script itself waits for the last line). Each step logs the time and the previous step's rc.
"%~1" -m litha.self_update >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
echo %date% %time% step self_check (previous rc=%errorlevel%) >> "%USERPROFILE%\.star\pr-merger\run.log"
rem litha.self_check next (well under 1 s when healthy): stale locks and broken JSON state repaired, rest reported.
"%~1" -m litha.self_check --quiet >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
echo %date% %time% step pr_fixer (previous rc=%errorlevel%) >> "%USERPROFILE%\.star\pr-merger\run.log"
"%~1" -m litha.pr_fixer --python "%~1" >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
echo %date% %time% step pr_merger (previous rc=%errorlevel%) >> "%USERPROFILE%\.star\pr-merger\run.log"
"%~1" -m litha.pr_merger --apply >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
echo %date% %time% step pr_promote (previous rc=%errorlevel%) >> "%USERPROFILE%\.star\pr-merger\run.log"
"%~1" -m litha.pr_promote --apply >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
echo %date% %time% step pr_fixer --others (previous rc=%errorlevel%) >> "%USERPROFILE%\.star\pr-merger\run.log"
"%~1" -m litha.pr_fixer --others 2 --python "%~1" >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
echo %date% %time% step pr_merger --others (previous rc=%errorlevel%) >> "%USERPROFILE%\.star\pr-merger\run.log"
"%~1" -m litha.pr_merger --apply --others >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
rem She picks her own work (litha.autonomy): dry run (queue only) until %USERPROFILE%\.star\litha-autonomy\APPLY
rem exists; OFF in that folder stops it. Queue: %USERPROFILE%\.star\litha-autonomy\queue.json
"%~1" -m litha.autonomy --python "%~1" >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
rem The owner's own Git server gets main and star/next too (fast-forward only): step 1 of leaving GitHub.
echo %date% %time% step forge_sync (previous rc=%errorlevel%) >> "%USERPROFILE%\.star\pr-merger\run.log"
"%~1" -m litha.forge_sync >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1
echo %date% %time% end rc=%errorlevel% >> "%USERPROFILE%\.star\pr-merger\run.log"
rem Keep this the last line: cmd.exe reads it whole before it runs, so an update that changes this script lands
rem here and `& exit /b` ends the run before cmd.exe reads the changed file at its old byte offset.
"%~1" -m litha.self_update --last >> "%USERPROFILE%\.star\pr-merger\run.log" 2>&1 & exit /b
