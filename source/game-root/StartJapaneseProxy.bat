@echo off
set "ROOT=%~dp0"
cd /d "%ROOT%"
"%ROOT%mitmdump.exe" -s "%ROOT%replay_japanese.py" --no-http2 >> "%ROOT%offline-proxy.log" 2>&1
exit %errorlevel%
