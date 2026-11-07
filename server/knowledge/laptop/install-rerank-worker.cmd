@echo off
rem Install the STAR laptop rerank worker (run once on the laptop in an elevated prompt or the admin ssh session).
rem   1. scheduled task "STAR laptop rerank worker": at boot, as this user without a stored password (S4U: local files
rem      only), hidden, runs run-rerank-worker.cmd; no logon needed, so it is back after an unattended update reboot
rem   2. firewall rule "STAR laptop rerank worker (LAN)": inbound TCP 8092, Private profile, local subnet only
rem Expects (copied by hand, see docs/agents/laptop-rerank-20261021.md): rerank-worker\.venv, rerank-worker\rerank_worker.py,
rem rerank-worker\run-rerank-worker.cmd, the model folder under models\hf, gpu-worker\api_keys.
rem Undo: schtasks /delete /tn "STAR laptop rerank worker" /f
rem       netsh advfirewall firewall delete rule name="STAR laptop rerank worker (LAN)"
setlocal
set "W=%USERPROFILE%\Documents\starai\rerank-worker"
powershell -NoProfile -Command "$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c \"%W%\run-rerank-worker.cmd\"' -WorkingDirectory '%W%'; $t = New-ScheduledTaskTrigger -AtStartup; $t.Delay = 'PT1M'; $p = New-ScheduledTaskPrincipal -UserId '%COMPUTERNAME%\%USERNAME%' -LogonType S4U -RunLevel Limited; $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew; Register-ScheduledTask -TaskName 'STAR laptop rerank worker' -Description 'STAR knowledge rerank worker on the GPU, port 8092; docs/agents/laptop-rerank-20261021.md' -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null" || exit /b 1
netsh advfirewall firewall delete rule name="STAR laptop rerank worker (LAN)" >nul 2>&1
netsh advfirewall firewall add rule name="STAR laptop rerank worker (LAN)" dir=in action=allow protocol=TCP localport=8092 remoteip=LocalSubnet profile=private || exit /b 1
echo installed; start now with: schtasks /run /tn "STAR laptop rerank worker"
