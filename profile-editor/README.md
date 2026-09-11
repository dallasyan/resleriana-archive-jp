# Japanese Profile Editor

The editor works with the Japanese `profile.bin` format captured from the current Steam client.

## Dependencies

```text
pip install pycryptodome protobuf
```

## Commands

Inspect the profile and show populated fields:

```text
python profile_editor.py inspect "path\to\profile.bin"
```

Export known protobuf fields to JSON:

```text
python profile_editor.py export "path\to\profile.bin" profile.json
```

Apply targeted edits to a new encrypted profile:

```text
python profile_editor.py edit "path\to\profile.bin" "path\to\profile-edited.bin" --set resources.wallet.<field>=123
```

When the profile path is omitted, the editor uses `profile.bin` in the detected Japanese game root. Set `JAPANESE_GAME_DIR` to select a specific game root. The editor selects the Japanese AES key from the profile's first-byte marker and uses the fixed Japanese IV; no `aes-material.json` is required.

The input profile is never overwritten by the `edit` command.

To anonymize the profile display name and the offline replay's player ID, supply both identity options to `edit` or `complete-collection`:

```text
python profile_editor.py edit "path\to\profile.bin" --in-place --player-name "Offline Player" --player-id 900000000001
```

`--player-name` changes `resources.profile.name` inside `profile.bin`. The player ID is not stored in `profile.bin`; `--player-id` writes `profile-anonymization.json` beside the input profile, and the offline replay patches the captured `/auth/sign_in` response from that sidecar. The sidecar also replaces the captured session token with a synthetic offline token. Apostrophes are preserved in the sidecar text. The protocol carries `user_id` as an integer, so a zero-padded ID is transmitted as numeric zero even though the requested display text is retained in the sidecar. Use `--anonymization-file` when the sidecar should be written elsewhere. The active profile is not changed until these values are supplied.

To inspect the installed game-root profile using its adjacent AES material:

```text
python profile_editor.py inspect
```

To update the default persistent game-root profile, use `--in-place`. It creates a timestamped copy in `profile-backups` beside the source before replacing it. Use `--backup-dir` to select another backup directory:

```text
python profile_editor.py edit "path\to\profile.bin" --in-place --backup-dir "path\to\profile-backups" --set resources.wallet.<field>=123
```

To unlock historical event stories and their post-battle chapters from the checked-in Japanese master data, generate a state manifest and apply it in place:

```text
python generate_event_state.py --output historical-event-state.json
python profile_editor.py edit "path\to\profile.bin" --in-place --state-file historical-event-state.json
```

The default manifest leaves `revived_events` unchanged because those entries represent completed revival state. Use `--include-revived-events` only when that behavior is intentional.

To unlock and maximize every character and Memoria, complete every Bond chapter and Character Story, add every Japanese recipe, every Japanese character skin/costume, every home background, every receivable photo background, every receivable pose/expression motion, every mod-timeline state, and historical event quest state, write a new profile:

```text
python profile_editor.py complete-collection "path\to\profile.bin" "path\to\profile-complete.bin"
```

For the default game-root profile and key, the equivalent in-place command is:

```text
python profile_editor.py complete-collection --in-place
```

The command applies the checked-in `historical-event-state.json` by default. Use `--state-file` to provide another state manifest. Use `--in-place` to update the profile with a timestamped backup. Existing records are upgraded to their supported maximums and missing records are added without duplicates. Characters are set to level 100, their per-character master-data maximum rarity, maximum normal/EX/Neo growthboard progress, maximum board stats, maximum board ability ranks, and maximum normal skill ranks. Memoria records are set to maximum level EXP and limit break while preserving the user's `is_locked` UI preference. Every home master row receives a `received_at` timestamp in the profile-owned home collection, including rows not marked `is_changeable_home`; these internal rows are included experimentally so the client can decide which Home Background Selection assets to expose. Recipe, skin, background, motion, and mod-timeline records also receive a `received_at` timestamp so the game treats them as learned/unlocked. Only master rows marked `is_receivable` are serialized into the profile-owned photo-background and motion collections by default; non-receivable rows remain client/master-data options. Use `--include-non-receivable-backgrounds` only for an experimental profile variant. Camera-related `key_tasks` from the photo frame, background, motion, and camera master data are also raised in `resources.total_task_counts`. Key quests from photo backgrounds, frames, CharaHome BGM, cameras, and mod timelines are also marked cleared so their client-side asset gates do not remain locked; the frame/camera/BGM definitions themselves remain client/master-data options rather than profile records.

Bond completion upserts one `communication_states` record per Bond character, releases and clears every available chapter, assigns the master-data reward scene, and raises Bond key-task counts to their required values.

Character Story completion upserts every record from `character_story.json`. Ordinary stories are cleared once with condition state 2. Branching stories are cleared twice with both condition states 2 and 3, matching the complete Japanese profile so both replayable branches are available.

The changeable home records cover the Home Background Selection categories such as Illustration, Memorial Scenes, and Story Scenes.

The `mod_timeline_states` records are the profile-side unlock state for photo-mode scenes such as "In Front of Friends". Adding them does not deduct wallet currency; the purchase cost in master data is a storefront condition used when the state is absent.

The editor uses the built-in Japanese 256-key table and fixed IV. Native observer output and online `session-*` material are not needed for normal profile inspection or editing.
