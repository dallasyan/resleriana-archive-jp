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

## Supplemental Recent Exploration Capture

The installed current-session captures include two exploration routes not
present in the full-playthrough audit above. The archived capture tree added no
other exploration route names beyond that inventory; session names and payloads
remain private.

| Endpoint | Captured records |
|---|---:|
| `/exploration/retire` | 1 |
| `/exploration/skip` | 1 |

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

## Supplemental Ship and Equipment Progression Capture

A local three-session Japanese capture on 2026-09-25 covered ship/subspace equipment and character/equipment/Memoria configuration. The captured profile snapshots remain private; only endpoint names and operation counts are tracked here.

| Endpoint | Captured operations |
|---|---:|
| `/character/bulk_set` | 1 |
| `/character/equip` | 2 |
| `/character/memoria_set` | 1 |
| `/equipment_preset/bulk_set` | 1 |
| `/equipment_preset/equip` | 1 |
| `/equipment_preset/memoria_set` | 1 |
| `/mana/use_item` | 1 |
| `/party/bulk_update` | 2 |
| `/ship/bulk_update` | 4 |
| `/ship/create` | 3 |
| `/ship/ship_tools_set` | 1 |
| `/tool/convert` | 2 |
| `/tool/lock` | 2 |

## Supplemental Gacha Capture

A local Japanese session on 2026-09-25 recorded 24 pulls from one banner, three gacha-list refreshes, wishlist changes, and the associated web-session token requests. Pull results and profile data remain private. The captured GachaListResponse includes exact rates and card lists for five standard and 22 mixed-wishlist sets. Japanese `gacha_rate.json`/`gacha_deck.json` provide rate-set/deck categories, priorities, pickup/wishlist flags, card types, and rarities; they do not enumerate explicit card-pool membership or calculated per-card percentages.

