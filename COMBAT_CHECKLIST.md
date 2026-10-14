> Share copy (sanitized per AGENTS.md): local capture session paths, user directories, and profile references removed. Route names, counts, and master IDs retained. Regenerate from workspace originals.

# Combat modifier checklist (working reference)

This checklist tracks every combat action and modifier for the full-combat
implementation. Each entry has a description, the implementation approach,
and where to look for more evidence. Local capture paths are analysis
pointers only; never copy private session or profile data into shared files.

Source precedence on conflicts: linked websites beat `BATTLE_DETAILS.md`.
Canonical workspace mechanics reference: `COMBAT_IMPLEMENTATION.md`.
Simulator: `tools/JapaneseOffline/battle_japanese.py`.
Derived data: `tools/JapaneseOffline/build_combat_map.py` plus
`battle-master/combat_map.json` (built from
`resleriana-db-main/data/master/jp`, ASCII-coded, no private data).
Contract oracle: `installed contract-dump/fields.txt`.

## How to read implementation status

- Done: implemented in `battle_japanese.py` with regression tests.
- Partial: structure exists, some branches estimated or unmapped.
- Missing: not implemented yet; the entry says what to do.

## Ally skills

- [x] Skill 1 / Skill 2 normal actions (Done)
  - Description: basic attacks, heals, and buff/state skills with master wait.
  - Implement: resolve via `battle-master/skill.json`; community damage, break,
    heal, and status rules; relative-wait timeline move using the speed-adjusted
    master wait; burst/item gauges.
  - Data: `battle/attack` in `local battle captures`; three-character
    attacks in `local battle captures`.
- [x] Extra skills (Done)
  - Description: replace skill 2 on extra turns where defined.
  - Implement: `extra_skill_for_character` picks rank-indexed or
    normal2-prefix-matched entries; skill summaries granting extra turns
    (`extra_turn_grant`: unconditional, on-crit, named-state presence) set
    the flag in `do_action`; `advance_round` moves the actor to the head
    and offers its setup with the extra skill in the skill-2 slot; the next
    skill-2 command resolves the extra id. Capped at 5 per battle; state
    level gates are presence checks; extra-action gauge policy is estimated.
  - Data: 25 characters with `extra_skill_ids`; 32 granting skills;
    resleriana-db skill summaries and state names; combat cases under
    `local battle captures`.
- [x] Panel skills (Done)
  - Description: fire on panel acquisition; no status-count use or post-action
    effects; excluded from burst gauge gain.
  - Implement: hyperlink skills resolve free with `post_hooks=False` on
    parsed panel triggers (plus/burst/minus categories, use caps, target
    tags); emitted as setup-less actions.
  - Data: ability descriptions with panel-skill hyperlinks; `hyperlink.json`.
- [ ] Active abilities (Partial)
  - Description: limited-use skills with rest counts.
  - Implement: `activeN_skill_id` plus skill-master limits; member field 7,
    setup field 15, mode-7 field 8, action field 28. Most are free actions;
    captured Totori timeline-swap active emits timeline moves and advances
    other waits, which the simulator does not yet reproduce. All 10 active
    slots on non-sentinel released characters have generated action tests;
    captures directly cover 5/10 slots.
  - Data: active-skill master rows and local combat captures; active skill 14002908.
- [x] Additional attacks (Done)
  - Description: conditional follow-up after a triggering skill.
  - Implement: hyperlink skills resolve free with `post_hooks=False` on
    weak/crit/ko/break/skill-id triggers with use caps; 200%+ burst
    overdrive consumes 100 gauge. No timeline advance.
  - Data: ability descriptions with additional-attack hyperlinks;
    combat cases under `local battle captures`.
