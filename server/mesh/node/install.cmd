@echo off
rem Litha mesh node: install in this folder (scheduled task at logon/every 5 min, hidden; firewall rule if admin).
setlocal
set "HERE=%~dp0"
set "PY="
if exist "%HERE%python\python.exe" set "PY=%HERE%python\python.exe"
if not defined PY if defined LITHA_PYTHON set "PY=%LITHA_PYTHON%"
if not defined PY for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%P"
if not defined PY for /f "delims=" %%P in ('where python.exe 2^>nul ^| findstr /v /i WindowsApps') do if not defined PY set "PY=%%P"
if not defined PY (
  echo No Python found. Put an embeddable Python in "%HERE%python\" or set LITHA_PYTHON to python.exe.
  exit /b 1
)
"%PY%" "%HERE%node_agent.py" install
