@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "JAPANESE_GAME_DIR=%ROOT%"
set "JAPANESE_OFFLINE=1"
set "OBSERVER_LAUNCHED=0"

echo Stopping any previous Japanese replay proxy...
taskkill /F /T /IM mitmproxy.exe >nul 2>&1
taskkill /F /T /IM mitmdump.exe >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq Atelier Resleriana Japanese replay" /IM cmd.exe >nul 2>&1

echo Starting Japanese offline replay...
start "Atelier Resleriana Japanese replay" /D "%ROOT%" "%ComSpec%" /D /C call "%ROOT%StartJapaneseReplayProxy.bat"
set /a ATTEMPTS=0
:wait_proxy
set /a ATTEMPTS+=1
tasklist /FI "IMAGENAME eq mitmdump.exe" | find /I "mitmdump.exe" >nul
if errorlevel 1 goto wait_more
netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if not errorlevel 1 goto proxy_ready
:wait_more
if %ATTEMPTS% GEQ 30 goto proxy_failed
timeout /T 1 /NOBREAK >nul
goto wait_proxy

:proxy_ready

echo Launching Japanese game...
set "HOME_ICON_ARGUMENT="
if "%JAPANESE_HOME_ICON_RENDER%"=="1" set "HOME_ICON_ARGUMENT=-japanese-home-icon-render"
if defined JAPANESE_HOME_ICON_HOME_ID set "HOME_ICON_ARGUMENT=%HOME_ICON_ARGUMENT% -japanese-home-icon-home-id=%JAPANESE_HOME_ICON_HOME_ID%"
start "Atelier Resleriana" "%ROOT%AtelierResleriana.exe" -japanese-offline %HOME_ICON_ARGUMENT%

set /a GAME_START_ATTEMPTS=0
set "GAME_SEEN=0"
:loop
timeout /T 2 /NOBREAK >nul
tasklist | find /I "AtelierResleriana.exe" >nul
if not errorlevel 1 goto game_seen
if "%GAME_SEEN%"=="1" goto break
set /a GAME_START_ATTEMPTS+=1
if %GAME_START_ATTEMPTS% GEQ 30 goto break
goto loop

:game_seen
set "GAME_SEEN=1"
call :ensure_observer
goto loop

:break
echo Stopping Japanese offline replay...
taskkill /F /T /IM mitmproxy.exe >nul 2>&1
taskkill /F /T /IM mitmdump.exe >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq Atelier Resleriana Japanese replay" /IM cmd.exe >nul 2>&1
exit /b 0

:proxy_failed
echo Japanese offline replay failed to start on port 8080.
taskkill /F /T /IM mitmproxy.exe >nul 2>&1
taskkill /F /T /IM mitmdump.exe >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq Atelier Resleriana Japanese replay" /IM cmd.exe >nul 2>&1
echo Check "%ROOT%offline-proxy.log" for mitmdump startup details.
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
start "Japanese Capture Observer" "%ROOT%JapaneseCaptureObserver.exe"
:observer_mark_running
set "OBSERVER_LAUNCHED=1"
exit /b 0