- [x] Skill ranks and evolution (Done)
  - Description: profile ranks pick normal1/normal2 rows; flags 31/32/33
    independently select evolved normal1/normal2/burst tables.
  - Implement: matching profile records feed combat skill selection; the
    all-skills-evolved ability subset is gated on rarity 8 and all three flags.
    Resna Innocent Dreamer's Skill 1 resolves the evolved rank's power/break,
    all-ally healing, capped Magic ATK, and item-gauge behavior; its +50%
    critical-damage passive merges to 250% and is only registered after all
    three flags.
  - Data: `progression-master/character.json`; 45 local evolution operations
    across 15 characters; skill masters and ability 1990325.
- [x] Skill lamps (Done)
  - Description: conditional lamp counts enhance skills at maximum.
  - Implement: battle-start and event lighting (skill/item/heal/panel/
    attacked/weak/ailment triggers, use caps, rank-variant resolution,
    max capping); per-lamp damage tiers and lamp-scaled pre-attack buffs;
    full-lamp Skill 2 return to base form for the captured Resna/Valeria
    changes, using the base rank-matched Skill 2 before the hit.
  - Data: 15 lamp abilities; `battle-master/skill.json lamp` maxima.
- [x] Penetration (Done, hooks)
  - Description: ignores part of defense and damage-taken reduction.
  - Implement: `(10x+3000)/(3x+3000)` and per-reduction
    `(x+2000)/(10x+2000)`; sources default to 0 until mapped.
  - Data: `https://atelier.xxsakixx.com/resleri/damage.html`.
- [x] Transformation (Partial, capture-backed return)
  - Description: two-lamp Skill 2 returns captured Awakened Resna/Valeria to
    their base character forms before attacking.
  - Implement: full-lamp setup/action selects the base rank-matched skill,
    restores the base current-character ID, and clears the temporary form.
    Character-sourced passive mods/triggers are replaced from the destination
    form's master on return. Captured transformed battle starts use the current
    form's ability IDs. Base-to-awakened entry remains open.
  - Data: Resna 43106/43107 and Valeria 43205/43206 skill/master captures.
- [x] Range switching (Done)
  - Description: in-range/out-range toggle changes usable skills.
  - Implement: bidirectional `skill_destination` links; out-range members
    offer/resolve the destination skill 1; post-attack range moves with
    display state buffs; starting-range swap abilities.
  - Data: 120 range skills; range states in `combat_map.json`.
- [ ] Timeline erase/swap skills (Partial)
  - Description: target type 6 skills erase or swap timeline turns.
  - Implement: `turn_swap`/`turn_erase` effect tags resolve in
    `apply_parsed_skill_effect` and post-attack behaviors; swap validates
    the front-five range; erase marks one skip in rebuilds. Active swap moves,
    wait rebasing, and extra scheduled actor events remain incomplete.
  - Data: skills 14003047/14003939; active skill 14002908 capture.

## Burst

- [x] Burst availability and rarity selection (Done)
  - Description: rarity-indexed burst id; gauge/panel/stock gating.
  - Implement: rarity-1 capped selection; per-ally 0-100 gauge; omit burst
    selection unless usable.
  - Data: `local skill captures`; rarity 7 last-entry evidence.
- [x] Burst gauge gain and use (Done)
  - Description: skill 1 +10, skill 2 +20; panel/no-post-action excluded;
    use consumes 100.
  - Implement: per-member gauge split from the shared item gauge.
  - Data: battle system guide; `battle/attack` captures.
- [x] Per-character burst stocks (Done)
  - Description: maximum burst stocks vary per character.
  - Implement: `burst_stocks` parsed from stock abilities; per-member gauge
    caps and gating use the stocked maximum; display max stays 100.
  - Data: stock ability descriptions (N周分ストック可能).

## Passive abilities

- [ ] Character passives (Partial)
  - Description: always-on behavior without grant text.
  - Implement: all 7,131 ability rows are emitted in `ability_parsed`; released
    characters link 432 distinct ability IDs, of which 374 currently have
    nonempty parsed mods/triggers. Parsed party tag-count and owner-speed ranges
    resolve dynamically; party-scoped stat passives fan out at battle start.
    Fifty-eight released linked IDs still have no parsed behavior.
  - Data: `character.json ability_ids`; `ability_parsed` map and parser tests.