| Endpoint | Captured operations |
|---|---:|
| `/gacha/execute` | 24 |
| `/gacha/list` | 3 |
| `/gacha/wish_list_set` | 4 |
| `/web_session/token` | 28 |

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
| `/web_session/token` | Generated | Returns a fresh synthetic UUID in `WebSessionTokenResponse`; the route supplies a web-session credential, not article content. |
| `/gacha/list` | Generated (snapshot) | Serves the 27 snapshot banners, 5 decoded rate sets, 22 verbatim mixed-wishlist sets, and synthesized empty wishlist states from `gacha-snapshot.json`; button counts come from the runtime `gacha-state.json` sidecar. |
| `/gacha/execute` | Generated (snapshot) | Weighted draws from snapshot pools/rates for all five standard banners (character, Memoria, mixed pools; single and ten draws) plus wishlist banners with and without selections (picks weigh 1.0 each, unselected pickup cards 0.5 each); rarity-keyed duplicate conversion, duplicate Memoria as extra entities with first-copy flag, ticket/item/gem costs, medal grants, Memoria entity allocation, profile persistence, and sidecar counts. Bonus and step-up pulls return 503. |
| `/character/skin_set` | Generated | Mutates the active profile and persists it. |
| `/party/bulk_update` | Generated | Updates parties and party members; persists changes. |
| `/party/battle_tools_set` | Generated | Updates assigned battle tools; persists changes. |
| `/character/bulk_set` | Generated | Bulk-updates equipment and equipped Memoria; persists changes. |
| `/character/equip` | Generated | Updates equipment; persists changes. |
| `/character/memoria_set` | Generated | Updates equipped Memoria; persists changes. |
| `/equipment_preset/bulk_set` | Generated | Updates equipment presets; persists changes. |
| `/equipment_preset/equip` | Generated | Sets or clears one equipment slot in a preset; persists changes. |
| `/equipment_preset/memoria_set` | Generated | Sets or clears the Memoria in a preset; persists changes. |
| `/equipment_preset/update_name` | Generated (schema-backed) | Updates a preset display name; Japanese capture evidence is not yet available. |
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
| `/tool/lock` | Generated | Locks or unlocks a Battle Tool or Equipment Tool; persists changes. |
| `/tool/convert` | Generated | Converts Battle Tools or Equipment Tools using Japanese rarity/trait-rank rewards, removes converted entities, and persists. |
| `/chara_home/register` | Generated | Updates Home configuration; persists changes. |
| `/profile/update_chara_home_favorite_character_list` | Generated | Updates Home favorites; persists changes. |
| `/profile/update_selected_home_id` | Generated | Updates selected Home; persists changes. |
| `/illustrated_book/start` | Generated | Uses unique profile Memoria IDs and configured expedition/exploration treasure IDs. |
| `/profile/update_name` | Generated | Updates the profile display name and persists the profile submessage. |
| `/profile/update_memo` | Generated | Updates the profile memo and persists the profile submessage. |
| `/profile/update_favorite_character` | Generated | Updates the profile's favorite character ID. |
| `/profile/update_favorite_party` | Generated | Sets/clears the five wrapped favorite-party character IDs. |
| `/profile/update_favorite_battle_tools` | Generated | Updates the repeated favorite Battle Tool entity IDs. |
| `/recipe/learn` | Partial/stub | Returns a fixed successful no-op response; its captured 17-byte envelope omits `X-Content-Encoding: gzip`. |
| `/recipe/favorite` | Generated | Updates the learned recipe's favorite flag in profile resources and persists it. |
| `/dish/order` | Generated | Uses Japanese dish rewards, consumes one available order, updates dish refresh time, task counts, and profile resources. |
| `/synthesis/bulk_execute` | Generated (approximate) | Consumes recipe costs, Mana, and optional ingredient; creates Battle/Equipment Tools from Japanese character/item trait pools. Selected eligible traits are forced into output slots; ranks use the requested 60% rank-5 / 10% rank-1–4 distribution. Persists tools, items, Mana, and recipe history. |
| `/synthesis/execute_easy` | Generated (profile-local fallback) | Uses the recipe's most recent local character/material combination, or an owned-character/material fallback, then runs generated synthesis. |
| `/synthesis/combination_ranking` | Partial (local history) | Returns the profile's most recent local combination for each ranking period; empty lists when the recipe has no history. No public leaderboard is bundled. |
| `/synthesis/execute_rental` | Partial (local fallback) | Generates rental synthesis using a local recipe combination or owned-character/material fallback, with a daily count limit. It does not reproduce the online public rental ranking. |
| `/exploration/start` | Generated | Starts exploration from the selected profile party and route table; persists progress. |
| `/exploration/update_party` | Generated | Updates the active exploration's party number and applies a captured party-status template when available. |
| `/exploration/explore` | Partial | Advances talk/gathering routes, persists progress, and applies gathering rewards immediately; common event/story gathering mappings are implemented, with a generic material fallback for unmapped types. Battle routes use `/exploration/battle_start`; their win updates route progress. |
| `/exploration/finish` | Generated | Applies the completed quest clear and removes active progress; gathering items are already persisted when `/exploration/explore` succeeds. |
| `/exploration/retire` | Generated | Clears active non-story progress and returns the captured bodyless success response. |
| `/exploration/skip` | Partial | Returns per-clear and aggregate gathering rewards, updates clear count, and persists item totals. Other skip reward/task details remain approximate. |
| `/expedition/start` | Generated | Collects elapsed rewards for replaced slots, saves new expedition assignments, and persists item/Cole changes. |
| `/expedition/reward_receive` | Partial | Refreshes active expedition timers and generates rank/material-pool rewards with a 120-hour cap; special rewards and character-piece details remain approximate. Full replay still patches its captured response. |
| `/quest/street/start` | Generated | Initializes `StreetState` from Japanese street-phase data. |
| `/quest/street/talk` | Generated | Validates the current talk phase, records played talk IDs, advances phases, and completes the final phase with task/profile updates. |
| `/mail/list` | Generated (empty fallback) | Returns an empty `MailListResponse` when hybrid startup has no bundled record. No online mailbox data is included in the package. |
| `/mail/open` | Generated (empty fallback) | Returns empty changed resources and mail list when hybrid startup has no bundled record; does not grant captured account-specific attachments. |
| `/mana/use_item` | Generated | Consumes Mana items, applies Japanese hourly regeneration, updates Mana, and persists. |
| `/ship/bulk_update` | Generated (Japanese capture) | Updates ship-party characters and Memoria selections; persists changes. |
| `/ship/ship_tools_set` | Generated (Japanese capture) | Updates ship-party support/cannon selections; persists changes. |
| `/ship/create` | Generated (Japanese capture) | Applies Japanese ship-part costs to Mana/items and advances ship/ship-tool EXP or rank; persists changes. |
| `/quest/talk_event/finish` | Client bypass | Offline Events plugin bypasses the client request. |
| CDN `/master_data/*`, `/manifest.json` | Generated/local asset | Served by the mitmproxy addon, outside the game API `Replay.respond` route table. |

