@echo off
rem Install the STAR laptop busy guard (run once on the laptop, in the admin ssh session or any prompt: no admin rights needed).
rem   1. copies busy_guard.py, node_agent.py (the mesh node's probes) next to each other in starai\busy-guard\ and the two
rem      supervisors (run-gpu-worker.cmd, run-rerank-worker.cmd, which wait while starai\PAUSE exists) into their folders
rem      (copy this folder's files to %TEMP%\laptop-kit first: busy_guard.py, node_agent.py, run-*.cmd)
rem   2. scheduled task "STAR laptop busy guard": at logon, in the owner's own session (a session-0 task cannot see the
rem      desktop, so it could not see games), hidden, below-normal priority, no password stored
rem Undo: schtasks /end /tn "STAR laptop busy guard" & schtasks /delete /tn "STAR laptop busy guard" /f & del %USERPROFILE%\Documents\starai\PAUSE
rem Notes: docs/agents/laptop-20261029.md
setlocal
set "B=%USERPROFILE%\Documents\starai"
set "K=%~dp0"
if not exist "%B%\busy-guard" mkdir "%B%\busy-guard"
copy /y "%K%busy_guard.py" "%B%\busy-guard\" >nul || exit /b 1
if exist "%K%node_agent.py" (copy /y "%K%node_agent.py" "%B%\busy-guard\" >nul) else (copy /y "%K%..\..\mesh\node\node_agent.py" "%B%\busy-guard\" >nul)
if errorlevel 1 exit /b 1
copy /y "%K%run-gpu-worker.cmd" "%B%\gpu-worker\" >nul || exit /b 1
copy /y "%K%run-rerank-worker.cmd" "%B%\rerank-worker\" >nul || exit /b 1
set "PYW=%B%\tools\toolcache\Python\3.11.9\x64\pythonw.exe"
powershell -NoProfile -Command "$a = New-ScheduledTaskAction -Execute '%PYW%' -Argument '-I \"%B%\busy-guard\busy_guard.py\" run' -WorkingDirectory '%B%\busy-guard'; $t = New-ScheduledTaskTrigger -AtLogOn -User '%COMPUTERNAME%\%USERNAME%'; $p = New-ScheduledTaskPrincipal -UserId '%COMPUTERNAME%\%USERNAME%' -LogonType Interactive -RunLevel Limited; $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew -Priority 7 -Hidden; Register-ScheduledTask -TaskName 'STAR laptop busy guard' -Description 'Pauses the GPU workers while the owner games or streams; docs/agents/laptop-20261029.md' -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null" || exit /b 1
echo installed; start now with: schtasks /run /tn "STAR laptop busy guard"
