# Japanese Capture Observer

Double-click `JapaneseCaptureObserver.exe` before launching the Japanese game through Steam.

The observer waits for `AtelierResleriana.exe`, attaches to `GameAssembly.dll`, and writes the discovered material only to the current `japanese-capture\native-observer-*` archive. If the game-root `aes-material.json` does not already exist, a complete key/IV pair is also written there for the profile editor; an existing root file is never overwritten. It never writes material to an online `session-*` directory. If the archive location is not writable, it falls back to `%TEMP%\AtelierResleriana\native-observer-*`. Existing output directories are never reused; a numeric suffix is added instead. The double-click executable waits up to one hour for the capture session. It does not launch or patch the game. Close the game when the desired requests have been captured, then press Enter in the observer window to close it.
