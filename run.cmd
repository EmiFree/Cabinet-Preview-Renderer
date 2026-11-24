@echo off
rem Cabinet Preview Renderer launcher for Windows.
rem Uses the bundled Python in runtime\python-win-amd64 when present, otherwise py / python on PATH.
setlocal
set "CPR_HOME=%~dp0"
set "CPR_BUNDLED=%CPR_HOME%runtime\python-win-amd64\python.exe"
if exist "%CPR_BUNDLED%" goto bundled
where py >nul 2>nul
if not errorlevel 1 goto pylauncher
where python >nul 2>nul
if not errorlevel 1 goto pathpython
echo ERROR: No Python found. Restore runtime\python-win-amd64 from the original zip, or install Python 3.8+.
exit /b 9

:bundled
"%CPR_BUNDLED%" "%CPR_HOME%tools\cpr.py" %*
exit /b %ERRORLEVEL%

:pylauncher
py -3 "%CPR_HOME%tools\cpr.py" %*
exit /b %ERRORLEVEL%

:pathpython
python "%CPR_HOME%tools\cpr.py" %*
exit /b %ERRORLEVEL%
