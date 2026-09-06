@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

echo Starting mitmdump on port 8080...
"%ROOT%mitmdump.exe" --listen-port 8080 -s "%ROOT%replay_japanese.py" --no-http2 >> "%ROOT%offline-proxy.log" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
echo mitmdump exited with code %EXIT_CODE%. >> "%ROOT%offline-proxy.log"
exit /b %EXIT_CODE%
