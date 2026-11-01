@echo off
rem Litha mesh node: remove the scheduled task, unload the model, stop the node (folder and token stay).
setlocal
set "HERE=%~dp0"
set "PY="
if exist "%HERE%python\python.exe" set "PY=%HERE%python\python.exe"
if not defined PY if defined LITHA_PYTHON set "PY=%LITHA_PYTHON%"
if not defined PY for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%P"
if not defined PY for /f "delims=" %%P in ('where python.exe 2^>nul ^| findstr /v /i WindowsApps') do if not defined PY set "PY=%%P"
"%PY%" "%HERE%node_agent.py" uninstall
