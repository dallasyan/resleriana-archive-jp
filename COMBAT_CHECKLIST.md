> Share copy (sanitized per AGENTS.md): local capture session paths, user directories, and profile references removed. Route names, counts, and master IDs retained. Regenerate from workspace originals.

# Combat modifier checklist (working reference)

This checklist tracks every combat action and modifier for the full-combat
implementation. Each entry has a description, the implementation approach,
and where to look for more evidence. Local capture paths are analysis
pointers only; never copy private session or profile data into shared files.

Source precedence on conflicts: linked websites beat `BATTLE_DETAILS.md`.
Canonical mechanics reference: `COMBAT_IMPLEMENTATION.md`.
Simulator: `tools/JapaneseOffline/battle_japanese.py`.
Derived data: `tools/JapaneseOffline/build_combat_map.py` plus
`battle-master/combat_map.json` (built from
`resleriana-db-main/data/master/jp`, ASCII-coded, no private data).
Contract oracle: `C:\Program Files (x86)\Steam\steamapps\common\AtelierResleriana\contract-dump\fields.txt`.

## How to read implementation status

- Done: implemented in `battle_japanese.py` with regression tests.
- Partial: structure exists, some branches estimated or unmapped.
- Missing: not implemented yet; the entry says what to do.

## Ally skills

- [x] Skill 1 / Skill 2 normal actions (Done)
  - Description: basic attacks, heals, and buff/state skills with master wait.
  - Implement: resolve via `battle-master/skill.json`; community damage, break,
    heal, and status rules; timeline move by master wait; burst/item gauges.
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
- [x] Active abilities (Done)
  - Description: limited-use skills with rest counts.
  - Implement: `activeN_skill_id` plus skill-master limits; member field 7,
    setup field 15, mode-7 field 8, action field 28; free action.
  - Data: Totori captures; `local decrypted captures`.
- [x] Additional attacks (Done)
  - Description: conditional follow-up after a triggering skill.
  - Implement: hyperlink skills resolve free with `post_hooks=False` on
    weak/crit/ko/break/skill-id triggers with use caps; 200%+ burst
    overdrive consumes 100 gauge. No timeline advance.
  - Data: ability descriptions with additional-attack hyperlinks;
    combat cases under `local battle captures`.
- [x] Skill ranks and evolution (Done)
  - Description: profile ranks pick normal rows; evolve flags switch tables.
  - Implement: existing rank/evolve selection with normal1 fallback.
  - Data: `progression-master/character.json`.
- [x] Skill lamps (Done)
  - Description: conditional lamp counts enhance skills at maximum.
  - Implement: battle-start and event lighting (skill/item/heal/panel/
    attacked/weak/ailment triggers, use caps, rank-variant resolution,
    max capping); per-lamp damage tiers and lamp-scaled pre-attack buffs;
    full-lamp transform flag with post-attack charging.
  - Data: 15 lamp abilities; `battle-master/skill.json lamp` maxima.
- [x] Penetration (Done, hooks)
  - Description: ignores part of defense and damage-taken reduction.
  - Implement: `(10x+3000)/(3x+3000)` and per-reduction
    `(x+2000)/(10x+2000)`; sources default to 0 until mapped.
  - Data: `https://atelier.xxsakixx.com/resleri/damage.html`.
- [x] Transformation (Done, estimated effect)
  - Description: full-lamp skills transform pre-attack, keep status effects.
  - Implement: `transformed` flag set at lamp max; post-attack lamp charge
    below max. Transformed numeric deltas are unmapped, so resolution is
    unchanged; flag only.
  - Data: 10 transform skill descriptions.
- [x] Range switching (Done)
  - Description: in-range/out-range toggle changes usable skills.
  - Implement: bidirectional `skill_destination` links; out-range members
    offer/resolve the destination skill 1; post-attack range moves with
    display state buffs; starting-range swap abilities.
  - Data: 120 range skills; range states in `combat_map.json`.
- [x] Timeline erase/swap skills (Done)
  - Description: target type 6 skills erase or swap timeline turns.
  - Implement: `turn_swap`/`turn_erase` effect tags resolve in
    `apply_parsed_skill_effect` and post-attack behaviors; swap validates
    the front-five range; erase marks one skip in rebuilds.
  - Data: skills 14003047/14003939 summaries; `combat_map.json` effects.

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

- [x] Character passives (Done)
  - Description: always-on behavior without grant text.
  - Implement: all 7131 ability descriptions parsed to battle-long mods
    (quoted/unquoted values resolved positionally); scope fan-out;
    condition-gated; immune to buff wipe.
  - Data: `character.json ability_ids`; `ability_parsed` map.
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
  - Implement: condition evaluation plus stacking/cap tables; never exceed
    hard caps. `combat_map.json` effects carry parsed conditions.
  - Data: status cases; permanent-debuff listings.

## Leader aura

- [x] Leader skill (Done)
  - Description: global party buff from the leader slot.
  - Implement: read leader `leader_skill`; parsed ability mods filtered by
    the condition table per member; leader trigger registration with
    scope-aware firing.
  - Data: party records; `character.json leader_skill`.
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