- [x] Board abilities (Done)
  - Description: growboard-derived passives.
  - Implement: same parsed-ability pipeline as character passives.
  - Data: `character.json board_ability*_ids`; growboard tables.
- [ ] Support abilities (Partial)
  - Description: ship/party support abilities scale with rarity/level.
  - Implement: pooled support stats exist; map support ability value/coef
    fields from capture ship blobs into combat bonuses.
  - Data: ship support captures; `ship_level.json`, `ship_part.json`.
- [ ] Ability conditions and caps (Partial)
  - Description: conditional triggers, stacks, hard upper limits.
  - Implement: capped trigger buffs merge into one value and obey the parsed
    limit; `stack_max` state effects retain separate entries up to their stack
    count. An absent value and stack cap keeps repeated entries separate.
    Japanese `N回行動開始/終了するまで` wording selects owner-turn start/end;
    `N回攻撃を受けるまで` uses a hit counter, serialized as remaining
    `rest_count`. Evasion and nullified attacks consume hit-limited effects.
    Capped no-duration effects persist; stack-overflow semantics and other
    effect families still need auditing.
  - Data: Resna ability 1990325 (50% critical damage, cap 250%); Liebe states
    610465/610466 (two separate defense stacks); state 610119's 50% cap;
    duration and uncapped-entry regressions.

## Leader aura

- [x] Leader skill (Done)
  - Description: global party buff from the leader slot.
  - Implement: read leader `leader_skill`; parsed ability mods filtered by
    tag, role, attribute, and series conditions per member; leader trigger
    registration with scope-aware firing. Valeria Awakened Past's Carefree
    condition (tag 25) grants Pioneer only to matching members; initial order
    places a low-speed Pioneer before faster non-Pioneers.
  - Data: `character.json leader_skill`; leader-condition and Pioneer tests.
- [ ] Leader position and role aggro (Partial)
  - Description: formation order and Defender bias affect targeting.
  - Implement: leader flag kept; add Defender-biased enemy targeting unless
    targeted/random actions ignore it.
  - Data: battle hints; enemy AI/targeting captures.

## Equipment stats and effects

- [x] Equipment flat/percentage stats (Done)
  - Description: flat and rate-based HP/speed/attack/defense/magic/mental.
  - Implement: existing equipment status-buff pipeline, flat before percent.
  - Data: `equipment_tool.json`; profile equipment records.
- [ ] Equipment abilities/effects (Partial)
  - Description: non-stat combat behavior from equipment.
  - Implement: collect `ability_ids`; route through `combat_map.json`
    ability-effect codes; keep unmapped IDs neutral and listed.
  - Data: equipment rows; status/battle captures.

## Equipment traits

- [x] Equipment trait ranks (Done, mapping partial)
  - Description: ranked traits modify combat through abilities/effects.
  - Implement: existing rank selection; map `equipment_tool_trait.json`
    ability effects via `combat_map.json`; honor filters/duplicates.
  - Data: `equipment_tool_trait.json`; profile trait rank records.
- [ ] Fixed trait effects (Missing)
  - Description: fixed-percentage effects ignore potency modifiers.
  - Implement: honor the parsed `fixed` flag in `combat_map.json`.
  - Data: trait/effect text; community trait hierarchy.

## Memoria stats and effects

- [x] Memoria level/limit-break stats (Done)
  - Description: growth and limit-break stat increases.
  - Implement: existing Memoria level/growth pipeline.
  - Data: `memoria*.json`; profile Memoria records.
- [ ] Memoria abilities (Partial)
  - Description: combat abilities unlocked by limit breaks/roles.
  - Implement: unlocked list exists; route effects via `combat_map.json`.
  - Data: `memoria.json ability_ids`.
