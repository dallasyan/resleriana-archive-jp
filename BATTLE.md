# Battle Implementation Checklist

What the generated battle simulation (`battle_japanese.py` + `battle-master`
tables) models, what it estimates, and what it ignores. Confidence scale:

- **High** - verified against captures or master data.
- **Medium** - follows observed shapes with fitted or estimated constants.
- **Low** - placeholder logic or a guess; needs capture evidence.

## Entry and battle setup

- [x] Quest battle entry (`/quest/battle/start`) - **High** shape. Quest,
  wave, and enemy lookups from `battle-master`; a party-only `BattleStart`
  snapshot, full wave state, typed action setups, two timeline horizons, and
  captured task-count resource are returned. Empty BattleState field 19 and
  per-base-enemy groups are included as observed. Stamina is deducted. Live
  clients append extra varint fields (field 4 observed); the validator
  accepts them and the first field 1 wins as quest_id.
- [x] Opening enemy turns - **Medium**. Enemies ordered before the first ally
  act before player control is returned. If estimated opening damage would
  defeat the entire party, damage is capped to leave each target alive so the
  client still receives the captured enemy action and a player setup (**Low**
  damage accuracy).
- [x] Exploration battle entry (`/exploration/battle_start`) - **Medium**.
  Weighted encounter roll from `exploration_area` tables; otherwise identical
  to quest battles.
- [x] Gacha battle entry (`/gacha/battle_start`) - **Medium**. Fixed parties
  from `fixed_party` tables; first-clear rewards tracked in `gacha-state.json`.
- [x] Multi-wave battles - **Medium**. Wave transitions rebuild the order;
  only quests/areas present in the tables can start.
- [x] Countdown (turn-limit) battles - **Medium**. Loss is forced past the
  limit; exact server timing is unverified.
- [x] Retire / resume - **High** shape, **Medium** behavior. Retire clears
  state with an empty response; resume echoes the active battle or 503s.
- [ ] Total-battle / solo-raid / rental-party starts - **Missing** (503).

## Stats and skills

- [x] Ally battle identity - **High**. `current_character_id` mirrors the
  profile character ID unless a character-change effect is active.
- [x] Ally base stats - **High**. Level from EXP thresholds, growth
  coefficients, rarity coefficients, and stored growboard stats/rate come
  from profile + master data, including the character master's base speed.
- [x] Equipment status and slot links - **Medium**. Equipped profile records,
  flat/rate status buffs, and ranked trait ability effects are applied.
- [x] Personal Memoria status growth and abilities - **Medium**.
  Level/limit-break growth, status buffs, and unlocked ability IDs come from
  profile + Memoria masters; exact battle formulas remain approximate.
- [x] Atelier Research levels - **Medium**. Profile research groups apply
  role-scoped stat bonuses from the derived combat map; equipment research
  rows stay unmapped.
- [x] Emblems - **Medium**. Owned profile emblems apply rarity-scaled stat
  bonuses and parsed conditional combat mods from the derived combat map.
- [x] Subspace Support characters/Memoria - **Low**. Profile support roster
  stats and selected subspace Memoria contribute estimated status bonuses
  using ship-level support rate.
- [x] Atelier Cannon availability and firing - **High** request/response
  shape. Selected ship tools emit cannon slot, skill ID, and uses in
  `BattleState` field 21. Japanese cannon attacks use mode 9 with a repeated
  field 10 slot command; the response uses action type 3 and field 31 for the
  selected slot. A firing consumes one use and leaves the acting character's
  timeline turn available.
- [x] Leader aura - **Medium**. The leader skill's ability effects apply to
  party members matching its tag/role/attribute/series conditions; the
  leader position/flag is still recorded.
- [x] Character passives - **Medium**. All ability descriptions parse into
  battle-long mods (positional placeholder values) and event triggers
  (battle/skill/panel/item/weak/ko/crit/break starts and hits) with
  conditions, scopes, use caps, and OR-branching; unmapped IDs stay
  neutral and unlisted in responses.
