@echo off
rem STAR laptop vision critic supervisor: llama.cpp server (the gpu-worker's existing build) with Qwen3-VL-8B (vision),
rem port 8093, for star/vision_critic.py (prefer / issues). Started hidden by the logon task "STAR laptop vision critic".
rem Restarts the server if it exits, unless STOP exists in this folder; waits while the busy guard's PAUSE file exists in
rem the starai folder (the guard also kills port 8093 when the owner games: busy-guard\busy_guard.json kill_ports).
rem CPU only (-dev none, no mmproj offload): uses no video memory, so the knowledge workers and games never get squeezed;
rem 23.6 s per call measured (13 s with the projector on the GPU, which costs 1.2 GB VRAM). The model sleeps after 120
rem idle seconds (about 6 GB RAM freed), the next request reloads it (a few seconds).
rem Notes: docs/agents/vision-critic-20261029.md
setlocal
set B=%USERPROFILE%\Documents\starai
set V=%B%\vision-critic
set E=%B%\gpu-worker\engine
set LOG=%B%\logs\vision-critic.log
set SUP=%B%\logs\vision-critic-supervisor.log
set TEMP=%B%\tmp
set TMP=%B%\tmp
if not exist "%B%\logs" mkdir "%B%\logs"
if not exist "%B%\tmp" mkdir "%B%\tmp"
cd /d "%V%"

:loop
if exist "%V%\STOP" (echo %date% %time% STOP file found, supervisor ends>>"%SUP%" & exit /b 0)
if exist "%B%\PAUSE" (
  if not defined PAUSED echo %date% %time% PAUSE file found, waiting>>"%SUP%"
  set PAUSED=1
  ping -n 4 127.0.0.1 >nul
  goto loop
)
if defined PAUSED echo %date% %time% PAUSE gone, continuing>>"%SUP%"
set PAUSED=
for %%F in ("%LOG%") do if %%~zF GTR 20000000 move /y "%LOG%" "%LOG%.old" >nul
echo %date% %time% starting llama-server>>"%SUP%"
rem Below-normal priority on logical CPUs 4-11 (mask FF0) so games keep CPUs 0-3. Unquoted paths: no spaces here, and
rem start /b mangles quoted arguments after the program name.
start "" /b /wait /belownormal /affinity FF0 %E%\llama-server.exe --host 0.0.0.0 --port 8093 --api-key-file %V%\api_keys -m %V%\models\Qwen3VL-8B-Instruct-Q4_K_M.gguf --mmproj %V%\models\mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf --alias critic -c 4096 -ctk q8_0 -ctv q8_0 --image-max-tokens 384 -np 1 -t 6 -ngl 0 --no-mmproj-offload -dev none --no-webui --sleep-idle-seconds 120 >>"%LOG%" 2>&1
echo %date% %time% llama-server exited with code %errorlevel%>>"%SUP%"
if exist "%V%\STOP" (echo %date% %time% STOP file found, supervisor ends>>"%SUP%" & exit /b 0)
timeout /t 10 /nobreak >nul
goto loop
