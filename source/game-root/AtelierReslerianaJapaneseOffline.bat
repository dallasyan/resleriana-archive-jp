@echo off
set "ROOT=%~dp0"
set "GAME_ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"
set "JAPANESE_REPLAY_MODE=hybrid"
set "JAPANESE_CAPTURE_SESSION=%ROOT%embedded-handshake"
if /I "%~1"=="-generated" set "JAPANESE_REPLAY_MODE=generated"
if /I "%~1"=="-replay" set "JAPANESE_REPLAY_MODE=replay"
set "JAPANESE_GAME_DIR=%ROOT%"
set "JAPANESE_OFFLINE=1"
set "OBSERVER_LAUNCHED=0"
set "OBSERVER_STOP_FILE=%GAME_ROOT%\japanese-capture\offline-observer-stop.txt"
set "OBSERVER_OUTPUT=%GAME_ROOT%\japanese-capture\native-observer-offline-%RANDOM%-%RANDOM%"
if not exist "%GAME_ROOT%\japanese-capture" mkdir "%GAME_ROOT%\japanese-capture"
if exist "%OBSERVER_STOP_FILE%" del /q "%OBSERVER_STOP_FILE%" >nul 2>&1
taskkill /IM JapaneseCaptureObserver.exe /T >nul 2>&1
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8080 .*LISTENING"') do taskkill /PID %%P /T /F >nul 2>&1

echo Starting Japanese offline mode: %JAPANESE_REPLAY_MODE%...
start "Atelier Resleriana Japanese replay" /b "%ROOT%StartJapaneseProxy.bat"
timeout /T 5 /NOBREAK >nul
netstat -ano | findstr ":8080" | findstr "LISTENING" >nul
if errorlevel 1 goto proxy_failed
goto proxy_ready

:proxy_ready

call :ensure_observer
timeout /T 1 /NOBREAK >nul

echo Launching Japanese game...
set "HOME_ICON_ARGUMENT="
if "%JAPANESE_HOME_ICON_RENDER%"=="1" set "HOME_ICON_ARGUMENT=-japanese-home-icon-render"
if defined JAPANESE_HOME_ICON_HOME_ID set "HOME_ICON_ARGUMENT=%HOME_ICON_ARGUMENT% -japanese-home-icon-home-id=%JAPANESE_HOME_ICON_HOME_ID%"
start "Atelier Resleriana" "%ROOT%AtelierResleriana.exe" -japanese-offline %HOME_ICON_ARGUMENT%
set "GAME_SEEN=0"
set /a GAME_PRESENT_CHECKS=0
set /a GAME_MISSING_CHECKS=0

:loop
timeout /T 2 /NOBREAK >nul
tasklist | find /I "AtelierResleriana.exe" >nul
if errorlevel 1 goto game_missing
set /a GAME_PRESENT_CHECKS+=1
set /a GAME_MISSING_CHECKS=0
call :ensure_observer
if %GAME_PRESENT_CHECKS% LSS 5 goto loop
set "GAME_SEEN=1"
goto loop

:game_missing
set /a GAME_PRESENT_CHECKS=0
if "%GAME_SEEN%"=="0" goto loop
set /a GAME_MISSING_CHECKS+=1
if %GAME_MISSING_CHECKS% LSS 3 goto loop
goto break

:break
echo Stopping Japanese offline replay...
taskkill /IM mitmdump.exe /T /F >nul 2>&1
taskkill /IM mitmproxy.exe /T /F >nul 2>&1
if "%OBSERVER_LAUNCHED%"=="1" goto stop_observer
goto exit_offline

:stop_observer
> "%OBSERVER_STOP_FILE%" echo stop
timeout /T 2 /NOBREAK >nul
taskkill /IM JapaneseCaptureObserver.exe /T /F >nul 2>&1
if exist "%OBSERVER_STOP_FILE%" del /q "%OBSERVER_STOP_FILE%" >nul 2>&1

:exit_offline
exit 0

:proxy_failed
echo Japanese offline replay failed to start on port 8080.
echo Check offline-proxy.log for the proxy startup error.
pause
exit 1

:ensure_observer
if "%OBSERVER_LAUNCHED%"=="1" exit /b 0
if not exist "%ROOT%JapaneseCaptureObserver.exe" (
    echo Native AES observer was not found at "%ROOT%JapaneseCaptureObserver.exe".
    echo Continuing without automatic key observation.
    exit /b 0
)
echo Starting native AES observer...
start "Japanese Capture Observer" /b "%ROOT%JapaneseCaptureObserver.exe" --game-root "%GAME_ROOT%" --output "%OBSERVER_OUTPUT%" --keep-waiting --stop-file "%OBSERVER_STOP_FILE%"
set "OBSERVER_LAUNCHED=1"
exit /b 0
