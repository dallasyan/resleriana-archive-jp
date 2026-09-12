# Toolkit Source

This directory contains the source code for the custom components shipped in the parent shareable toolkit. The runtime data used by the compiled profile editor remains in the sibling `profile-editor` directory, and the compiled runtime files remain in `game-root` and `BepInEx/plugins`.

Use [`BUILDING.md`](BUILDING.md) for the verified build, data-bundling, synchronization, and archive commands. Do not substitute `dotnet build` for the Python or PyInstaller commands.

## Layout

```text
game-root/
  AtelierReslerianaJapaneseOffline.bat
  StartJapaneseReplayProxy.bat
  ProfileEditor.bat
  ShareProfile.bat
  replay_japanese.py
  analyze_japanese_capture.py
  generate_exploration_routes.py
  exploration-routes-jp.json
  expedition-special-rewards.json
tools/
  frida_capture_japanese.py
  JapaneseOffline/ForceProxy/
  JapaneseOffline/Events/
  JapaneseOffline/analyze_japanese_capture.py
  JapaneseOffline/generate_exploration_routes.py
  JapaneseProfileCapture/
  JapaneseProfileEditor/
```

`frida_capture_japanese.py` is the source used to build `JapaneseCaptureObserver.exe`.

The observer resolves the directory beside its executable when frozen and accepts `--game-root`; the packaged offline launcher passes its own directory explicitly. It does not contain a fixed Steam installation path.

`analyze_japanese_capture.py` decodes named Japanese dungeon and battle protobuf requests/responses from the capture sessions written by `JapaneseProfileCapture`. It reports key fingerprints rather than AES keys. `exploration-routes-jp.json` is generated from Japanese `exploration_area.json` and is used by the offline dungeon-start handler.

The replay currently synthesizes dungeon start/finish and profile-backed party, equipment, Memoria, battle-tool, and equipment-preset updates. Dungeon movement, dungeon rewards, and battle action responses remain capture/replay work for a later stage.

The source package's `game-root/japanese-masterdata.bytes` is the decrypted Japanese master-data payload; the encrypted payload variants are served by the offline proxy through the client's normal master-data update path before user-data initialization. Generated API crypto uses the built-in Japanese 256-key table and fixed IV; the native observer is optional diagnostics.

`tools/JapaneseProfileEditor/profile_editor.py` is the source used to build `ProfileEditor.exe`. Its bundled data comes from the parent package's `profile-editor/profile-descriptors.pb`, `profile-editor/historical-event-state.json`, and `profile-editor/master` directory.

The editor selects the Japanese AES key from the profile marker and preserves the fixed-IV profile format, so a recipient does not need the original capture session or AES-material file.

`ShareProfile.bat` runs `ProfileEditor.exe normalize --in-place` for an existing profile without applying the complete-collection edits.

`JapaneseOfflineEvents.Plugin` includes the offline `ExpeditionTimelineGroup` selector patch. Its three timeline keys are derived from the Japanese `ExpeditionTimelineGroup.json` TextAsset and are rotated in memory during special-reward presentation.

The C# projects are BepInEx plugins:

```text
tools/JapaneseOffline/ForceProxy/ForceProxy.csproj
tools/JapaneseOffline/Events/JapaneseOfflineEvents.csproj
tools/JapaneseProfileCapture/JapaneseProfileCapture.csproj
tools/JapaneseOffline/ClientRequestDiagnostics/ClientRequestDiagnostics.csproj
```

## Rebuild Components

See [`BUILDING.md`](BUILDING.md) for the exact verified commands. It covers all four BepInEx plugins, the required PyInstaller data files for `ProfileEditor.exe`, the optional observer, runtime synchronization, and `share.zip` creation.

## External Components

`mitmdump.exe`, BepInEx, Unity/IL2CPP libraries, BestHTTP, and the game itself are external components. Their source is not part of this toolkit source tree.
