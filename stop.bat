@echo off
rem Shuts down the servers start.bat launched. They run with no window, so
rem there's nothing to close by hand — this is how you stop QuantPa.
rem
rem Kills whatever is listening on the two ports rather than every python.exe
rem or node.exe on the machine: those names are far too common to kill blind.
title QuantPa - stop

call :kill 8000 backend
call :kill 5173 frontend
echo.
echo Done.
rem `ping` rather than `timeout`: see the note in start.bat.
ping -n 3 127.0.0.1 >nul
exit /b 0

:kill
set "found="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%~1 .*LISTENING"') do (
  set "found=1"
  echo Stopping %~2 ^(port %~1, PID %%p^)...
  taskkill /f /pid %%p >nul 2>&1
)
if not defined found echo No %~2 running on port %~1.
exit /b 0