- [ ] Memoria roles/attributes (Missing)
  - Description: role/attribute matching affects support and bonuses.
  - Implement: use roles/attributes in support matching and conditionals.
  - Data: Memoria rows; ship support formations.

## Battle items

- [ ] Item slots, uses, gauge (Partial)
  - Description: 3 normal / 5 dungeon tools; 50 start, +10 per ally action,
    usable at 100, reset on use.
  - Implement: profile/master tool resolution and use tracking; battle-kind
    capacity is not enforced yet.
  - Data: `party/battle_tools_set`; `battle_tool.json`.
- [x] Fixed item targeting (Done)
  - Description: fixed conditions override taunt; ties go to nearest turn.
  - Implement: lowest-HP ally, highest-HP enemy, highest-stat ally, plus
    timeline tie-breaks.
  - Data: item captures in `local battle captures`.
- [x] Item damage and healing (Done)
  - Description: party-average stats; base 0 crit; fixed/percentage healing.
  - Implement: pooled actor stats; item-only crit hooks; healing rules.
  - Data: attack/enhance/weaken/recovery items.
- [ ] Item mix (Partial)
  - Description: two attack items combine into a mixed skill.
  - Implement: accept request field 9 (`BattleBattleToolMixCommand`);
    `combat_map.json` mix table maps attribute pairs to skills; superior
    forms at slot value >= 600; source-item traits carry over.
  - Data: item-mix wiki page; dungeon/item captures.

## Battle item traits

- [ ] Battle-item trait effects (Partial)
  - Description: item-specific damage/healing/buff/crit/gauge traits.
  - Implement: map `battle_tool_trait.json` effects via `combat_map.json`;
    gate by item/effect category so healing traits never boost damage.
  - Data: `battle_tool_trait.json`; battle tool blobs with trait ranks.

## Atelier cannons

- [x] Cannon slots, levels, skills, uses (Done)
  - Description: ship cannon tools scale by tool level/EXP.
  - Implement: existing ship-party/tool-level resolution.
  - Data: `ship_tool.json`, `ship_tool_level.json`; cannon captures.
- [x] Cannon gauge and turn cost (Done, boost estimated)
  - Description: cannon gauge fills per ally action; firing costs a turn.
  - Implement: `cannon_gauge` starts at 0, gains a base 10 plus ship
    cannon-boost triggers per ally skill use (ship-level abilities such as
    7000852/7000859 parsed as `cannon_gauge` triggers), fires one cannon at
    100 and resets. No wire field carries it in captures, so it is tracked
    silently. Free-action accrual scope is an estimate.
  - Data: cannon captures in `local battle captures`; cannon reference page.
- [x] Cannon-only bonuses (Done, formulas estimated)
  - Description: only cannon damage/crit bonuses apply, never item bonuses.
  - Implement: pooled-mod filtering has separate cannon damage/crit slots from
    the item slots; exact bonus stacking still needs capture calibration.
  - Data: Atelier cannon reference page.

## Subspace memoria

- [x] Main support Memoria blob (Done)
  - Description: support Memoria id, top ability, level, limit break on allies.
  - Implement: existing field 27 emission; add combat bonus application.
  - Data: ship `support_ability*`/`main_memoria_*` capture fields.
- [ ] Sub Memoria caps and matching (Missing)
  - Description: up to three sub Memoria raise caps by limit/attribute/role.
  - Implement: cap-aware support calculation.
  - Data: subspace support reference page.
- [ ] Support scaling formula (Missing)
  - Description: exact client-side scaling is still open.
  - Implement: calibrate against Memoria selection previews and capture
    coefficients.
  - Data: `BATTLE_DETAILS.md`; ship support captures.

## Subspace support

- [x] Support roster stats (Done, approximate)
  - Description: pooled support-character and Memoria stats.
  - Implement: existing pooled support pipeline.
  - Data: ship-party profile records.
