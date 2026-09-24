# Generated/Hybrid API Endpoint Coverage

This is the working tracker for API endpoints that should eventually be supported by the generated/hybrid offline server. Update the status here as handlers are implemented and validated.

## Inventory Sources

The endpoint baseline is taken from the route decorators in:

```text
ReslerianaServer-master/newserver/routes/*.py
ReslerianaServer-master/newserver/misc_routes.py
```

The corresponding request/response protobuf contracts are in:

```text
ReslerianaServer-master/blend/api.py
ReslerianaServer-master/blend/model.py
```

That server is an experimental Global-server reference, not a complete authoritative catalog of Japanese production routes. Japanese endpoints missing from that reference are added below when found in Japanese capture metadata. Japanese captures are evidence of real route use, but not treated as a complete inventory. `resleriana-db-main/data/master` supplies gameplay/master-data records and does not define the network route registry; its `navigation_task_url.json` contains external navigation links, not API routes.

## Japanese Full-Playthrough Inventory

A local audit of the Japanese full-playthrough captures counted 59 sessions, 8,233 game API records, and 66 distinct paths. Only the route names and counts are recorded here; capture files and personal profile snapshots remain outside the share package.

| Endpoint | Captured records |
|---|---:|
| `/atelier/research` | 36 |
| `/auth/sign_in` | 77 |
| `/auth/sign_up` | 2 |
| `/battle/attack` | 3,176 |
| `/battle/finish` | 646 |
| `/battle/retire` | 38 |
| `/character/enhance` | 57 |
| `/character/growboard_bulk_release` | 116 |
| `/character/growboard_page_release` | 67 |
| `/character/rarity_enhance` | 24 |
| `/dish/order` | 20 |
| `/emblem/acquisition_drama` | 7 |
| `/equipment_preset/bulk_set` | 4 |
| `/event/top` | 3 |
| `/expedition/reward_receive` | 11 |
| `/expedition/start` | 9 |
| `/exploration/battle_start` | 132 |
| `/exploration/explore` | 237 |
| `/exploration/finish` | 45 |
| `/exploration/start` | 45 |
| `/external_purchase/receive` | 229 |
| `/gacha/execute` | 50 |
| `/gacha/list` | 83 |
| `/gacha/wish_list_set` | 22 |
| `/growth_pack/bulk_receive` | 7 |
| `/illustrated_book/start` | 13 |
| `/login_bonus/receive` | 322 |
| `/mail/list` | 10 |
| `/mail/open` | 10 |
| `/mana/use_item` | 1 |
| `/memoria/enhance` | 13 |
| `/memoria/limit_break` | 53 |
| `/memoria/lock` | 109 |
| `/mission/navigation_task_proceed` | 4 |
| `/mission/receive` | 244 |
| `/party/battle_tools_set` | 4 |
| `/party/bulk_update` | 50 |
| `/profile/update_name` | 1 |
| `/quest/battle/skip` | 123 |
| `/quest/battle/start` | 553 |
| `/quest/daily_clear_add` | 9 |
| `/quest/street/start` | 3 |
| `/quest/street/talk` | 13 |
| `/quest/talk_event/finish` | 838 |
| `/recipe/count_reward_receive` | 29 |
| `/recipe/favorite` | 11 |
| `/recipe/learn` | 48 |
| `/refund_info/get_country_code` | 61 |
| `/ship/create` | 1 |
| `/shop/piece_exchange` | 15 |
| `/shop/purchase` | 19 |
| `/shop/random_shop/list` | 32 |
| `/shop/random_shop/refresh` | 4 |
| `/stamina/purchase` | 10 |
| `/stamina/use_item` | 16 |
| `/stamina/use_spare_stamina` | 17 |
| `/status` | 119 |
| `/synthesis/bulk_execute` | 46 |
| `/synthesis/combination_ranking` | 55 |
| `/synthesis/execute_rental` | 11 |
| `/tool/convert` | 22 |
| `/tool/lock` | 74 |
| `/tutorial/progress` | 1 |
| `/user/log_in` | 114 |
| `/user/unlink_steam` | 1 |
| `/web_session/token` | 11 |

