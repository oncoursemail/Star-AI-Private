@echo off
rem Litha's face (litha.face): her local web page, http://127.0.0.1:8770/ on this PC.
rem   face_run.cmd                       this PC only
rem   face_run.cmd "" --lan              also phones/PCs on the LAN (they sign in with the token below)
rem   face_run.cmd C:\path\python.exe    another python (default: the pr39 venv she runs with)
rem LAN token: type %%USERPROFILE%%\.star\litha-face.token (made on first run; never printed or logged).
rem Not registered as a task or startup entry here: whoever wants that adds it.
set "PY=%~1"
if "%PY%"=="" set "PY=%USERPROFILE%\Documents\starai\worktrees\pr39\.venv-audit\Scripts\python.exe"
cd /d "%~dp0.."
"%PY%" -m litha.face %2 %3 %4 %5