- [x] Character support abilities (Done, caps estimated)
  - Description: support characters auto-fire gated abilities in battle.
  - Implement: ladder index rarity-1 (maximum assumed without a record);
    snapshot battles use start-message ability ids and coefs, generated
    battles scale by the ship-level apply rate. Passive stat effects apply
    at build (snapshot stats already final); slot effects ride member mods;
    pre-attack debuffs, reactive heals, and cannon-gauge accrual fire
    through member triggers with per-ally use caps.
  - Data: character `support_ability_ids`; start `ship.support_ability_ids`
    and `support_ability_value_coef`.
- [x] Main-memoria party spillover (Done, snapshot only)
  - Description: main-memoria abilities reach the party at message coef.
  - Implement: start-message ability ids scale party mods; generated coef
    needs the unverified sub-memoria bonus formula.
  - Data: start `ship.main_memoria_ability_ids` and `main_memoria_value_coef`.
- [ ] Support level/cannon frame bonuses (Partial)
  - Description: support level affects multipliers, cannon gauge, frames.
  - Implement: `support_ability_apply_rate` scales support values; ship
    cannon-boost abilities parsed as `cannon_gauge` triggers. Cannon frames
    stay unmodeled.
  - Data: `ship_level.json`.

## Atelier research level

- [x] Battle/alchemy research (Done, equipment/nurturing deferred)
  - Description: HP/dealt-damage/resistance plus item damage/heal slots.
  - Implement: profile field 30 levels select the latest unlocked tier per
    effect (verified Lv200 totals: attacker HP 2500, dealt 2020, defender
    resist 1500); HP folds into base stats at build (max-HP parity on all
    five Score 33-1 allies), damage/resistance/item slots ride silent
    battle-long mods; research is never potency-boosted. Equipment-stat and
    item-potency rows plus nurturing floor levels stay out (applicability
    unverified, moot at level cap).
  - Data: research reference pages; `research*.json` masters.

## Subspace ship level

- [x] Ship level and capacity (Done)
  - Description: ship EXP/level lookup and capacity enforcement.
  - Implement: existing ship level resolution.
  - Data: `ship_level.json`.
- [ ] Ship parts and enhancement (Missing)
  - Description: parts enhance targets by type/value.
  - Implement: map `ship_part.json` enhance targets into combat/stats.
  - Data: `ship_part.json`; ship upgrade captures.

## Timeline panels and adjustments

- [x] Fixed panel schedules (Done)
  - Description: per-battle panel schedules fixed per battle, same every run.
  - Implement: `battle-master/panel_schedules.json` carries majority-vote
    schedules from 879 starts and 10646 captured attacks (80 battles);
    turns past the captured range (and battles without data) use a
    deterministic hash draw from the battle row's available panel list
    weighted by the measured distribution (empty dominant, then
    14/12/13/30/42/15/17). Panel 11 is the empty display id and never
    emits. Showcase training battles show per-instance variance, so
    generated tails can diverge from any single attempt by construction.
  - Data: `battle.json` available lists; captured setup forecast windows.
- [ ] Panel categories and effects (Partial)
  - Description: burst/plus/negative/recovery/empty panels with exact values.
  - Implement: `combat_map.json` panels carry parsed ops; apply acquisition
    buffs for holder side, enemy-side variants, durations, and caps.
  - Data: effect-panel reference pages; panel descriptions in masters.
- [ ] Panel generation/conversion/enhancement (Missing)
  - Description: skills/abilities create, change, or upgrade panels.
  - Implement: panel-state mutation hooks plus `overwritten_timeline_panels`
    emission (contract fields 10/19).
  - Data: panel-manipulation captures and skill effects.
- [ ] Timeline advance/delay (Partial)
  - Description: relative wait values move units on the timeline; turn delay
    and hasten effects modify those waits.
  - Implement: field 6 carries remaining Int32 wait, current event is 0, and
    every advance subtracts the minimum pending wait. Initial and requeue waits
    use `floor(57600 / Speed) + master_skill.wait`; timeline delay/hasten still
    uses estimated slot-step gaps. Free actions skip moves.
  - Data: setups/actions with `timeline_moves`.
