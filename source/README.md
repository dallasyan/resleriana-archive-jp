# Toolkit Source

This directory contains the source code for the custom components shipped in the parent shareable toolkit. The runtime data used by the compiled profile editor remains in the sibling `profile-editor` directory, and the compiled runtime files remain in `game-root` and `BepInEx/plugins`.

## Layout

```text
game-root/
  AtelierReslerianaJapaneseOffline.bat
  StartJapaneseReplayProxy.bat
  ProfileEditor.bat
  replay_japanese.py
  expedition-special-rewards.json
tools/
  frida_capture_japanese.py
  JapaneseOffline/ForceProxy/
  JapaneseOffline/Events/
  JapaneseProfileCapture/
  JapaneseProfileEditor/
```

`frida_capture_japanese.py` is the source used to build `JapaneseCaptureObserver.exe`.

`tools/JapaneseProfileEditor/profile_editor.py` is the source used to build `ProfileEditor.exe`. Its bundled data comes from the parent package's `profile-editor/profile-descriptors.pb`, `profile-editor/historical-event-state.json`, and `profile-editor/master` directory.

`JapaneseOfflineEvents.Plugin` includes the offline `ExpeditionTimelineGroup` selector patch. Its three timeline keys are derived from the Japanese `ExpeditionTimelineGroup.json` TextAsset and are rotated in memory during special-reward presentation.

The three C# projects are BepInEx plugins:

```text
tools/JapaneseOffline/ForceProxy/ForceProxy.csproj
tools/JapaneseOffline/Events/JapaneseOfflineEvents.csproj
tools/JapaneseProfileCapture/JapaneseProfileCapture.csproj
```

## Rebuild BepInEx Plugins

Use a .NET 6 SDK and set `JapaneseRoot` to the installed Japanese game directory:

```powershell
dotnet build "source\tools\JapaneseProfileCapture\JapaneseProfileCapture.csproj" -c Release /p:JapaneseRoot="C:\path\to\AtelierResleriana"
dotnet build "source\tools\JapaneseOffline\ForceProxy\ForceProxy.csproj" -c Release /p:JapaneseRoot="C:\path\to\AtelierResleriana"
dotnet build "source\tools\JapaneseOffline\Events\JapaneseOfflineEvents.csproj" -c Release /p:JapaneseRoot="C:\path\to\AtelierResleriana"
```

Copy the resulting DLLs into the parent package's `BepInEx/plugins` directory or directly into the game's `BepInEx/plugins` directory.

## Rebuild ProfileEditor.exe

The normal package does not require Python. Rebuilding the executable requires Python, `pycryptodome`, `protobuf`, and PyInstaller:

```powershell
python -m pip install -r "source\tools\JapaneseProfileEditor\requirements.txt"
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --console --name ProfileEditor `
  --add-data "profile-editor\profile-descriptors.pb;." `
  --add-data "profile-editor\historical-event-state.json;." `
  --add-data "profile-editor\master;master" `
  "source\tools\JapaneseProfileEditor\profile_editor.py"
```

Copy the resulting `ProfileEditor.exe` beside `AtelierResleriana.exe`.

## Rebuild JapaneseCaptureObserver.exe

The observer executable was built with Frida `16.7.19` and PyInstaller:

```powershell
python -m pip install frida==16.7.19 pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --console --name JapaneseCaptureObserver `
  "source\tools\frida_capture_japanese.py"
```

Copy the resulting `JapaneseCaptureObserver.exe` beside `AtelierResleriana.exe`.

## External Components

`mitmdump.exe`, BepInEx, Unity/IL2CPP libraries, BestHTTP, and the game itself are external components. Their source is not part of this toolkit source tree.
