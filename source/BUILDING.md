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
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseOffline\edit_japanese_capture.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseOffline\analyze_japanese_capture.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseOffline\build_gameplay_master.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseOffline\build_endpoint_contract_map.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseOffline\create_starter_profile.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseProfileEditor\profile_editor.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseOffline\tests\test_replay_progression.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseOffline\tests\test_replay_gacha.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseOffline\tests\test_replay_battle.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseOffline\tests\test_replay_noncombat.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseOffline\build_gacha_snapshot.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseOffline\battle_japanese.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile "tools\JapaneseOffline\build_battle_master.py"
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -m unittest discover -s "tools\JapaneseOffline\tests" -p "test_replay_*.py"
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

## Synthetic Starter Profile

The package's `game-root\starter-profile.bin` is generated from an encrypted new-signup profile captured before tutorial progress. The generator accepts only profiles with `tutorial_step=0`, rank 1, and one starter character. It preserves the profile marker while replacing the player name, clearing memo and birthday fields, and normalizing the account creation timestamp. Never bundle the input capture or original profile.

```powershell
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" "tools\JapaneseOffline\create_starter_profile.py" "<private-session>\profile.bin" "tools\JapaneseToolkit\share\game-root\starter-profile.bin" --name "Offline"
```

The normal launcher copies this starter file to `profile.bin` only when no profile exists. It does not seed full `-replay` mode or overwrite an existing profile.

## Gacha Snapshot

The package's `game-root\gacha-snapshot.json` carries the public banner/rate data used by the generated `/gacha/list` and `/gacha/execute` handlers: banner/button/cost metadata, decoded standard rate sets with per-card rates and rarities, verbatim mixed-wishlist sets, and the banner notification payload. Wishlist selections and execution counts are excluded (empty states are synthesized; counts live in the runtime `gacha-state.json` sidecar). Regenerate it from a private capture session and the Japanese master tables; never bundle the input session:

```powershell
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" "tools\JapaneseOffline\build_gacha_snapshot.py" "<private-session>" "resleriana-db-main\data\master\jp" "tools\JapaneseToolkit\share\game-root\gacha-snapshot.json"
```

`progression-master` also contains Japanese `battle_tool.json`, `battle_tool_trait.json`, `equipment_tool.json`, `equipment_tool_trait.json`, `memoria_level.json`, `memoria_buff_growth.json`, `memoria.json`, `memoria_rarity.json`, `memoria_sp_bonus.json`, `trait_rank_total.json`, `ship_part.json`, `ship_level.json`, `ship_tool.json`, and `ship_tool_level.json` tables used by generated battle, tool-conversion, Memoria, and ship handlers. Keep these files synchronized across `dist`, share runtime/source, and the installed game.

## Non-Combat Gameplay Master

The runtime's `gameplay-master.json` contains compact Japanese recipe, dish,
expedition, expedition-recommendation, exploration-area, street-phase, and
street-talk tables. Character, item, battle-tool, equipment-tool, and trait tables are reused from
`progression-master`; quest score and drop tables are reused from
`battle-master`. Regenerate it from Japanese master tables (no capture data is
used):

```powershell
& "<configured Python 3.10 executable>" "tools\JapaneseOffline\build_gameplay_master.py" "resleriana-db-main\data\master\jp" "tools\JapaneseToolkit\share\game-root\gameplay-master.json"
```

Copy `gameplay-master.json` to `tools\JapaneseOffline\dist`,
`tools\JapaneseToolkit\share\source\game-root`, and the installed game.
Hybrid mode uses empty generated `/mail/list` and `/mail/open` responses when
the embedded startup handshake has no records for those routes; do not bundle
online mailbox payloads or account-specific mail attachments.

## Endpoint Contract Mapping

Regenerate the request/response mapping and unmatched API-message list at the
bottom of `ENDPOINTS.md` from the installed client's contract dump:

```powershell
& "<configured Python 3.10 executable>" "tools\JapaneseOffline\build_endpoint_contract_map.py" "C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana\contract-dump\fields.txt" "tools\JapaneseToolkit\share\ENDPOINTS.md"
```

## Battle Master