- [x] Consecutive actions (Done)
  - Description: speed/weight manipulation enables back-to-back turns.
  - Implement: relative wait math and speed-adjusted requeueing produce
    consecutive turns where scheduled; ally-turn rotation has regression tests.
  - Data: timeline captures; wait formula page.

## Emblems

- [ ] Owned emblem stats and conditionals (Missing)
  - Description: permanent stat and conditional bonuses.
  - Implement: load profile field 19 emblems; map `combat_map.json`
    emblem tables into stats/damage/break/panel hooks.
  - Data: emblem reference page; `emblem*.json` masters.

## Growboards

- [x] Growboard stats and rates (Done)
  - Description: stored board stats and all-rates feed battle stats.
  - Implement: existing profile fields 19-24 plus all-rate pipeline.
  - Data: profile character records; growboard tables.
- [ ] Neo/exclusive board behavior (Missing)
  - Description: special boards may carry battle-relevant exceptions.
  - Implement: board-specific rules without potency boosts where prohibited.
  - Data: growboard/progression evidence.

## Status conditions

- [ ] Positive/negative buffs (Partial, slot-mapped)
  - Description: stat up/down, damage dealt/taken modifiers, typed resistance,
    and conditional state effects with durations.
  - Implement: parsed state descriptions map known slots; relative stat/damage
    modifiers and separate taken-down multipliers apply. Unknown state rows are
    inert instead of defaulting to generic outgoing/taken damage. Explicit
    action-start/end durations tick on the owner's action; hit-count durations
    tick when an attack reaches its target. Generic stacking caps, several
    trigger families, and some status categories remain incomplete.
  - Data: Japanese `skill.json` / `state_change.json` duration text; regression
    tests for start/end, hit limits, evades, and nullification.
- [x] Ailments (Done, rates estimated)
  - Description: poison, burn, paralysis, sleep, frozen, darkness, stun, taunt.
  - Implement: `combat_map.json` state tags drive ticks, action-fail rolls,
    targeting overrides, crit interactions, and cures; application rates
    parsed where present, resisted by resist-up states.
  - Data: `status` burn/paralysis/sleep cases; state-change reference page.
- [ ] Neutral/special states (Partial)
  - Description: regen, barrier, evade, counter, reflect, cover, null damage,
    panel-null, range states, dummies/counters.
  - Implement: regen ticks, barrier absorb, evade rolls, null-damage
    thresholds, cover redirection with `protector_id`, and reflect damage.
    Counter damage remains records-only; reflect amount/type details are
    estimated.
  - Data: state-change reference page; contract barrier/protector fields.
- [ ] Immunity, cleanse, block (Partial)
  - Description: prevention and removal mechanics.
  - Implement: ailment immunity/resistance and explicit cleanse/dispel paths;
    turn-start cleanse states are modeled. Capture-mined skill removal
    effects run before grants (`skill_effect_map.json`; intrinsic skill
    effects only, before_skill entries serialize to field 20) and boss aura
    810224 blocks every cross-side state grant silently. General
    positive-effect blocking and resistance emission (contract field 18)
    are incomplete.
  - Data: status captures; skill removed_state_changes mining.
- [x] Permanent debuffs (Done)
  - Description: raid-style persistent stacks with caps.
  - Implement: no-expiry stacks with caps from parsed data.
  - Data: permanent-debuff listings.

## Enemy attacks

- [x] Enemy stats and scaling (Done, estimated growth)
  - Description: quest-specific status, growth, resistance, break gauges.
  - Implement: `enemy.json` status/growth/resistance; linear level scaling.
  - Data: `enemy.json`; quest/wave tables.
- [x] Enemy AI cycles and bursts (Done)
  - Description: AI skill lists, cursor behavior, periodic bursts.
  - Implement: existing AI-cycle resolution and burst cadence.
  - Data: `enemy_ai.json`; `battle/attack` enemy actions.
