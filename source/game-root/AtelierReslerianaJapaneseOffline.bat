@echo off
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "JAPANESE_GAME_DIR=%ROOT%"
set "JAPANESE_OFFLINE=1"
set "OBSERVER_LAUNCHED=0"

echo Starting Japanese offline replay...
start "Atelier Resleriana Japanese replay" "%ROOT%mitmproxy.exe" -s "%ROOT%replay_japanese.py" --no-http2
set /a ATTEMPTS=0
:wait_proxy
netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if not errorlevel 1 goto proxy_ready
set /a ATTEMPTS+=1
if %ATTEMPTS% GEQ 30 goto proxy_failed
timeout /T 1 /NOBREAK >nul
goto wait_proxy

:proxy_ready

echo Launching Japanese game...
set "HOME_ICON_ARGUMENT="
if "%JAPANESE_HOME_ICON_RENDER%"=="1" set "HOME_ICON_ARGUMENT=-japanese-home-icon-render"
if defined JAPANESE_HOME_ICON_HOME_ID set "HOME_ICON_ARGUMENT=%HOME_ICON_ARGUMENT% -japanese-home-icon-home-id=%JAPANESE_HOME_ICON_HOME_ID%"
start "Atelier Resleriana" "%ROOT%AtelierResleriana.exe" -japanese-offline %HOME_ICON_ARGUMENT%

:loop
timeout /T 2 /NOBREAK >nul
tasklist | find /I "AtelierResleriana.exe" >nul
if errorlevel 1 goto break
call :ensure_observer
goto loop

:break
echo Stopping Japanese offline replay...
taskkill /IM mitmproxy.exe >nul 2>&1
exit /b 0

:proxy_failed
echo Japanese offline replay failed to start on port 8080.
taskkill /IM mitmproxy.exe >nul 2>&1
exit /b 1

:ensure_observer
if "%OBSERVER_LAUNCHED%"=="1" exit /b 0
tasklist /FI "IMAGENAME eq JapaneseCaptureObserver.exe" | find /I "JapaneseCaptureObserver.exe" >nul
if not errorlevel 1 goto observer_mark_running
if not exist "%ROOT%JapaneseCaptureObserver.exe" (
    echo Native AES observer was not found at "%ROOT%JapaneseCaptureObserver.exe".
    echo Continuing without automatic key observation.
    exit /b 0
)
echo Starting native AES observer...
start "Japanese Capture Observer" "%ROOT%JapaneseCaptureObserver.exe" --game-root "%ROOT%"
:observer_mark_running
set "OBSERVER_LAUNCHED=1"
exit /b 0
