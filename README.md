# WARNING: ENTIRELY LLM-GENERATED
Use at own risk, provided as-is.

## TLDR:
1. Copy contents of `game-root` next to `AtelierResleriana.exe`.
2. Copy contents of `BepInEx/plugins` into the game's `BepInEx/plugins` directory.
3. Launch the game normally once and log in. It should create a `profile.bin`.
4. Close the game, launch `AtelierReslerianaJapaneseOffline.bat` and log in. It should create a `aes-material.json` which is your profile's encryption key. You should be able to view characters etc.
5. (Optional) If you want to turn your `profile.bin` into a "master-save" with all characters, events completed, bond stories, etc. then close the game and run `ProfileEditor.bat`. Make sure to do this after step 4 as the program will need your profile's encryption key. Note that some parts of this are untested. Then you can use `AtelierReslerianaJapaneseOffline.bat`.
6. If you want to overwrite your profile with another login, rename/delete `profile.bin` and `aes-material.json` then perform steps 3-5 again. Every online play should create a folder like `japanese-capture/session-*` so you can manually replace the `profile.bin` and `aes-material.json` from there if you want.

## How you can help
1. Run `JapaneseCaptureObserver.exe` and play the game normally online.
2. Send the `japanese-capture/session-*` data to me (maybe zip the whole folder). (Note the session will still be recorded without `JapaneseCaptureObserver.exe` running, the executable just adds more data to the folder. It may still be valuable without it.)

What I'm looking for specifically.
- In combat, attack of every character (Skill 1, Skill 2, Burst)
  - In particular the ones unavailable now (especially Dark Memories), but it would be easiest if someone (or a small group of people) have all the characters between them and can coordinate getting data for every attack.
- Entering every fight in general
  - Training quests, material quests, dungeons (+ event dungeons), event battles, elemental tower, etc., just anything that involves a fight. Ideally complete the fight too and let the enemies do some attacks.

However, everything may be useful! Just try entering every single screen you can think of and send the data.

Additionally, there should be a bunch of "Home Scene" scenes that have a white thumbnail, because they are story-based scenes that were never intended to be selectable. I'm looking for high quality (4K?) screenshots of these scenes so I can replace the thumbnails. Just change to the scene, hide the UI (button should be on the right side, just a bit above the middle), and take a screenshot.

The rest of this README is LLM-generated.

# Atelier Resleriana Japanese Offline Toolkit

This folder contains the shareable runtime files for the Japanese Steam installation. It does not contain a personal `profile.bin`, capture session, AES material, or anonymization sidecar.

## Install

1. Copy the contents of `game-root` into the Japanese game directory beside `AtelierResleriana.exe`.
2. Copy the contents of `BepInEx/plugins` into the game's `BepInEx/plugins` directory.

The normal workflow does not require Python. `ProfileEditor.exe` includes the profile editor, protobuf descriptors, event state, and required master data. The package expects the game to have BepInEx installed and uses the directory containing the batch files as the game root. The offline launcher must be used instead of Steam for offline runs.

The `source` directory contains the source code for the custom scripts, compiled editor, observer, and BepInEx plugins. It also includes rebuild instructions. Third-party binaries such as `mitmdump.exe` and BepInEx/Unity libraries are not included as source.

## Online Capture

`JapaneseProfileCapture.dll` watches successful Japanese login responses. It always saves a session copy under `japanese-capture/session-*`. If the game-root `profile.bin` does not exist, the first successful online login creates it from that session copy. An existing root profile is never overwritten.

When the native observer has captured a complete key/IV pair, it saves `aes-material.json` beside the session profile and, once the root profile exists, beside the game-root `profile.bin`.

Offline Expedition reward collection is configured by `game-root/expedition-special-rewards.json`. The replay rotates through the seven valuable items associated with expedition sites 50-56 and marks each response as a rare special reward. The offline events plugin separately rotates the weighted `ExpeditionTimelineGroup` keys used by the client presentation, since changing the item ID alone does not change the cutscene. This is intended to trigger the special-reward presentation/cutscene and must be verified in-game.

Run `JapaneseCaptureObserver.exe` before an online Steam launch if fresh AES material is needed. The observer saves material into the newest capture session and does not launch or patch the game.

## Recommended Workflow

1. Launch the game normally through Steam and log in once. `JapaneseProfileCapture.dll` saves the session profile and creates the game-root profile if it does not already exist.
2. Close the game and double-click `AtelierReslerianaJapaneseOffline.bat`. The local proxy and native observer start automatically. Log in through the offline game once so the observer can capture the profile AES material.
3. Close the game, then double-click `ProfileEditor.bat`. It updates the game-root profile in place and creates a timestamped backup.
4. Double-click `AtelierReslerianaJapaneseOffline.bat` again to play offline with the completed profile.

No environment variables or absolute paths are required when the files are copied beside `AtelierResleriana.exe`. The batch files use their own directory as the game root.

Create `offline-session.txt` in the game root from `offline-session.example.txt` when a fixed capture session should be used. Otherwise the newest `japanese-capture/session-*` directory is selected.

Manual offline launch:

```text
AtelierReslerianaJapaneseOffline.bat
```

The launcher starts the local replay proxy, sets `JAPANESE_OFFLINE=1`, starts the game, and stops the proxy when the game exits. It also starts the capture observer if it is present and not already running.

## Profile Editor

The editor supports inspection, targeted edits, historical event state, collection unlocks, progression maximization, Bond chapters, and Character Stories. The normal entry point is `ProfileEditor.bat`; it runs the bundled `ProfileEditor.exe` against the game-root profile.

The editor defaults to the game-root `profile.bin` and adjacent `aes-material.json` when `ProfileEditor.bat` runs from the game directory. `JAPANESE_GAME_DIR` is only needed for advanced use of the raw Python editor from another directory.

The editor can be run directly for the default game-root profile:

```text
ProfileEditor.bat
```

Advanced source usage that writes a separate output profile:

```text
python profile-editor/profile_editor.py complete-collection \
  "C:\\path\\to\\profile.bin" \
  "C:\\path\\to\\profile-complete.bin"
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