- [x] Skill ranks and evolution - **High**. Profile ranks pick normal1/normal2
  rows; evolve flags switch to evolved tables.
- [x] Burst skill selection - **High**. Rarity-indexed into the burst table
  (rarity-1, capped); Season2 captures confirm rarity 7 uses the last entry.
- [x] Skill lamp - **Medium**. BattleMember skills carry `lamp` from the
  skill master when `max_lamp > 0` (Season2 captures show lamp 3 at start).
  Lit counts track battle-start and event lighting (capped, rank-variant
  resolved) with per-lamp damage tiers, lamp-scaled pre-attack buffs, and
  full-lamp transform flags. Transformed numeric deltas stay unmapped.
- [x] Burst gauge and ship Memoria on members - **Medium** shape. Every
  member carries `burst_gauge` with current gauge and `max_gauge` 100;
  allies also carry `ship_main_memoria` (support Memoria id, top unlocked
  ability, computed level, limit break) resolved from the selected ship
  party. The support value coefficient (augmented by supporting Memoria,
  e.g. 4400/2600 observed) and the one-off enabled 300 gauge in an older
  session are not modeled. `ship_support_ability` and bomb gauge never
  appear in captures and are omitted, as are state-change summaries
  (field 24), whose per-type aggregation formula is still open (entries
  demonstrably track live buffs/debuffs, including negative values).
  Barriers emit fields 21/22 with absorb and broken flags.
- [x] Unknown characters - **Medium**. Work if their character/skill master
  rows exist (stats + generic damage math). Missing rows degrade to zero
  stats/skills, which is not a usable fallback.
- [x] Active skills - **Medium** shape. Skill ids come from the character
  master `activeN_skill_id` slots (e.g. Totori 26904 active1 14002908) with
  rest counts from skill-master limits. Members emit field 7
  {id, type, rest}; setups offer field 15 selections {type, targets, id};
  mode-7 requests with field 8 {type, target, rest} resolve as free actions
  (no timeline advance, no enemy turns) and the action carries field 28.
  Exhausted skills stop being emitted. Rest-gated availability text and any
  gauge interaction remain unverified.

## Damage, affinity, crits

- [x] Physical affinities (Slash 1, Strike 2, Stab 3) on attack/defense -
  **High** for Slash; **Low** for Strike/Stab element mapping (game
  knowledge, no capture samples).
- [x] Magic affinities (Wind 4, Fire 5, Ice 6, Bolt 7) on magic/mental -
  **High** for Fire/Bolt; **Low** for Wind/Ice mapping.
- [x] Community damage formula - **Medium**. `112/9 * attack * (level+9) *
  skill% / defense` with multiplicative slots (skill damage, skill power,
  outgoing, taken, resistance, penetration, break, crit, random 1.00-1.01).
  Same-category bonuses add; taken-down debuffs multiply separately.
  Penetration uses `(10x+3000)/(3x+3000)` with per-reduction scaling.
- [x] Weakness (-25%) / resistance (+25%) thresholds - **Medium**. Resistance
  slot is `(100 - res)/100` with -50 on break; weakest-link element wins.
- [x] Criticals (10% ally, 0% enemy/item base, x1.5 plus bonuses, panel 30
  forces) - **Medium**. Crits never affect break damage; frozen targets are
  always crit.
- [x] Healing (power * stat / 100 * 0.45 with given/received recovery
  bonuses) - **Low**. Shape verified, scale estimated.
- [x] Break damage formula - **Medium**. `125 * (1 - 100/(atk+100)) *
  break% * break-up * break-power * resistance * random`; ignores skill
  panels and crits; break-up bonuses add, break-power multiplies.
- [x] Buff display gating - **High** shape. Only effects present in the
  state-change master reach member buff icons; anything else (tool/cannon
  effect ids, lamp/gauge effects, unmapped traits) keeps combat multipliers
  where understood but stays hidden. The client resolves buff icons by
  state id and softlocks on unknown ids (seen live as a `StateChangeIcon`
  NRE, e.g. enemy self-buff `20000655`). Effect results are still emitted
  for every effect as in captures.
