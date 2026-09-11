# Atelier Resleriana Japanese Offline Toolkit

This folder contains the shareable runtime files for the Japanese Steam installation. It does not contain a personal `profile.bin`, capture session, or personal AES material. The included anonymization sidecar contains only synthetic identity values.

## Recommended Workflow

1. Copy the contents of `game-root` into the Japanese game directory beside `AtelierResleriana.exe`.
2. Copy the contents of `BepInEx/plugins` into the game's `BepInEx/plugins` directory.
3. Launch the game normally through Steam and log in once. `JapaneseProfileCapture.dll` saves the online profile in `japanese-capture\session-*` and creates the game-root `profile.bin` only if one does not already exist.
4. Close the game. Optionally double-click `ProfileEditor.bat` to create the complete profile. It preserves the profile's marker-selected Japanese AES format and creates a backup automatically.
5. Double-click `AtelierReslerianaJapaneseOffline.bat` to play offline. No initial offline session or AES observation run is required.
6. Optionally double-click `ShareProfile.bat` when a profile should be prepared for sharing. Share only the resulting `profile.bin`.

The normal workflow requires no Python, environment variables, command-line arguments, or manual proxy setup. Do not use Steam for offline launches. `ProfileEditor.exe` is bundled; `ProfileEditor.bat` and `ShareProfile.bat` are the intended entry points.

Japanese API encryption uses the built-in 256-key table derived from the two Japanese server seed families and the fixed IV. The native observer is not required for normal offline API crypto.

Generated `/login_bonus/receive` returns a regular daily-login state. Captured-response replay is an optional developer/diagnostic mode and is not required for the recommended workflow.

`game-root\japanese-masterdata.bytes` and the encrypted payload variants contain the current Japanese master data. The offline proxy serves the matching encrypted payload through the client's normal master-data update request, so the localization plugin can translate the loaded data before user-data initialization.

The package also handles Japanese dungeon entry through `/exploration/start` and a safe empty-resource `/exploration/finish` response. It uses the selected dungeon's `quest_id`, party number, bundled `exploration-routes-jp.json`, and the profile/capture party state. Dungeon movement, dungeon gathering rewards, and dungeon battles remain pending battle-response work.

Party editing is locally synthesized for `/party/bulk_update`, `/party/battle_tools_set`, `/character/equip`, `/character/memoria_set`, and `/equipment_preset/bulk_set`, using the active profile and request fields.

The `source` directory contains the source code for the custom scripts, compiled editor, observer, and BepInEx plugins. It also includes rebuild instructions. Third-party binaries such as `mitmdump.exe` and BepInEx/Unity libraries are not included as source.

## Optional Online Capture

`JapaneseProfileCapture.dll` watches successful Japanese login responses. It always saves a session copy under `japanese-capture/session-*`. If the game-root `profile.bin` does not exist, the first successful online login creates it from that session copy. An existing root profile is never overwritten.

The native observer is optional diagnostic tooling. It can still capture native buffers and verify the key table, but its output is not required by the normal offline launcher or profile editor.

Offline Expedition reward collection is configured by `game-root/expedition-special-rewards.json`. The replay rotates through the seven valuable items associated with expedition sites 50-56 and marks each response as a rare special reward. The offline events plugin separately rotates the weighted `ExpeditionTimelineGroup` keys used by the client presentation, since changing the item ID alone does not change the cutscene. This is intended to trigger the special-reward presentation/cutscene and must be verified in-game.

For optional online analysis, double-click `JapaneseCaptureObserver.exe` before launching the game through Steam. It does not launch or patch the game.

## Advanced Diagnostics

The following are not required for normal use:

```text
AtelierReslerianaJapaneseOffline.bat -replay
```

`-replay`, `offline-session.txt`, `StartJapaneseReplayProxy.bat`, Python commands, and manual proxy commands are for development and capture analysis only. The launcher starts the local replay proxy, sets `JAPANESE_OFFLINE=1`, and starts the game. The observer is not required by the normal launcher.

## Profile Editor

The editor supports inspection, targeted edits, historical event state, collection unlocks, progression maximization, Bond chapters, and Character Stories. The normal entry point is `ProfileEditor.bat`; it runs the bundled `ProfileEditor.exe` against the game-root profile.

The editor defaults to the game-root `profile.bin` and selects the AES key directly from the profile marker. `JAPANESE_GAME_DIR` is only needed for advanced use of the raw Python editor from another directory.

Profiles written by the bundled editor preserve the marker-selected Japanese AES key/IV format. Other users can use the resulting `profile.bin` without receiving the source user's capture session or AES-material file.

To prepare an existing profile specifically for sharing, run `ShareProfile.bat` from the source game directory, then distribute only `profile.bin`. Profiles using the Japanese marker-selected key table do not require the source user's AES material.

The editor can be run directly for the default game-root profile:

```text
ProfileEditor.bat
```

Advanced source usage that writes a separate output profile:

```text
python profile-editor/profile_editor.py complete-collection \
  "<game-root>\\profile.bin" \
  "<game-root>\\profile-complete.bin"
```

The bundled `profile-editor/master` directory is used automatically. Use `--master-root` to select another master-data directory.

The command creates all collection records, sets characters to level 100 and their individual maximum rarity, completes their growthboards, maximizes Memoria level and limit break, completes historical events, completes all Bond chapters, and unlocks both branches of replayable Character Stories.

## Costumes And Custom Scenes

Unlocked character skins can be changed offline through the normal game UI. The replay generates `/character/skin_set` responses locally from the active profile.

Edit Home requests are generated locally as well. Custom character, background, motion, camera, BGM, and slot selections use `/chara_home/register`; favorite characters use `/profile/update_chara_home_favorite_character_list`; the selected Home background uses `/profile/update_selected_home_id`.

## Package Contents

```text
README.md
JapaneseCaptureObserver.md
game-root/
  AtelierReslerianaJapaneseOffline.bat
  StartJapaneseReplayProxy.bat
  ProfileEditor.bat
  ProfileEditor.exe
  replay_japanese.py
  expedition-special-rewards.json
  mitmdump.exe
  JapaneseCaptureObserver.exe
BepInEx/plugins/
  JapaneseOfflineProxy.dll
  JapaneseOfflineEvents.dll
  JapaneseProfileCapture.dll
  JapaneseOfflineClientRequestDiagnostics.dll
profile-editor/
  profile_editor.py
  profile-descriptors.pb
  historical-event-state.json
  requirements.txt
  master/*.json
source/
  README.md
  game-root/
  tools/
```