## Supplemental Upgrade Capture

A separate local upgrade session added 23 progression operations. The raw session and profile snapshot are not shared.

| Endpoint | Captured operations |
|---|---:|
| `/character/enhance` | 2 |
| `/character/enhancement_reset` | 2 |
| `/character/growboard_bulk_release` | 12 |
| `/character/growboard_page_release` | 2 |
| `/character/level_limit_release` | 4 |
| `/character/rarity_enhance` | 1 |

## Status Legend

- **Implemented**: a generated handler is present in `tools/JapaneseOffline/replay_japanese.py`.
- **Hybrid capture**: the bundled `embedded-handshake` has the response used for startup/login.
- **Partial/stub**: a response exists but does not model the complete server-side state transition.
- **Replay-only**: `-replay` can answer if the selected capture contains the route; generated/hybrid has no general handler.
- **Missing**: generated/hybrid returns a generated miss/503 for this route.
- **Client bypass**: the client plugin short-circuits the API method; there is no proxy-side endpoint handler.

## Currently Covered

| Endpoint | Mode | Notes |
|---|---|---|
| `/status` | Hybrid capture; generated static response | Status/title/bootstrap metadata. |
| `/refund_info/get_country_code` | Hybrid capture; generated empty response | No country-code payload. |
| `/auth/sign_in` | Hybrid capture; generated handler | Packaged auth response is anonymized during preparation. |
| `/user/log_in` | Hybrid capture; generated handler | Asset negotiation followed by the current game-root `profile.bin`. |
| `/login_bonus/receive` | Hybrid capture; generated stub | Generated mode returns a fixed regular bonus response. |
| `/external_purchase/receive` | Hybrid capture; generated empty response | The captured/generated empty form is a 17-byte encrypted envelope and omits `X-Content-Encoding: gzip`. |
| `/web_session/token` | Hybrid capture; generated empty response | No web session is created. |
| `/character/skin_set` | Generated | Mutates the active profile and persists it. |
| `/party/bulk_update` | Generated | Updates parties and party members; persists changes. |
| `/party/battle_tools_set` | Generated | Updates assigned battle tools; persists changes. |
| `/character/bulk_set` | Generated | Bulk-updates equipment and equipped Memoria; persists changes. |
| `/character/equip` | Generated | Updates equipment; persists changes. |
| `/character/memoria_set` | Generated | Updates equipped Memoria; persists changes. |
| `/equipment_preset/bulk_set` | Generated | Updates equipment presets; persists changes. |
| `/character/enhance` | Generated | Consumes EXP items, caps EXP one point below the threshold from `growboard_level_limit + level_limit_increase_value + 1`, charges 10% of item EXP in Cole, updates level/milestone missions, and persists. |
| `/character/rarity_enhance` | Generated | Uses Japanese rarity/piece/additional-cost tables; updates character, pieces, Neo maximum page, items, Cole, awaken totals, and character-specific awaken tasks. |
| `/character/enhancement_reset` | Generated | Captured level-only/full reset refunds EXP items, Cole, released panel costs, and mission progress. Resetting after level-limit release uses the Japanese step-cost table; that combined case is not separately captured. |
| `/character/level_limit_release` | Generated | Applies the four Japanese item-cost steps and advances `level_limit_increase_value` by 2/3/2/3; persists changes. |
| `/character/growboard_page_release` | Generated | Releases the next completed normal/EX/Neo page using wrapped Japanese `board_type` and `is_ex` fields. Normal and Neo page-release requests are captured. |
| `/character/growboard_bulk_release` | Generated | Captured all three selections: normal `(1,false)`, EX `(1,true)`, Neo `(2,false)`. Applies 7/6/8-bit panels, costs, stats, role rates, Neo ability rank, and task progress. |
| `/memoria/enhance` | Generated | Consumes EXP items/Memoria, applies Cole and EXP changes, reports deleted entities, and persists. |
| `/memoria/limit_break` | Generated | Consumes duplicate Memoria entities, updates limit break/task progress, reports deletions, and persists. |
| `/memoria/lock` | Generated | Updates the selected Memoria lock state and persists. |
| `/memoria/sell` | Generated | Sells unlocked Memoria using Japanese rarity values; returns Cole reward/deletions and persists. |
| `/chara_home/register` | Generated | Updates Home configuration; persists changes. |
| `/profile/update_chara_home_favorite_character_list` | Generated | Updates Home favorites; persists changes. |
| `/profile/update_selected_home_id` | Generated | Updates selected Home; persists changes. |
| `/illustrated_book/start` | Generated | Uses unique profile Memoria IDs and configured expedition/exploration treasure IDs. |
| `/recipe/learn` | Partial/stub | Returns a fixed successful no-op response; its captured 17-byte envelope omits `X-Content-Encoding: gzip`. |
| `/exploration/start` | Generated | Starts exploration from the selected profile party and route table; persists progress. |
| `/exploration/finish` | Partial/stub | Returns an empty successful finish response. |
| `/expedition/reward_receive` | Partial/stub | Generated mode returns an empty response; special reward patch is available only in replay mode. |
| `/quest/talk_event/finish` | Client bypass | Offline Events plugin bypasses the client request. |
| CDN `/master_data/*`, `/manifest.json` | Generated/local asset | Served by the mitmproxy addon, outside the game API `Replay.respond` route table. |