- [x] Previews in action setups - **Medium**. Single-target previews list
  every living candidate (captured 204101001 shows all 3 foes per skill).
  Multi-candidate damage previews mark every target `is_killed`/`is_critical`
  and carry critical rate `110.0`; single-candidate starts carry the rate but
  omit the marks. Buff/state previews carry only the target id (captured
  Rorona 12002902 shows no damage fields); buff previews for skills with
  wait also carry one timeline move (captured Totori active 14002902,
  wait -200). Damage, break, critical-damage,
  and estimated wait-move previews are emitted; per-target timeline shifts
  and panel overwrites are missing.
- [x] Damage result presentation - **Medium** shape. Damage results include
  barrier damage / broken flags, miss / invalid flags, field 18
  critical-damage values, field 19 rate, and the ally bomb-gauge effect
  result used by skill actions. Cover redirection emits `protector_id`;
  skipped (ailment-failed) actions emit `is_skipped`. Damage math and
  passive-generated effect results remain approximate.
- [x] Status conditions - **Medium**. Poison/burn/venom ticks, regen ticks,
  paralysis fail chance, sleep/stun turn loss, darkness miss chance, frozen
  crits, taunt targeting, evade rolls, barrier absorb, null-damage
  thresholds, cover redirection, and cleanse run from the derived combat map
  (`battle-master/combat_map.json`). Application rates are estimated;
  counter retaliation and reflect damage stay display-only.
- [x] Buff potency - **Medium**. Granted amounts scale with giver
  given-plus/minus and receiver received potency; caps and fixed flags are
  honored where parsed; permanent raid-style debuffs never expire.

## Timeline, panels, gauge, break

- [x] Initial order by wait time - **Medium**. `floor(57600/speed) +
  skill-2 wait`, ties left to right; enemies use zero master wait.
  User captures show opening enemy actions before control passes to an ally.
- [x] Post-action repositioning by wait time - **Medium**. Steps derive from
  the same wait value; wrapped fields 4/5/6 carry from/to indexes and wait.
  Delay/hasten effects and turn swap/erase shift the order directly.
