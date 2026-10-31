@echo off
rem Litha's nightly learning run (scheduled task "Litha bug bench", 03:10): 10 new planted bugs with the PR diff,
rem 6 blind ones (failing tests only). Results: %USERPROFILE%\.star\litha\bench.jsonl; lessons and training pairs
rem next to it. Off switch: %USERPROFILE%\.star\litha\OFF
if exist "%USERPROFILE%\.star\litha\OFF" exit /b 0
if not exist "%USERPROFILE%\.star\litha" mkdir "%USERPROFILE%\.star\litha"
cd /d "%~dp0.."
"%~1" -m star.bug_bench run --n 10 --python "%~1" >> "%USERPROFILE%\.star\litha\bench.log" 2>&1
"%~1" -m star.bug_bench run --n 6 --blind --python "%~1" >> "%USERPROFILE%\.star\litha\bench.log" 2>&1
