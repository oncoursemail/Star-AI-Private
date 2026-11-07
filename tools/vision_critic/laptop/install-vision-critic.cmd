@echo off
rem Install the STAR laptop vision critic (run once on the laptop, admin prompt or the admin ssh session).
rem   1. scheduled task "STAR laptop vision critic": at logon of this user, hidden (conhost --headless), runs
rem      run-vision-critic.cmd in the logon session so the busy guard can kill it (same as "STAR laptop GPU worker")
rem   2. firewall rule "STAR laptop vision critic (LAN)": inbound TCP 8093, Private profile, local subnet only
rem   3. busy guard overlay busy-guard\busy_guard.json: kill_ports 8090+8093, watch_ports 8090+8092+8093
rem      (restart the task "STAR laptop busy guard" afterwards so it reads the overlay)
rem Expects: vision-critic\run-vision-critic.cmd, vision-critic\api_keys (one key per line), vision-critic\models\
rem (Qwen3VL-8B-Instruct-Q4_K_M.gguf + mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf, sha256 in the notes).
rem Undo: schtasks /delete /tn "STAR laptop vision critic" /f
rem       netsh advfirewall firewall delete rule name="STAR laptop vision critic (LAN)"
rem       delete busy-guard\busy_guard.json (or remove 8093 from it) and restart the guard task
setlocal
set V=%USERPROFILE%\Documents\starai\vision-critic
set G=%USERPROFILE%\Documents\starai\busy-guard
powershell -NoProfile -Command "$a = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument '--headless cmd.exe /c %V%\run-vision-critic.cmd' -WorkingDirectory '%V%'; $t = New-ScheduledTaskTrigger -AtLogOn -User '%COMPUTERNAME%\%USERNAME%'; $p = New-ScheduledTaskPrincipal -UserId '%COMPUTERNAME%\%USERNAME%' -LogonType Interactive -RunLevel Limited; $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew; Register-ScheduledTask -TaskName 'STAR laptop vision critic' -Description 'STAR vision critic (Qwen3-VL-8B, llama.cpp, CPU), port 8093; docs/agents/vision-critic-20261029.md' -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null" || exit /b 1
netsh advfirewall firewall delete rule name="STAR laptop vision critic (LAN)" >nul 2>&1
netsh advfirewall firewall add rule name="STAR laptop vision critic (LAN)" dir=in action=allow protocol=TCP localport=8093 remoteip=LocalSubnet profile=private || exit /b 1
if not exist "%G%\busy_guard.json" (
  > "%G%\busy_guard.json" echo {"kill_ports": [8090, 8093], "watch_ports": [8090, 8092, 8093]}
) else (
  echo busy_guard.json exists already: add 8093 to kill_ports and watch_ports by hand
)
echo installed; restart the guard: schtasks /end /tn "STAR laptop busy guard" ^& schtasks /run /tn "STAR laptop busy guard"
echo start the critic: schtasks /run /tn "STAR laptop vision critic"
