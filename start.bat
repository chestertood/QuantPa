@echo off
rem Launches the QuantPa backend + frontend and opens the UI in an app window.
rem Both servers run with no console window — run stop.bat to shut them down.
rem Their output goes to backend\log\server.log and frontend\vite.log.
rem For frontend development with hot reload, use `npm run dev` instead.
title QuantPa

if not exist "%~dp0backend\log" mkdir "%~dp0backend\log"

wscript //nologo "%~dp0hidden.vbs" "%~dp0backend" ".venv\Scripts\python.exe -m uvicorn main:app --port 8000" "%~dp0backend\log\server.log"

rem Serve the production build, not the dev server: React StrictMode
rem double-invokes effects in dev, which fired every API call twice and made a
rem cold Markets load take ~18s instead of ~6s. Build is ~3s.
rem This one stays visible: a failed build must not scroll past unseen.
echo Building frontend...
pushd "%~dp0frontend"
call npm run build || (echo BUILD FAILED & popd & pause & exit /b 1)
popd

wscript //nologo "%~dp0hidden.vbs" "%~dp0frontend" "npm run preview" "%~dp0frontend\vite.log"

rem ponytail: fixed wait instead of polling the port. Bump it if the UI window
rem opens before the server is ready; a refresh fixes it either way.
rem `ping` rather than `timeout`: timeout.exe aborts with "Input redirection is
rem not supported" whenever stdin isn't a console, and a PATH carrying Git Bash
rem resolves the name to the GNU tool, which rejects /t outright.
ping -n 4 127.0.0.1 >nul

rem Chrome's --app gives a chromeless window, so it looks like a desktop app.
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if exist "%CHROME%" (
  start "" "%CHROME%" --app=http://localhost:5173
) else (
  start "" http://localhost:5173
)
