@echo off
rem STAR laptop GPU worker supervisor: llama.cpp CUDA server (router mode) serving star-embed-ft1 and the Qwen3 0.6B reranker.
rem Started hidden by the logon task "STAR laptop GPU worker" or by laptop-ctl.cmd start. Restarts the server if it exits,
rem unless the file STOP exists (laptop-ctl.cmd stop creates it, start deletes it), and waits while the file PAUSE exists in
rem the starai folder (written by busy_guard.py while the owner games or streams). Notes: docs\agents\laptop-20261021.md, laptop-20261029.md
setlocal
set "B=%USERPROFILE%\Documents\starai"
set "G=%B%\gpu-worker"
set "LOG=%B%\logs\llama-server.log"
set "SUP=%B%\logs\gpu-worker-supervisor.log"
set "TEMP=%B%\tmp"
set "TMP=%B%\tmp"
if not exist "%B%\logs" mkdir "%B%\logs"
if not exist "%B%\tmp" mkdir "%B%\tmp"
cd /d "%G%"

:loop
if exist "%G%\STOP" (echo %date% %time% STOP file found, supervisor ends>>"%SUP%" & exit /b 0)
if exist "%B%\PAUSE" (
  if not defined PAUSED echo %date% %time% PAUSE file found, waiting>>"%SUP%"
  set "PAUSED=1"
  ping -n 4 127.0.0.1 >nul
  goto loop
)
if defined PAUSED echo %date% %time% PAUSE gone, continuing>>"%SUP%"
set "PAUSED="
rem keep the server log under 20 MB: one old copy
for %%F in ("%LOG%") do if %%~zF GTR 20000000 move /y "%LOG%" "%LOG%.old" >nul
echo %date% %time% starting llama-server>>"%SUP%"
rem Below-normal priority on logical CPUs 4-11 (mask FF0) so games keep CPUs 0-3 and win the shared ones.
start "" /b /wait /belownormal /affinity FF0 "%G%\engine\llama-server.exe" --host 0.0.0.0 --port 8090 --api-key-file "%G%\api_keys" --models-preset "%G%\models.ini" --models-max 2 >>"%LOG%" 2>&1
echo %date% %time% llama-server exited with code %errorlevel%>>"%SUP%"
if exist "%G%\STOP" (echo %date% %time% STOP file found, supervisor ends>>"%SUP%" & exit /b 0)
timeout /t 10 /nobreak >nul
goto loop
