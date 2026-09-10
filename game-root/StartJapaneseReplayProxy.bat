@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "JAPANESE_REPLAY_MODE=generated"
if /I "%~1"=="-replay" set "JAPANESE_REPLAY_MODE=replay"

echo Starting mitmdump on port 8080 in %JAPANESE_REPLAY_MODE% mode...
"%ROOT%mitmdump.exe" --listen-port 8080 -s "%ROOT%replay_japanese.py" --no-http2 >> "%ROOT%offline-proxy.log" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
echo mitmdump exited with code %EXIT_CODE%. >> "%ROOT%offline-proxy.log"
exit /b %EXIT_CODE%