The package's `game-root\battle-master\*.json` carries the slim battle tables used by the generated battle simulation (`battle_japanese.py`): quests, battles, waves, enemies, skills, timeline panels, state-change kinds, drop/reward sets, enemy AI, exploration areas, gacha battles, fixed parties, and character growth. Regenerate it from the Japanese master tables:

```powershell
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" "tools\JapaneseOffline\build_battle_master.py" "resleriana-db-main\data\master\jp" "tools\JapaneseToolkit\share\game-root\battle-master"
```

Character/rarity/level/memoria tables are reused from `progression-master` at runtime.

## Combat Map and Checklists

`build_combat_map.py` translates Japanese effect/state/panel descriptions into
the runtime `combat_map.json`. Regenerate the share runtime map after changing
the parser or battle simulator:

```powershell
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" "tools\JapaneseOffline\build_combat_map.py" "resleriana-db-main\data\master\jp" "tools\JapaneseToolkit\share\game-root\battle-master" --machine "AtelierResleriana-master\Localization\MasterData\Machine\en"
```

Then copy the share `battle-master` directory to `tools\JapaneseOffline\dist`,
`tools\JapaneseToolkit\share\source\game-root`, and the installed game as
shown under Runtime Synchronization. The generator prints effect coverage,
JP/EN disagreements, and state-kind counts for review.

After a combat-map, parser, or simulator change, regenerate the workspace and
sanitized share checklists:

```powershell
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" "tools\JapaneseOffline\build_granular_checklists.py" "resleriana-db-main\data\master\jp" "tools\JapaneseToolkit\share\game-root" "COMBAT_CHECKLISTS" --localization "AtelierResleriana-master\Localization\MasterDataLocalizationData.json" --machine "AtelierResleriana-master\Localization\MasterData\Machine\en" --share-dir "tools\JapaneseToolkit\share"
```