Hybrid mode also declares `/mail/list` and `/mail/open` as initialization replay paths. Their captured mailbox contents remain private; if no startup record is bundled, the generated empty responses above are used.

## Battle Endpoints

These are kept together because battle entry, previews, actions, and results form one dependency chain. The generated battle simulation (`battle_japanese.py`) resolves a simplified turn loop against `battle-master` tables: speed-ordered starts, wait-based repositioning, physical/magic affinity with weak/resist flags, panel effects, party-gauge bursts, break gauges, and generic buff stacking. Damage numbers are calibrated estimates, not exact replicas.

| Status | Endpoint | Evidence / notes |
|---|---|---|
| - [x] Implemented | `/quest/battle/start` | Generated history/context from quest, party, and wave tables; stamina deducted; full quest rewards (score-rank sets, drops, first-clear, EXP, missions, quest states) on finish. |
| - [x] Implemented | `/battle/attack` | Generated action resolution for skill/auto, batched free battle-tool actions, and Japanese cannon mode 9; captured selectable-target, damage-result, skill-motion, timeline-move, enemy-turn, wave-transition, and win/loss shapes. Damage values and many passive/effect behaviors remain approximate. |
| - [x] Implemented | `/battle/resume` | Returns the active generated battle history/context; 503 with no active battle. |
| - [x] Implemented | `/battle/retire` | Clears the active battle; empty `ChangedResourcesResponse`. |
| - [x] Implemented | `/battle/finish` | Generated quest/exploration/gacha results with rewards and profile persistence; 503 unless the active battle is won. |
| - [x] Implemented | `/quest/battle/skip` | Generated per-clear piece/Cole rewards, drop rolls, EXP, clear counts, and stamina cost. |
| - [ ] Missing | `/quest/battle/total_battle_start` | Schema-only start variant; no generated response. |
| - [ ] Missing | `/quest/battle/solo_raid_battle_start` | Schema-only start variant; no generated response. |
| - [ ] Missing | `/quest/battle/rental_party_start` | Schema-only start variant; no generated response. |
| - [x] Implemented | `/exploration/battle_start` | Generated battles from exploration-area tables with weighted encounters. |
| - [x] Implemented | `/gacha/battle_start` | Generated battles from gacha-battle tables with fixed parties and first-clear tracking. |

Captured `BattleHistory.action_setups.skill_selections` includes preview values such as `hp_damage`, `hp_damage_for_critical`, `critical_rate`, `break_damage`, weakness/resistance flags, and timeline changes. Use these response fields as combat-test oracles when battle simulation work begins.

**Loss-path observation (Japanese capture 2026-09-24):** `/quest/battle/start` can return a `BattleStartResponse` whose `history.status` is already `lost`. In this case, the enemy was faster than the party and acted first in the initial timeline; its action in `actions` killed the party before the player could attack. The response included `wave_starts`, `action_setups`, and that enemy action's `skill_results`/`effect_results`; no `/battle/attack` request occurred. The client then sent a bodyless `/battle/retire`, which returned HTTP 200 with an empty `ChangedResourcesResponse`. Generated battle-start handling must resolve the initial speed-ordered timeline and include enemy opening actions, including a terminal loss before player input when the party is defeated.

## Other Missing Reference-Server Routes

These routes are not currently implemented by the generated/hybrid Japanese replay. Items marked Japanese-capture-only were observed in local Japanese sessions; `-replay` may answer only if a selected capture contains the route.

### Character, equipment, and Memoria progression

- All currently implemented routes in this section are listed under **Currently Covered** above.

### Profile, mail, mission, and progression

- [ ] `/atelier/research` (Japanese capture only)
- [ ] `/mail/delete`
- [ ] `/mission/receive` (also observed in Japanese captures)
- [ ] `/mission/count_reward_receive` (also observed in Japanese captures)
- [ ] `/mission/navigation_task_proceed` (Japanese capture only)
- [ ] `/quest/daily_clear_add`
- `/quest/street/start` and `/quest/street/talk` are listed under **Currently Covered** above.
- [ ] `/daily_pass/bulk_receive` (Japanese capture only; absent from reference route registry)

### Expedition and exploration

- All prioritized expedition and exploration routes are listed under **Currently Covered** above.

### Economy, shops, synthesis, and gacha

