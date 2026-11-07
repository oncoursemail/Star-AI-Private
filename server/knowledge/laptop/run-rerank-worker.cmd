@echo off
rem STAR laptop rerank worker supervisor (server/knowledge/laptop/rerank_worker.py on the laptop's GTX 1650, port 8092).
rem Started hidden at boot by the scheduled task "STAR laptop rerank worker" (install-rerank-worker.cmd). Restarts the
rem worker 10 s after an exit, unless the file STOP exists in this folder; waits while the file PAUSE exists in the
rem starai folder (written by busy_guard.py while the owner games or streams). Offline: the model is a local folder.
rem Notes: docs/agents/laptop-rerank-20261021.md
setlocal
set "B=%USERPROFILE%\Documents\starai"
set "W=%B%\rerank-worker"
set "MODEL=%B%\models\hf\Alibaba-NLP--gte-reranker-modernbert-base"
set "KIND=seqcls"
set "LOG=%B%\logs\rerank-worker.log"
set "TEMP=%B%\tmp"
set "TMP=%B%\tmp"
set "HF_HOME=%B%\cc\hf"
set "HF_HUB_OFFLINE=1"
set "TRANSFORMERS_OFFLINE=1"
if not exist "%B%\logs" mkdir "%B%\logs"
if not exist "%B%\tmp" mkdir "%B%\tmp"
cd /d "%W%"

:loop
if exist "%W%\STOP" (echo %date% %time% STOP file found, supervisor ends>>"%LOG%" & exit /b 0)
if exist "%B%\PAUSE" (
  if not defined PAUSED echo %date% %time% PAUSE file found, waiting>>"%LOG%"
  set "PAUSED=1"
  ping -n 4 127.0.0.1 >nul
  goto loop
)
if defined PAUSED echo %date% %time% PAUSE gone, continuing>>"%LOG%"
set "PAUSED="
for %%F in ("%LOG%") do if %%~zF GTR 20000000 move /y "%LOG%" "%LOG%.old" >nul
echo %date% %time% starting rerank worker>>"%LOG%"
rem Below-normal priority on logical CPUs 4-11 (mask FF0), like the llama.cpp GPU worker, so games keep CPUs 0-3.
start "" /b /wait /belownormal /affinity FF0 "%W%\.venv\Scripts\python.exe" -I "%W%\rerank_worker.py" --model-dir "%MODEL%" --kind %KIND% --key-file "%B%\gpu-worker\api_keys" --port 8092 --pause-file "%B%\PAUSE" >>"%LOG%" 2>&1
echo %date% %time% rerank worker exited with code %errorlevel%>>"%LOG%"
if exist "%W%\STOP" (echo %date% %time% STOP file found, supervisor ends>>"%LOG%" & exit /b 0)
rem ping as the delay: timeout.exe refuses to run without a console
ping -n 11 127.0.0.1 >nul
goto loop