- [x] Incremental attack histories - **High** shape. Attack responses carry
  only new wave starts, setups, and actions (plus the ever-present start
  snapshot and previous state); resending full history makes the client
  replay stale turns in a loop. Setup/action numbers stay in lockstep
  (setup N precedes action N; the next turn's setup rides along).
- [x] Per-action enemy setups - **High** shape. Every enemy action is
  preceded by its own setup in the same response; free tool/cannon actions
  carry no setup and advance neither order nor enemies. Terminal (winning)
  actions carry no following setup, so the client proceeds to finish.
- [x] Timeline-order enemy turns - **Low**. Enemies act in head-of-timeline
  order between player turns (not ID order); initial order, speeds, and
  wait slots remain estimated.
- [x] Panel schedule and effects - **Medium**. The master battle row lists
  panel ids in turn order and captures match per-battle fixed schedules, so
  turns cycle that list (hash fallback only when empty). Panels 12/13 feed
  the skill-damage slot (1.4/0.6); panel 30 forces crits; panels 14/17 gate
  burst use. Acquisition applies exact parsed effects (break/heal/taken/
  crit/ailment/stat/panel ops with durations and caps) to the holder side.
  Skill panel overwrites are missing.
- [x] Burst gauge - **Medium**. Per-ally 0-100 gauge (skill 1 +10, skill 2
  +20, panel/no-post-action skills excluded, burst use consumes 100);
  members emit current/max. The shared party gauge is now the item gauge
  only (500 start, +100 per ally action, reset on tool use).
- [x] Break gauges - **Medium**. Max estimated from HP; community break
  formula; breaking resets the gauge and grants x2 damage with -50
  all-resistance. Multi-gauge enemies and minor/full break distinction apply.
- [x] Ally/enemy deaths - **Medium** shape. HP 0 clears the alive flag, sets
  `killed` in results, and removes the member from timeline/order/setups;
  Ayesha capture confirms the shape. Damage math remains approximate.
- [x] Stun handling - **Medium**. Stun costs one turn, then clears; break
  delays via repositioning instead of a permanent flag.
- [x] Enemy telegraph fields (`enemy_skill_type`, `is_enemy_strong`) -
  **Low**. Emitted cosmetically; always cleared after use.

## Enemies, tools, auto

- [x] Enemy stats/resistances/AI skill lists - **Medium**. Master data with
  estimated linear growth (clamped) and mild speed scaling.
- [x] Enemy targeting - **Medium**. Defender-biased choice with taunt
  override and fixed-condition targeting; targeted/random actions ignore
  aggro; support skills self-heal; enemy action `main_target_id` mirrors
  its first resolved target.
- [x] Enemy bursts - **Low**. Every 5th action when a burst skill exists.
- [x] Battle tools - **Medium** shape, **Low** damage. Profile-equipped tools,
  master usage counts, traits, and skill-based use are emitted. Tool commands
  can batch several tool numbers; each produces its own free-action result,
  without moving the acting member or triggering enemy turns. Selections are
  offered when the item gauge is full; using tools empties that gauge. Parsed
  trait effects apply by item category; unmapped traits stay neutral.
- [x] Item mix - **Medium** shape, **Low** values. Request field 9 mix
  commands resolve via the mix attribute table with the mixer-only stats,
  carried source traits, and superior forms at slot >= 600. Mix field
  effects stay unmodeled.
- [x] Equipment/memoria/character traits and abilities - **Medium**. Ranked
  traits and unlocked abilities map through the derived combat map into
  battle-long stat mods and combat slots; research, emblems, and leader
  skills apply from profile records; unmapped IDs stay neutral and listed.
- [x] Auto battle - **Medium**. Burst when the member gauge allows, otherwise
  normal2 every third request, else normal1.

## Rewards and persistence

- [x] Score and rank - **Low**. Component weights fitted to one finish, but
  score battles show different component bases per quest/party whose source
  is unidentified; rank thresholds come from master data.
- [x] Rank reward sets, drop rolls, first-clear rewards - **Medium**.
  Structures verified; rank-set items carry captured `is_bonus`/`bonus_rate`
  flags, quantities stay at master values.
- [x] Finish response shapes - **High**. Quest results omit empty
  mission results; quest states carry the run's score detail and only
  persist improved min turns; Status/character updates echo stored records
  with only changed scalars replaced, so rank/exp and growboard fields
  survive (a minimal Status broke post-battle rank recomputation).
- [x] Character EXP, Cole, items, quest states, stamina deduction -
  **High** mechanism. Missions are all auto-cleared (**Low** accuracy).
  Character EXP gains stop at the level-cap threshold and already-capped
  characters are omitted entirely, matching captures (uncapped gains grew
  without bound); over-cap values clamp back down on the next finish.
- [ ] Task-count updates, episode states, mission progress, level-ups -
  **Missing**.
- [x] Battle skip - **Medium** shape; **Low** values (fixed 6 pieces per
  member and 2400 Cole per clear from a single sample, plus drop rolls).
- [ ] Stamina gating - **Missing** by design. Stamina floors at zero and
  battles remain enterable.

## Verification status

- Automated: `test_replay_battle.py` covers start snapshots/resources, enemy
  groups/target references, selectable-skill previews, damage-result fields and
  skill motion, profile equipment/Memoria, cannon firing, multi-tool commands,
  item-mix command shape and skill lookup, active-skill member/setup/action
  flow with rest exhaustion, buff-preview timeline moves, community damage
  and break formulas, panel/state combat-map entries, poison ticks, taunt
  and cover targeting, burst-gauge accrual and gating, turn-swap ordering,
  ship support, opening-damage capping, a full win loop, retire/resume/skip,
  loss path, and a multi-quest/area no-crash sweep. It does not cover every
  master entry.
- In-game verification across quest types is still pending. Derived combat
  data comes from `build_combat_map.py` over community master data; the raw
  database stays outside the share package.