- [ ] `/mana/purchase`
- [ ] `/stamina/purchase` (also observed in Japanese captures)
- [ ] `/stamina/use_item`
- [ ] `/stamina/use_spare_stamina`
- [ ] `/shop/gem_list` (also observed in Japanese captures)
- [ ] `/shop/purchase` (also observed in Japanese captures)
- [ ] `/shop/random_shop/list` (also observed in Japanese captures)
- [ ] `/shop/random_shop/purchase`
- [ ] `/shop/piece_exchange` (Japanese capture only; absent from reference route registry)
- [ ] `/shop/random_shop/refresh` (Japanese capture only; absent from reference route registry)
- All prioritized synthesis routes are listed under **Currently Covered** above.
- [x] `/gacha/list` (generated from the sanitized `gacha-snapshot.json`: 27 snapshot banners, 5 decoded rate sets, 22 verbatim mixed-wishlist sets; wishlist states and button counts from the runtime `gacha-state.json` sidecar)
- [x] `/gacha/execute` (generated weighted draws from snapshot pools: all five standard banners including mixed character/Memoria pools and single draws, plus wishlist banners with and without selections; wishlist picks weigh 1.0 each, unselected pickup cards 0.5 each, base/dynamic pools keep captured weights; rarity-keyed duplicate conversion (1/10/50 pieces), duplicate Memoria granted as extra entities with a first-copy flag, ticket/item/gem cost handling, medal grants, Memoria entity allocation, profile persistence, and sidecar counts; bonus and step-up pulls return 503)
- [x] `/gacha/wish_list_set` (generated; validates pickup membership and select counts against snapshot wishlist rules and persists selections in the `gacha-state.json` sidecar)
- [ ] `/growth_pack/bulk_receive` (Japanese capture only)
- [ ] `/emblem/acquisition_drama` (Japanese capture only)
- [ ] `/recipe/count_reward_receive` (Japanese capture only)
- [ ] `/event/top` (Japanese capture only; absent from reference route registry)
- [ ] `/auth/sign_up` (Japanese capture only)
- [ ] `/user/unlink_steam` (Japanese capture only)
- [ ] `/tutorial/progress` (Japanese capture only)

## Japanese Hybrid Paths Needing Bundled Responses or Generated Fallbacks

- None. `/mail/list` and `/mail/open` use generated empty fallbacks when no startup record is bundled.

## Updating This Tracker

For each endpoint, update its checkbox/status only after the generated or hybrid behavior is implemented and verified. Keep a short note describing whether it is stateful, a no-op/stub, client-bypassed, or capture-only. Update the separate Battle section when implementing battle-related paths; do not classify an endpoint as implemented solely because it appears in a capture or schema.

<!-- BEGIN GENERATED PROTOBUF CONTRACT MAP -->
## Protobuf Contract Mapping

Names below come from the installed client `contract-dump/fields.txt`. Shared response types (especially `ChangedResourcesResponse`) legitimately serve multiple routes. `Empty`, JSON, and asset entries are non-route-specific wire shapes rather than missing protobuf definitions.

