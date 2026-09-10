@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

if not exist "%ROOT%ProfileEditor.exe" (
    echo ProfileEditor.exe is missing from the game directory.
    exit /b 1
)
if not exist "%ROOT%profile.bin" (
    echo No game-root profile.bin was found.
    exit /b 1
)

echo Re-encrypting profile.bin into the share-compatible format.
"%ROOT%ProfileEditor.exe" normalize --in-place
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" echo Profile is ready to share.
pause
exit /b %EXIT_CODE%