- [ ] Enemy telegraphs and forced actions (Missing)
  - Description: burst-panel-forced and break-triggered action changes.
  - Implement: re-resolve telegraphed actions on panel acquisition/break.
  - Data: burst captures; enemy behavior references.
- [x] Enemy targeting (Done, aggro estimated)
  - Description: random/aggro/fixed targeting; forced-target exceptions.
  - Implement: Defender-biased choice; targeted/random skills ignore bias.
  - Data: enemy behavior references.
- [ ] Enemy support/heal/death behavior (Partial)
  - Description: heals, buffs, summons, death rattles.
  - Implement: enemy-side support hooks; on-break/on-KO triggers; AoE
    suppression falls out of simultaneous resolution.
  - Data: boss behavior notes; status captures.
- [ ] Multiple break gauges (Missing)
  - Description: multi-gauge enemies; minor vs full break.
  - Implement: one break gauge per enemy; multiple-gauge depletion, minor
    break timing, and break-induced timeline delay are not modeled.
  - Data: enemy 10282002 capture showed break damage 2692 consuming gauge 5,
    resetting it to 3000 at gauge 4, with `small_break` timeline records.

## Battle framework

- [x] Waves and battle status (Done)
  - Description: multi-wave persistence; win/loss/countdown rules.
  - Implement: existing wave/status logic; countdown/field/wave triggers.
  - Data: `battle.json`, `wave.json`; start/finish captures.
- [ ] Field effects (Partial)
  - Description: one active field with turn-color duration rules.
  - Implement: field state, overwrite behavior, tick logic, combat hooks,
    `field_effect_id` emission (contract effect field 25).
  - Data: wave `field`; field-effect references.
- [x] Score, rewards, persistence (Done, estimated weights)
  - Description: score slots, drops, missions, EXP, profile updates.
  - Implement: existing finish pipeline; per-quest score bases still open.
  - Data: `battle/finish`; score verification page.
- [x] Protocol compatibility (Done)
  - Description: new combat must not break client response shapes.
  - Implement: incremental histories, preview fields, moves, effects,
    miss/invalid flags, and regression tests.
  - Data: `local decrypted captures`;
    `tools/JapaneseOffline/tests/test_replay_battle.py`.

## Status audit (implemented / missing / unsure)

Per-item verdicts after the description-driven pass. Granular evidence lives
in `COMBAT_CHECKLISTS/`.

- Ally skills: Implemented. All 3,446 character-referenced skills resolve;
  1,118 have confirmed behaviors; the rest resolve generically with
  records-only effects. Unsure: exact values of empty-description skill
  buffs (client-side mapping).
- Extra skills: Implemented. Rank/prefix selection, grant conditions,
  substitution, 5/battle cap. Unsure: extra-action gauge accrual, 6th-entry
  variants, re-grant chains.
- Panel skills: Implemented. Hyperlink resolution, free actions, use caps.
  Unsure: exact client history shapes for panel-skill actions.
- Active abilities: Partial. All 10 released active-skill slots have generated
  action coverage; captures directly cover 5/10. Use limits and request/response
  shapes are implemented; active timeline-swap timing/move records remain
  incomplete.
- Additional attacks: Implemented, including 200%+ overdrive with gauge
  consume. Unsure: whether bonus actions trigger their own post effects.
- Skill ranks/evolution: Implemented.
- Skill lamps: Implemented (lighting, tiers, scaled buffs, transform flag).
  Unsure: transformed numeric deltas; lit-count client display.
- Penetration: Implemented with hooks; sources default 0. Unsure: additional
  penetration sources in unmapped text.
- Transformation: Partial. Captured full-lamp Skill 2 return-to-base is
  modeled for Resna and Valeria, including form-specific passive replacement.
  Captured starts select the current form's passive IDs. Missing: base-to-
  awakened entry and other transformed numeric behavior. Unsure: lamp
  reset/consumption outside these two captured transitions.