| Endpoint | Request definition | Response definition |
|---|---|---|
| `/atelier/research` | `blend.api.AtelierResearchRequest` | `blend.api.ChangedResourcesResponse` |
| `/auth/sign_in` | `blend.api.AuthSignInRequest` | `blend.api.AuthSignInResponse` |
| `/auth/sign_up` | `blend.api.AuthSignUpRequest` | `blend.api.AuthSignUpResponse` |
| `/battle/attack` | `blend.api.BattleAttackRequest` | `blend.api.BattleAttackResponse` |
| `/battle/finish` | `google.protobuf.Empty` | `blend.api.BattleFinishResponse` |
| `/battle/retire` | `google.protobuf.Empty` | `blend.api.ChangedResourcesResponse` |
| `/character/enhance` | `blend.api.CharacterEnhanceRequest` | `blend.api.ChangedResourcesResponse` |
| `/character/growboard_bulk_release` | `blend.api.CharacterGrowboardBulkReleaseRequest` | `blend.api.ChangedResourcesResponse` |
| `/character/growboard_page_release` | `blend.api.CharacterGrowboardPageReleaseRequest` | `blend.api.ChangedResourcesResponse` |
| `/character/rarity_enhance` | `blend.api.CharacterRarityEnhanceRequest` | `blend.api.ChangedResourcesResponse` |
| `/dish/order` | `blend.api.DishOrderRequest` | `blend.api.DishOrderResponse` |
| `/emblem/acquisition_drama` | `blend.api.EmblemAcquisitionDramaRequest` | `blend.api.ChangedResourcesResponse` |
| `/equipment_preset/bulk_set` | `blend.api.EquipmentPresetBulkSetRequest` | `blend.api.ChangedResourcesResponse` |
| `/event/top` | `No matching request definition in fields.txt` | `blend.api.EventTopResponse` |
| `/expedition/reward_receive` | `google.protobuf.Empty` | `blend.api.ExpeditionRewardReceiveResponse` |
| `/expedition/start` | `blend.api.ExpeditionStartRequest` | `blend.api.ExpeditionStartResponse` |
| `/exploration/battle_start` | `blend.api.ExplorationBattleStartRequest` | `blend.api.BattleStartResponse` |
| `/exploration/explore` | `blend.api.ExplorationExploreRequest` | `blend.api.ExplorationExploreResponse` |
| `/exploration/finish` | `blend.api.ExplorationFinishRequest` | `blend.api.ExplorationFinishResponse` |
| `/exploration/start` | `blend.api.ExplorationStartRequest` | `blend.api.ChangedResourcesResponse` |
| `/external_purchase/receive` | `google.protobuf.Empty` | `Empty encrypted envelope` |
| `/gacha/execute` | `blend.api.GachaExecuteRequest` | `blend.api.GachaExecuteResponse` |
| `/gacha/list` | `google.protobuf.Empty` | `blend.api.GachaListResponse` |
| `/gacha/wish_list_set` | `blend.api.GachaWishListSetRequest` | `blend.api.GachaWishListSetResponse` |
| `/growth_pack/bulk_receive` | `blend.api.GrowthPackBulkReceiveRequest` | `blend.api.GrowthPackBulkReceiveResponse` |
| `/illustrated_book/start` | `blend.api.IllustratedBookStartRequest` | `blend.api.IllustratedBookStartResponse` |
| `/login_bonus/receive` | `google.protobuf.Empty` | `blend.api.LoginBonusReceiveResponse` |
| `/mail/list` | `google.protobuf.Empty` | `blend.api.MailListResponse` |
| `/mail/open` | `blend.api.MailOpenRequest` | `blend.api.MailOpenResponse` |
| `/mana/use_item` | `blend.api.ManaUseItemRequest` | `blend.api.ChangedResourcesResponse` |
| `/memoria/enhance` | `blend.api.MemoriaEnhanceRequest` | `blend.api.MemoriaEnhanceResponse` |
| `/memoria/limit_break` | `blend.api.MemoriaLimitBreakRequest` | `blend.api.MemoriaLimitBreakResponse` |
| `/memoria/lock` | `blend.api.MemoriaLockRequest` | `blend.api.ChangedResourcesResponse` |
| `/mission/navigation_task_proceed` | `blend.api.MissionNavigationTaskProceedRequest` | `blend.api.ChangedResourcesResponse` |
| `/mission/receive` | `blend.api.MissionReceiveRequest` | `blend.api.MissionReceiveResponse` |
| `/party/battle_tools_set` | `blend.api.PartyBattleToolsSetRequest` | `blend.api.ChangedResourcesResponse` |
| `/party/bulk_update` | `blend.api.PartyBulkUpdateRequest` | `blend.api.ChangedResourcesResponse` |
| `/profile/update_name` | `blend.api.ProfileUpdateNameRequest` | `blend.api.ChangedResourcesResponse` |
| `/quest/battle/skip` | `blend.api.QuestBattleSkipRequest` | `blend.api.QuestBattleSkipResponse` |
| `/quest/battle/start` | `blend.api.QuestBattleStartRequest` | `blend.api.BattleStartResponse` |
| `/quest/daily_clear_add` | `blend.api.QuestDailyClearAddRequest` | `blend.api.ChangedResourcesResponse` |
| `/quest/street/start` | `blend.api.QuestStreetStartRequest` | `blend.api.ChangedResourcesResponse` |
| `/quest/street/talk` | `blend.api.QuestStreetTalkRequest` | `blend.api.ChangedResourcesResponse` |
| `/quest/talk_event/finish` | `blend.api.QuestTalkEventFinishRequest` | `blend.api.QuestTalkEventFinishResponse` |
| `/recipe/count_reward_receive` | `blend.api.RecipeCountRewardReceiveRequest` | `blend.api.RecipeCountRewardReceiveResponse` |
| `/recipe/favorite` | `blend.api.RecipeFavoriteRequest` | `blend.api.ChangedResourcesResponse` |
| `/recipe/learn` | `google.protobuf.Empty` | `blend.api.RecipeLearnResponse` |
| `/refund_info/get_country_code` | `google.protobuf.Empty` | `blend.api.RefundInfoGetCountryCodeResponse` |
| `/ship/create` | `blend.api.ShipCreateRequest` | `blend.api.ChangedResourcesResponse` |
| `/shop/piece_exchange` | `blend.api.ShopPieceExchangeRequest` | `blend.api.ChangedResourcesResponse` |
| `/shop/purchase` | `blend.api.ShopPurchaseRequest` | `blend.api.ShopPurchaseResponse` |
| `/shop/random_shop/list` | `blend.api.ShopRandomShopListRequest` | `blend.api.ShopRandomShopListResponse` |
| `/shop/random_shop/refresh` | `blend.api.ShopRandomShopRefreshRequest` | `blend.api.ShopRandomShopRefreshResponse` |
| `/stamina/purchase` | `blend.api.StaminaPurchaseRequest` | `blend.api.ChangedResourcesResponse` |
| `/stamina/use_item` | `blend.api.StaminaUseItemRequest` | `blend.api.ChangedResourcesResponse` |
| `/stamina/use_spare_stamina` | `blend.api.StaminaUseSpareStaminaRequest` | `blend.api.ChangedResourcesResponse` |
| `/status` | `JSON` | `JSON` |
| `/synthesis/bulk_execute` | `blend.api.SynthesisBulkExecuteRequest` | `blend.api.SynthesisExecuteResponse` |
| `/synthesis/combination_ranking` | `blend.api.SynthesisCombinationRankingRequest` | `blend.api.SynthesisCombinationRankingResponse` |
| `/synthesis/execute_rental` | `blend.api.SynthesisExecuteRentalRequest` | `blend.api.SynthesisExecuteResponse` |
| `/tool/convert` | `blend.api.ToolConvertRequest` | `blend.api.ToolConvertResponse` |
| `/tool/lock` | `blend.api.ToolLockRequest` | `blend.api.ChangedResourcesResponse` |
| `/tutorial/progress` | `No matching request definition in fields.txt` | `No matching response definition in fields.txt` |
| `/user/log_in` | `google.protobuf.Empty` | `blend.api.UserLogInResponse` |
| `/user/unlink_steam` | `No matching request definition in fields.txt` | `No matching response definition in fields.txt` |
| `/web_session/token` | `google.protobuf.Empty` | `blend.api.WebSessionTokenResponse` |
| `/exploration/retire` | `blend.api.ExplorationRetireRequest` | `blend.api.ChangedResourcesResponse` |
| `/exploration/skip` | `blend.api.ExplorationSkipRequest` | `blend.api.ExplorationSkipResponse` |
| `/character/enhancement_reset` | `blend.api.CharacterEnhancementResetRequest` | `blend.api.CharacterEnhancementResetResponse` |
| `/character/level_limit_release` | `blend.api.CharacterLevelLimitReleaseRequest` | `blend.api.ChangedResourcesResponse` |
| `/character/bulk_set` | `blend.api.CharacterBulkSetRequest` | `blend.api.ChangedResourcesResponse` |
| `/character/equip` | `blend.api.CharacterEquipRequest` | `blend.api.ChangedResourcesResponse` |
| `/character/memoria_set` | `blend.api.CharacterMemoriaSetRequest` | `blend.api.ChangedResourcesResponse` |
| `/equipment_preset/equip` | `blend.api.EquipmentPresetEquipRequest` | `blend.api.ChangedResourcesResponse` |
| `/equipment_preset/memoria_set` | `blend.api.EquipmentPresetMemoriaSetRequest` | `blend.api.ChangedResourcesResponse` |
| `/ship/bulk_update` | `blend.api.ShipBulkUpdateRequest` | `blend.api.ChangedResourcesResponse` |
| `/ship/ship_tools_set` | `blend.api.ShipShipToolsSetRequest` | `blend.api.ChangedResourcesResponse` |
| `/character/skin_set` | `blend.api.CharacterSkinSetRequest` | `blend.api.ChangedResourcesResponse` |
| `/equipment_preset/update_name` | `blend.api.EquipmentPresetUpdateNameRequest` | `blend.api.ChangedResourcesResponse` |
| `/memoria/sell` | `blend.api.MemoriaSellRequest` | `blend.api.MemoriaSellResponse` |
| `/chara_home/register` | `blend.api.CharaHomeRegisterRequest` | `blend.api.ChangedResourcesResponse` |
| `/profile/update_chara_home_favorite_character_list` | `blend.api.ProfileUpdateCharaHomeFavoriteCharacterListRequest` | `blend.api.ChangedResourcesResponse` |
| `/profile/update_selected_home_id` | `blend.api.ProfileUpdateSelectedHomeIdRequest` | `blend.api.ChangedResourcesResponse` |
| `/profile/update_memo` | `blend.api.ProfileUpdateMemoRequest` | `blend.api.ChangedResourcesResponse` |
| `/profile/update_favorite_character` | `blend.api.ProfileUpdateFavoriteCharacterRequest` | `blend.api.ChangedResourcesResponse` |
| `/profile/update_favorite_party` | `blend.api.ProfileUpdateFavoritePartyRequest` | `blend.api.ChangedResourcesResponse` |
| `/profile/update_favorite_battle_tools` | `blend.api.ProfileUpdateFavoriteBattleToolsRequest` | `blend.api.ChangedResourcesResponse` |
| `/synthesis/execute_easy` | `blend.api.SynthesisExecuteEasyRequest` | `blend.api.SynthesisExecuteEasyResponse` |
| `/exploration/update_party` | `blend.api.ExplorationUpdatePartyRequest` | `blend.api.ChangedResourcesResponse` |
| `/master_data/*` | `CDN/asset request` | `CDN asset payload (not protobuf)` |
| `/manifest.json` | `JSON/asset request` | `JSON asset payload` |
| `/battle/resume` | `google.protobuf.Empty` | `blend.api.BattleResumeResponse` |
| `/quest/battle/total_battle_start` | `blend.api.QuestBattleTotalBattleStartRequest` | `blend.api.BattleStartResponse` |
| `/quest/battle/solo_raid_battle_start` | `blend.api.QuestBattleSoloRaidBattleStartRequest` | `blend.api.BattleStartResponse` |
| `/quest/battle/rental_party_start` | `blend.api.QuestBattleRentalPartyStartRequest` | `blend.api.BattleStartResponse` |
| `/gacha/battle_start` | `blend.api.GachaBattleStartRequest` | `blend.api.BattleStartResponse` |
| `/mail/delete` | `blend.api.MailDeleteRequest` | `blend.api.MailDeleteResponse` |
| `/mission/count_reward_receive` | `blend.api.MissionCountRewardReceiveRequest` | `blend.api.MissionCountRewardReceiveResponse` |
| `/daily_pass/bulk_receive` | `blend.api.DailyPassBulkReceiveRequest` | `blend.api.DailyPassBulkReceiveResponse` |
| `/mana/purchase` | `blend.api.ManaPurchaseRequest` | `blend.api.ChangedResourcesResponse` |
| `/shop/gem_list` | `No matching request definition in fields.txt` | `blend.api.ShopGemListResponse` |
| `/shop/random_shop/purchase` | `blend.api.ShopRandomShopPurchaseRequest` | `blend.api.ShopRandomShopPurchaseResponse` |

