# Japanese Capture Observer

Double-click `JapaneseCaptureObserver.exe` before launching the Japanese game through Steam.

The observer waits for `AtelierResleriana.exe`, attaches to `GameAssembly.dll`, records the native AES buffers, and writes the discovered material to the newest `japanese-capture\session-*\aes-material.json`. When a complete key/IV pair and the game-root `profile.bin` are available, it also writes `aes-material.json` in the game root beside that profile. Raw native buffers go to the Japanese installation's `japanese-capture\native-observer-*` archive by default. If that location is not writable, it falls back to `%TEMP%\AtelierResleriana\native-observer-*`. Existing output directories are never reused; a numeric suffix is added instead. The double-click executable waits up to one hour for the capture session. It does not launch or patch the game. Close the game when the desired requests have been captured, then press Enter in the observer window to close it.