Review newly unmapped/partial rows and verify the share checklist copies contain
no session tokens or profile references before rebuilding the archive.
This command also writes `COMBAT_UNIMPLEMENTED_EFFECTS.md`, a bilingual backlog
of state-change rows with missing mechanics and effect-master IDs whose parser
code is still `unmapped`; duplicate descriptions are grouped with all IDs kept.

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
$captureEditor = "tools\JapaneseOffline\edit_japanese_capture.py"
Copy-Item $captureEditor "tools\JapaneseOffline\dist\edit_japanese_capture.py" -Force
Copy-Item $captureEditor "tools\JapaneseToolkit\share\game-root\edit_japanese_capture.py" -Force
Copy-Item $captureEditor "tools\JapaneseToolkit\share\source\tools\JapaneseOffline\edit_japanese_capture.py" -Force
$captureAnalyzer = "tools\JapaneseOffline\analyze_japanese_capture.py"
Copy-Item $captureAnalyzer "tools\JapaneseOffline\dist\analyze_japanese_capture.py" -Force
Copy-Item $captureAnalyzer "tools\JapaneseToolkit\share\game-root\analyze_japanese_capture.py" -Force
Copy-Item $captureAnalyzer "tools\JapaneseToolkit\share\source\tools\JapaneseOffline\analyze_japanese_capture.py" -Force
$gameplayBuilder = "tools\JapaneseOffline\build_gameplay_master.py"
Copy-Item $gameplayBuilder "tools\JapaneseToolkit\share\source\tools\JapaneseOffline\build_gameplay_master.py" -Force
$contractMapBuilder = "tools\JapaneseOffline\build_endpoint_contract_map.py"
Copy-Item $contractMapBuilder "tools\JapaneseToolkit\share\source\tools\JapaneseOffline\build_endpoint_contract_map.py" -Force
$gameplayMaster = "tools\JapaneseToolkit\share\game-root\gameplay-master.json"
Copy-Item $gameplayMaster "tools\JapaneseOffline\dist\gameplay-master.json" -Force
Copy-Item $gameplayMaster "tools\JapaneseToolkit\share\source\game-root\gameplay-master.json" -Force
Copy-Item $gameplayMaster "C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana\gameplay-master.json" -Force
$starterProfileTool = "tools\JapaneseOffline\create_starter_profile.py"
Copy-Item $starterProfileTool "tools\JapaneseToolkit\share\source\tools\JapaneseOffline\create_starter_profile.py" -Force
$gachaSnapshotTool = "tools\JapaneseOffline\build_gacha_snapshot.py"
Copy-Item $gachaSnapshotTool "tools\JapaneseToolkit\share\source\tools\JapaneseOffline\build_gacha_snapshot.py" -Force
$gachaSnapshot = "tools\JapaneseToolkit\share\game-root\gacha-snapshot.json"
Copy-Item $gachaSnapshot "tools\JapaneseOffline\dist\gacha-snapshot.json" -Force
Copy-Item $gachaSnapshot "tools\JapaneseToolkit\share\source\game-root\gacha-snapshot.json" -Force
Copy-Item $gachaSnapshot "C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana\gacha-snapshot.json" -Force
$offlineLauncher = "tools\JapaneseToolkit\share\game-root\AtelierReslerianaJapaneseOffline.bat"
Copy-Item $offlineLauncher "tools\JapaneseToolkit\share\source\game-root\AtelierReslerianaJapaneseOffline.bat" -Force
Copy-Item $offlineLauncher "C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana\AtelierReslerianaJapaneseOffline.bat" -Force
Copy-Item "tools\JapaneseToolkit\share\game-root\starter-profile.bin" "tools\JapaneseToolkit\share\source\game-root\starter-profile.bin" -Force
Copy-Item "tools\JapaneseToolkit\share\game-root\starter-profile.bin" "C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana\starter-profile.bin" -Force
$progressionMaster = "tools\JapaneseToolkit\share\game-root\progression-master"
Copy-Item $progressionMaster "tools\JapaneseOffline\dist" -Recurse -Force
Copy-Item $progressionMaster "tools\JapaneseToolkit\share\source\game-root" -Recurse -Force
Copy-Item $progressionMaster "C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana" -Recurse -Force
$battle = "tools\JapaneseOffline\battle_japanese.py"
Copy-Item $battle "tools\JapaneseOffline\dist\battle_japanese.py" -Force
Copy-Item $battle "tools\JapaneseToolkit\share\game-root\battle_japanese.py" -Force
Copy-Item $battle "tools\JapaneseToolkit\share\source\game-root\battle_japanese.py" -Force
Copy-Item $battle "C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana\battle_japanese.py" -Force
$combatMapBuilder = "tools\JapaneseOffline\build_combat_map.py"
Copy-Item $combatMapBuilder "tools\JapaneseToolkit\share\source\tools\JapaneseOffline\build_combat_map.py" -Force
$checklistBuilder = "tools\JapaneseOffline\build_granular_checklists.py"
Copy-Item $checklistBuilder "tools\JapaneseToolkit\share\source\tools\JapaneseOffline\build_granular_checklists.py" -Force
$battleBuilder = "tools\JapaneseOffline\build_battle_master.py"
Copy-Item $battleBuilder "tools\JapaneseToolkit\share\source\tools\JapaneseOffline\build_battle_master.py" -Force
$battleMaster = "tools\JapaneseToolkit\share\game-root\battle-master"
Copy-Item $battleMaster "tools\JapaneseOffline\dist" -Recurse -Force
Copy-Item $battleMaster "tools\JapaneseToolkit\share\source\game-root" -Recurse -Force
Copy-Item $battleMaster "C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana" -Recurse -Force
```

After all files are synchronized, normalize Windows batch files to CRLF, then rebuild the share archive:

```powershell
& "C:\Users\Dallas Yan\AppData\Local\Programs\Python\Python310\python.exe" -c "from pathlib import Path; [Path(p).write_bytes(Path(p).read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')) for p in list(Path('tools').rglob('*.bat'))]"
Compress-Archive -Path "tools\JapaneseToolkit\share\*" -DestinationPath "tools\JapaneseToolkit\share.zip" -Force
```

Batch files must keep CRLF line endings; LF-only checkouts break `call :label` with "cannot find the batch label".

## Verification

```powershell
& "C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana\ProfileEditor.exe" inspect "C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana\profile.bin"
```

Verify the expected profile marker and rank, and compare installed/source replay hashes before a runtime test.