Hybrid mode also declares `/mail/list` and `/mail/open` as initialization replay paths. Both appear in the local Japanese full-playthrough inventory, but their records are not included in the share package and there is no generated fallback; treat them as **Missing** in the shared runtime.

## Battle Endpoints

These are kept together because battle entry, previews, actions, and results form one dependency chain. Battle endpoint request/response contracts are defined in `blend/api.py`; Japanese captures provide concrete examples. None currently has a generated battle simulation handler.

| Status | Endpoint | Evidence / notes |
|---|---|---|
| - [ ] Missing | `/quest/battle/start` | Captured Japanese endpoint; returns battle-start history/context. |
| - [ ] Missing | `/battle/attack` | Captured Japanese endpoint; request carries skill/tool commands; response contains action history and preview/action data. |
| - [ ] Missing | `/battle/resume` | `BattleResumeResponse` schema; no generated response. |
| - [ ] Missing | `/battle/retire` | Battle retirement/result route; no generated response. |
| - [ ] Missing | `/battle/finish` | Captured Japanese endpoint; returns final battle/resource result. |
| - [ ] Missing | `/quest/battle/skip` | Captured Japanese endpoint; no generated skip result. |
| - [ ] Missing | `/quest/battle/total_battle_start` | Schema-defined start variant; no generated response. |
| - [ ] Missing | `/quest/battle/solo_raid_battle_start` | Schema-defined start variant; no generated response. |
| - [ ] Missing | `/quest/battle/rental_party_start` | Schema-defined start variant; no generated response. |
| - [ ] Missing | `/exploration/battle_start` | Captured Japanese dungeon battle entry; no generated battle response. |
| - [ ] Missing | `/gacha/battle_start` | Schema-defined gacha battle entry; no generated response. |

Captured `BattleHistory.action_setups.skill_selections` includes preview values such as `hp_damage`, `hp_damage_for_critical`, `critical_rate`, `break_damage`, weakness/resistance flags, and timeline changes. Use these response fields as combat-test oracles when battle simulation work begins.

**Loss-path observation (Japanese capture 2026-09-24):** `/quest/battle/start` can return a `BattleStartResponse` whose `history.status` is already `lost`. In this case, the enemy was faster than the party and acted first in the initial timeline; its action in `actions` killed the party before the player could attack. The response included `wave_starts`, `action_setups`, and that enemy action's `skill_results`/`effect_results`; no `/battle/attack` request occurred. The client then sent a bodyless `/battle/retire`, which returned HTTP 200 with an empty `ChangedResourcesResponse`. Generated battle-start handling must resolve the initial speed-ordered timeline and include enemy opening actions, including a terminal loss before player input when the party is defeated.

## Other Missing Reference-Server Routes

These routes are not currently implemented by the generated/hybrid Japanese replay. Items marked Japanese-capture-only were observed in local Japanese sessions; `-replay` may answer only if a selected capture contains the route.

