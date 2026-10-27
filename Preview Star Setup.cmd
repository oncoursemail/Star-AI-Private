@echo off
call "%~dp0installer\star-home\setup.cmd" -DryRun %*
exit /b %ERRORLEVEL%