- Range switching: Implemented with bidirectional links and display states.
  Unsure: default range for non-crossover characters; Memoria range-swap
  edge cases.
- Timeline erase/swap: Partial. Position changes/erase skips are implemented;
  active-swap wait rebasing, extra event scheduling, and move-record parity
  remain open.
- Burst selection/gauge/stocks: Implemented, including per-member stocked
  caps. Unsure: stock display fields; burst-panel forcing details.
- Character/board passives: Partial. All 7,131 ability rows are mapped; 374/432
  distinct abilities linked by released characters have nonempty parsed
  behavior, including tag-count/speed scaling. Missing: 58 released linked
  ability IDs with empty parser output and other complex state/passive systems.
- Support abilities: Partial. Stats/blob support done; 648/784 ability
  effects parsed but trigger timing/level selection unmodeled. Unsure:
  support-ability firing rules and level mapping.
- Ability conditions/caps: Partial. Parsed role, attribute, scope, weak, crit,
  KO, boss, HP, panel, skill, tag-count, and gauge conditions; separate value
  caps, stack limits, uncapped entries, and action/hit expiry are tested.
  Unsure: stack overflow refresh policy and personality-count conditions.
- Leader skill/aura: Implemented with tag/role/attribute/series condition
  filtering; Valeria's Carefree/Pioneer condition is regression-tested. Unsure:
  combat-power coefficients and unobserved leader conditions.
- Equipment stats/traits: Implemented (1,234/1,282 fully). Missing: 48
  partially parsed. Unsure: duplicate-assignment and filter semantics.
- Fixed trait effects: Implemented via parsed `fixed` flags. Unsure:
  interaction of fixed effects with caps.
- Memoria stats/abilities: Implemented (278/279). Unsure: exact battle
  formula vs estimate.
- Memoria roles/attributes: Partial. Used in support matching and
  conditions. Unsure: equip restrictions.
- Items/targeting/damage: Implemented, including mix superior forms.
  Unsure: mix field effects; exact item-heal scales.
- Battle-item traits: Implemented where parsed (120/170 with battle and
  equipment traits combined). Missing: unmapped trait texts.
- Cannons: slots/levels/use done; cannon-only bonus separation done via
  pooled-mod filtering. Partial: gauge gating (uses-gated instead).
  Unsure: cannon gauge bonus sources.
- Subspace memoria/support: stats/blob done; caps/matching/scaling
  Missing. Unsure: client-side support formula.
- Research/emblems/ship level: Implemented from profile records.
  Missing: equipment research rows; growth research. Unsure: emblem rarity
  mapping for unknown record layouts.
- Panels: Implemented (22/30 fully, 4 partial). Missing: rewrite panel,
  generation/conversion/enhancement hooks. Unsure: panel-null interactions.
- Timeline/panels adjustments: relative wait model and speed-adjusted
  requeue math implemented; delay/hasten use estimated turn-slot gaps; enemy
  schedules and opening waits remain estimates. Consecutive actions emerge
  naturally: Implemented.
- Status conditions: mapped state slots cover common stat/damage/resistance,
  ailment, item/cannon, healing, barrier, evade, cover, reflect, and null paths.
  Action-start/end and hit-count lifetimes follow Japanese master descriptions.
  Counter damage, general effect block, panel-null behavior, revival, and many
  complex state triggers are missing. Unknown state rows stay inert. Unsure:
  uncaptured stack-overflow behavior, potency edge cases, and some trigger timing.
- Enemy attacks: stats/AI/bursts/targeting and one break gauge implemented
  (growth estimated). Missing: multi-gauge depletion, telegraphs, forced
  actions, death rattles. A capture confirms a five-gauge 3000-point break
  sequence and small-break response fields.
  Unsure: enemy skill wait values; burst-panel forcing.
- Waves/status/score/finish/protocol: Implemented with estimated weights.
  Missing: task counts, missions, level-ups. Unsure: per-quest score bases.