### Character, equipment, and Memoria progression

- [ ] `/equipment_preset/equip`
- [ ] `/equipment_preset/memoria_set`
- [ ] `/equipment_preset/update_name`
- [ ] `/tool/convert`
- [ ] `/tool/lock` (Japanese capture only)

### Profile, mail, mission, and progression

- [ ] `/atelier/research` (Japanese capture only)
- [ ] `/profile/update_name` (also observed in Japanese captures)
- [ ] `/profile/update_memo`
- [ ] `/profile/update_favorite_character`
- [ ] `/profile/update_favorite_party`
- [ ] `/profile/update_favorite_battle_tools`
- [ ] `/mail/delete`
- [ ] `/mission/receive` (also observed in Japanese captures)
- [ ] `/mission/count_reward_receive` (also observed in Japanese captures)
- [ ] `/mission/navigation_task_proceed` (Japanese capture only)
- [ ] `/quest/daily_clear_add`
- [ ] `/quest/street/start` (Japanese capture only)
- [ ] `/quest/street/talk` (Japanese capture only)
- [ ] `/daily_pass/bulk_receive` (Japanese capture only; absent from reference route registry)

### Expedition and exploration

- [ ] `/expedition/start` (also observed in Japanese captures)
- [ ] `/exploration/update_party`
- [ ] `/exploration/explore`
- [ ] `/exploration/retire`
- [ ] `/exploration/skip`

### Economy, shops, synthesis, and gacha

- [ ] `/dish/order` (also observed in Japanese captures)
- [ ] `/mana/purchase`
- [ ] `/mana/use_item` (Japanese capture only)
- [ ] `/stamina/purchase` (also observed in Japanese captures)
- [ ] `/stamina/use_item`
- [ ] `/stamina/use_spare_stamina`
- [ ] `/shop/gem_list` (also observed in Japanese captures)
- [ ] `/shop/purchase` (also observed in Japanese captures)
- [ ] `/shop/random_shop/list` (also observed in Japanese captures)
- [ ] `/shop/random_shop/purchase`
- [ ] `/shop/piece_exchange` (Japanese capture only; absent from reference route registry)
- [ ] `/shop/random_shop/refresh` (Japanese capture only; absent from reference route registry)
- [ ] `/synthesis/bulk_execute` (also observed in Japanese captures)
- [ ] `/synthesis/combination_ranking` (also observed in Japanese captures)
- [ ] `/synthesis/execute_rental` (also observed in Japanese captures)
- [ ] `/synthesis/execute_easy`
- [ ] `/gacha/list` (Japanese capture only; absent from reference route registry)
- [ ] `/gacha/execute` (Japanese capture only; absent from reference route registry)
- [ ] `/gacha/wish_list_set` (Japanese capture only)
- [ ] `/growth_pack/bulk_receive` (Japanese capture only)
- [ ] `/emblem/acquisition_drama` (Japanese capture only)
- [ ] `/recipe/favorite` (Japanese capture only)
- [ ] `/recipe/count_reward_receive` (Japanese capture only)
- [ ] `/ship/create` (Japanese capture only; absent from reference route registry)
- [ ] `/event/top` (Japanese capture only; absent from reference route registry)
- [ ] `/auth/sign_up` (Japanese capture only)
- [ ] `/user/unlink_steam` (Japanese capture only)
- [ ] `/tutorial/progress` (Japanese capture only)

## Japanese Hybrid Paths Needing Bundled Responses or Generated Fallbacks

- [ ] `/mail/list` — observed in local captures and listed in `HYBRID_INIT_PATHS`, but no record is bundled and no generated handler exists.
- [ ] `/mail/open` — observed in local captures and listed in `HYBRID_INIT_PATHS`, but no record is bundled and no generated handler exists.

## Updating This Tracker

For each endpoint, update its checkbox/status only after the generated or hybrid behavior is implemented and verified. Keep a short note describing whether it is stateful, a no-op/stub, client-bypassed, or capture-only. Update the separate Battle section when implementing battle-related paths; do not classify an endpoint as implemented solely because it appears in a capture or schema.