### Request/response definitions not assigned to a listed endpoint

These API messages are present in `fields.txt` but are not selected by the route mappings above. Some may be nested helpers, legacy/variant routes, or routes not yet observed; review them before adding endpoints.

- `blend.api.AdvertisingIdUpdateRequest`
- `blend.api.AuthSignUpAppleRequest`
- `blend.api.AuthSignUpAppleResponse`
- `blend.api.AuthSignUpGoogleRequest`
- `blend.api.AuthSignUpGoogleResponse`
- `blend.api.AuthSignUpPasscodeRequest`
- `blend.api.AuthSignUpPasscodeResponse`
- `blend.api.CharacterSkillEvolveRequest`
- `blend.api.CharacterSkillLockReleaseRequest`
- `blend.api.CharacterStoryClearRequest`
- `blend.api.CharacterStoryClearResponse`
- `blend.api.CommunicationStoryClearRequest`
- `blend.api.CommunicationStoryClearResponse`
- `blend.api.CommunicationStoryReleaseRequest`
- `blend.api.DailyPassReceiveRequest`
- `blend.api.DailyPassReceiveResponse`
- `blend.api.DebugCharacterEnhanceRequest`
- `blend.api.DebugExplorationFinishRequest`
- `blend.api.DebugKtidLinkRequest`
- `blend.api.DebugLoginBonusListResponse`
- `blend.api.DebugMailSendRequest`
- `blend.api.DebugShopPurchaseRequest`
- `blend.api.DebugShopStoreProductListResponse`
- `blend.api.DebugTitleListResponse`
- `blend.api.DebugTutorialStepUpdateRequest`
- `blend.api.DebugUserBulkResourceRequest`
- `blend.api.DebugUserLastMainStoryQuestRequest`
- `blend.api.DebugUserResourceRequest`
- `blend.api.EventDamageContestRequest`
- `blend.api.EventDamageContestResponse`
- `blend.api.EventLegendChallengeRequest`
- `blend.api.EventLegendChallengeResponse`
- `blend.api.EventReviveRequest`
- `blend.api.ExternalPurchaseReceiveResponse`
- `blend.api.GachaListRequest`
- `blend.api.GachaStepUpExecuteRequest`
- `blend.api.GachaStepUpExecuteResponse`
- `blend.api.GrowthPackPointPurchaseRequest`
- `blend.api.GrowthPackPurchaseRequest`
- `blend.api.GrowthPackReceiveRequest`
- `blend.api.GrowthPackReceiveResponse`
- `blend.api.HouseBuildingCountRewardReceiveRequest`
- `blend.api.HouseBuildingCountRewardReceiveResponse`
- `blend.api.HouseBuildingEnhanceRequest`
- `blend.api.HouseBuildingEnhanceResponse`
- `blend.api.HouseBuildingRentRequest`
- `blend.api.HouseBuildingRentalRewardReceiveRequest`
- `blend.api.HouseBuildingRentalRewardReceiveResponse`
- `blend.api.HouseBuildingResetRequest`
- `blend.api.HouseBuildingRewardReceiveRequest`
- `blend.api.HouseBuildingRewardReceiveResponse`
- `blend.api.HouseBuildingStartRequest`
- `blend.api.InvitationCreateRequest`
- `blend.api.InvitationCreateResponse`
- `blend.api.InvitationReceiveRequest`
- `blend.api.ItemBundleOpenRequest`
- `blend.api.ItemBundleOpenResponse`
- `blend.api.ItemChallengeExecuteRequest`
- `blend.api.ItemChallengeExecuteResponse`
- `blend.api.ItemChallengeRewardReceiveRequest`
- `blend.api.ItemChallengeRewardReceiveResponse`
- `blend.api.KtidWebTokenResponse`
- `blend.api.MissionEventTabRewardReceiveRequest`
- `blend.api.MissionEventTabRewardReceiveResponse`
- `blend.api.ModTimelineReleaseRequest`
- `blend.api.MultiMissionReceiveRequest`
- `blend.api.MultiMissionReceiveResponse`
- `blend.api.MultiMissionStatusRequest`
- `blend.api.MultiMissionStatusResponse`
- `blend.api.PresentExecuteRequest`
- `blend.api.PresentExecuteResponse`
- `blend.api.PurchaseSessionPublishRequest`
- `blend.api.PurchaseSessionStartRequest`
- `blend.api.PurchaseSessionStartResponse`
- `blend.api.PurchaseVerifyRequest`
- `blend.api.QuestClearedPartyListRequest`
- `blend.api.QuestClearedPartyListResponse`
- `blend.api.QuestScoreRankFirstRewardReceiveRequest`
- `blend.api.QuestScoreRankFirstRewardReceiveResponse`
- `blend.api.QuestStreetMoveRequest`
- `blend.api.RefundInfoGetRequest`
- `blend.api.RefundInfoGetResponse`
- `blend.api.RentalPartyBattleToolsSetRequest`
- `blend.api.RentalPartyBulkUpdateRequest`
- `blend.api.RentalPartyCharacterBulkEquipRequest`
- `blend.api.RentalPartyCharacterEquipRequest`
- `blend.api.ShipSynthesizeRequest`
- `blend.api.ShipSynthesizeResponse`
- `blend.api.ShopBoxGachaExecuteRequest`
- `blend.api.ShopBoxGachaExecuteResponse`
- `blend.api.ShopReceiveFirstPurchaseBonusResponse`
- `blend.api.ShopWheelRequest`
- `blend.api.ShopWheelResponse`
- `blend.api.SoloRaidResetRequest`
- `blend.api.SpecialOfferPurchaseRequest`
- `blend.api.SynthesisExecuteRequest`
- `blend.api.ToolTraitRankUpRequest`
- `blend.api.TotalBattleAchieveLineDramaRequest`
- `blend.api.TotalBattleResetPanelRequest`
- `blend.api.UserLinkAppleRequest`
- `blend.api.UserLinkGoogleRequest`
- `blend.api.UserLinksListResponse`
- `blend.api.UserUpdateBirthdateRequest`
- `blend.api.UserUpdateLanguageRequest`
<!-- END GENERATED PROTOBUF CONTRACT MAP -->
