@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

if not exist "%ROOT%ProfileEditor.exe" (
    echo ProfileEditor.exe is missing from the game directory.
    goto failed
)
if not exist "%ROOT%profile.bin" (
    echo No game-root profile.bin was found.
    echo Run the game online once first, then run this file again.
    goto failed
)
tasklist /FI "IMAGENAME eq AtelierResleriana.exe" | find /I "AtelierResleriana.exe" >nul
if not errorlevel 1 (
    echo Close Atelier Resleriana before editing profile.bin.
    goto failed
)

echo Updating the game-root profile. A backup will be created automatically.
"%ROOT%ProfileEditor.exe" complete-collection --in-place
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" echo Profile update completed successfully.
if not "%EXIT_CODE%"=="0" echo Profile update failed with exit code %EXIT_CODE%.
echo.
pause
exit /b %EXIT_CODE%

:failed
echo.
pause
exit /b 1
