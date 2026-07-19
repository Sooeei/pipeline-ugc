@echo off
REM Lance l'application UGC SANS console noire (via pythonw, détaché) puis se ferme.
cd /d "%~dp0"
set "PYW=%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"
start "" "%PYW%" -m app.main
exit
