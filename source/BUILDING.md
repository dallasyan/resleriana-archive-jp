# Build Instructions

These are the verified Windows build commands for the toolkit. Run them from the workspace root unless a command specifies another directory.

## Paths

```text
Workspace: D:\SteamLibrary\steamapps\common\AtelierReslerianaGL
Japanese game: C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana
Python: C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe
Share package: tools\JapaneseToolkit\share
```

Do not run `dotnet build` against a `.py` file. Python tools are built with Python or PyInstaller.

## Python Validation

```powershell
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseOffline\replay_japanese.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseProfileEditor\profile_editor.py"
```

Remove generated `__pycache__` directories when preparing a package.

## BepInEx Plugins

Use the installed game directory as `JapaneseRoot` because the projects reference its BepInEx and IL2CPP assemblies.

```powershell
dotnet build "tools\JapaneseProfileCapture\JapaneseProfileCapture.csproj" -c Release -p:JapaneseRoot="C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana"
dotnet build "tools\JapaneseOffline\ForceProxy\ForceProxy.csproj" -c Release -p:JapaneseRoot="C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana"
dotnet build "tools\JapaneseOffline\Events\JapaneseOfflineEvents.csproj" -c Release -p:JapaneseRoot="C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana"
dotnet build "tools\JapaneseOffline\ClientRequestDiagnostics\ClientRequestDiagnostics.csproj" -c Release -p:JapaneseRoot="C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana"
```

Copy the resulting Release DLLs into the installed `BepInEx\plugins` directory and `share\BepInEx\plugins` as appropriate.

## ProfileEditor.exe

The editor requires `pycryptodome`, `protobuf`, and PyInstaller. Its data files must be bundled or the executable will fail to find `profile-descriptors.pb` from its temporary `_MEI` directory.

```powershell
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m pip install -r "tools\JapaneseProfileEditor\requirements.txt"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m pip install pyinstaller
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m PyInstaller --onefile --console --clean --name ProfileEditor --distpath "tools\JapaneseProfileEditor\dist" --workpath "C:\Users\DALLAS~1\AppData\Local\Temp\opencode\profile-editor-build" --add-data "tools\JapaneseProfileEditor\profile-descriptors.pb;." --add-data "tools\JapaneseProfileEditor\historical-event-state.json;." --add-data "tools\JapaneseProfileEditor\dist\master;master" "tools\JapaneseProfileEditor\profile_editor.py"
```

The Japanese key table and fixed IV are compiled into the editor. An AES key file is not required for normal profile operations.

## JapaneseCaptureObserver.exe

The observer is optional diagnostics. It requires Frida `16.7.19` and PyInstaller.

```powershell
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m pip install frida==16.7.19 pyinstaller
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m PyInstaller --onefile --console --clean --name JapaneseCaptureObserver "tools\frida_capture_japanese.py"
```

## Runtime Synchronization

After changing `replay_japanese.py`, synchronize it before testing:

```powershell
$replay = "tools\JapaneseOffline\replay_japanese.py"
Copy-Item $replay "tools\JapaneseOffline\dist\replay_japanese.py" -Force
Copy-Item $replay "tools\JapaneseToolkit\share\game-root\replay_japanese.py" -Force
Copy-Item $replay "tools\JapaneseToolkit\share\source\game-root\replay_japanese.py" -Force
Copy-Item $replay "C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana\replay_japanese.py" -Force
```

After all files are synchronized, rebuild the share archive:

```powershell
Compress-Archive -Path "tools\JapaneseToolkit\share\*" -DestinationPath "tools\JapaneseToolkit\share.zip" -Force
```

## Verification

```powershell
& "C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana\ProfileEditor.exe" inspect "C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana\profile.bin"
```

Verify the expected profile marker and rank, and compare installed/source replay hashes before a runtime test.