- [x] Item slots, uses, gauge (Done)
  - Description: 3 normal / 5 dungeon tools; 50 start, +10 per ally action,
    usable at 100, reset on use.
  - Implement: existing profile/master tool resolution and use tracking.
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
- [ ] Cannon gauge and turn cost (Partial)
  - Description: cannon gauge fills per ally action; firing costs a turn.
  - Implement: separate cannon gauge from item gauge; one use at maximum.
  - Data: cannon captures in `local battle captures`.
- [ ] Cannon-only bonuses (Missing)
  - Description: only cannon damage/crit bonuses apply, never item bonuses.
  - Implement: separate cannon bonus pipeline from the item pipeline.
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
- [ ] Support level/cannon frame bonuses (Missing)
  - Description: support level affects multipliers, cannon gauge, frames.
  - Implement: `support_ability_apply_rate` and level bonus tables.
  - Data: `ship_level.json`.

## Atelier research level

- [ ] Battle/alchemy/growth research (Missing)
  - Description: damage/HP/resist, item/equipment, and floor-level bonuses.
  - Implement: load profile field 30 research groups; map
    `combat_map.json` research tables; research is never potency-boosted.
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
  - Description: per-battle panel schedules cycled per turn.
  - Implement: existing `battle.json` panel cycling.
  - Data: `battle.json`; captured starts.
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
- [x] Timeline advance/delay (Done, estimated steps)
  - Description: wait adjustments move units on the timeline.
  - Implement: wait-based ordering and move records; free actions skip moves.
  - Data: setups/actions with `timeline_moves`.
- [ ] Consecutive actions (Partial)
  - Description: speed/weight manipulation enables back-to-back turns.
  - Implement: exact wait math preserved so setups emerge naturally.
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

- [x] Positive/negative buffs (Done)
  - Description: stat up/down, damage dealt/taken modifiers with durations.
  - Implement: additive same-slot buffs; separate taken-down multipliers;
    turn/use durations; hard caps.
  - Data: status cases under `status`; `state_change.json`.
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
    thresholds, cover redirection with `protector_id`; counter retaliation
    and reflect damage stay display-only until values are mapped.
  - Data: state-change reference page; contract barrier/protector fields.
- [ ] Immunity, cleanse, block (Missing)
  - Description: prevention and removal mechanics.
  - Implement: application checks, removal paths, resistance emission
    (contract field 18).
  - Data: status captures.
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
- [x] Multiple break gauges (Done)
  - Description: multi-gauge enemies; minor vs full break.
  - Implement: per-gauge break state; minor break slows order only.
  - Data: multi-gauge enemy captures.

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
- Active abilities: Implemented. All 10 verified end to end.
- Additional attacks: Implemented, including 200%+ overdrive with gauge
  consume. Unsure: whether bonus actions trigger their own post effects.
- Skill ranks/evolution: Implemented.
- Skill lamps: Implemented (lighting, tiers, scaled buffs, transform flag).
  Unsure: transformed numeric deltas; lit-count client display.
- Penetration: Implemented with hooks; sources default 0. Unsure: additional
  penetration sources in unmapped text.
- Transformation: Implemented as flag only. Missing: transformed numeric
  behavior. Unsure: lamp reset/consumption on transform.
- Range switching: Implemented with bidirectional links and display states.
  Unsure: default range for non-crossover characters; Memoria range-swap
  edge cases.
- Timeline erase/swap: Implemented. Unsure: target-range validation for
  type-6 skills.
- Burst selection/gauge/stocks: Implemented, including per-member stocked
  caps. Unsure: stock display fields; burst-panel forcing details.
- Character/board passives: Implemented via description parsing (2,881
  abilities with mods, 1,264 with triggers). Missing: unmapped-description
  abilities (1,087). Unsure: positional value mapping on multi-clause
  abilities; tag-count value scaling.
- Support abilities: Partial. Stats/blob support done; 648/784 ability
  effects parsed but trigger timing/level selection unmodeled. Unsure:
  support-ability firing rules and level mapping.
- Ability conditions/caps: Implemented for parsed conditions (role, attr,
  scope, weak, crit, ko, boss, HP, panel, skill, tag-count, gauge).
  Unsure: personality-count and character-specific conditions.
- Leader skill/aura: Implemented with condition table. Unsure: combat-power
  coefficients; gender/series edge conditions.
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
- Timeline/panels adjustments: wait math exact; delay/hasten estimated
  steps. Consecutive actions emerge naturally: Implemented.
- Status conditions: buffs/ailments implemented; regen/barrier/evade/
  reflect/cover/null implemented; counter retaliation display-only;
  immunity implemented; cleanse implemented. Unsure: application rates,
  barrier durability scale, reflect damage formula.
- Enemy attacks: stats/AI/bursts/targeting/multi-gauge implemented
  (growth estimated). Missing: telegraphs, forced actions, death rattles.
  Unsure: enemy skill wait values; burst-panel forcing.
- Waves/status/score/finish/protocol: Implemented with estimated weights.
  Missing: task counts, missions, level-ups. Unsure: per-quest score bases.
