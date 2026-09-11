# Japanese Capture Observer

The observer is optional diagnostic tooling. It is not required by the normal offline launcher.

The observer waits for `AtelierResleriana.exe`, attaches to `GameAssembly.dll`, and writes diagnostic native buffers to the current `japanese-capture\native-observer-*` archive. It does not launch or patch the game. The offline API uses the built-in Japanese 256-key table and fixed IV, so observer output is useful only for validating future protocol changes or investigating unknown native encryption.
