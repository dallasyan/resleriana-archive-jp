> Share copy (sanitized per AGENTS.md): local capture session paths, user directories, and profile references removed. Route names, counts, and master IDs retained. Regenerate from workspace originals.

# Timeline panels

Status: Implemented = resolves fully in the sim; Partial = resolves generically with some effects records-only; Missing = not implemented; Unsure = needs capture confirmation. EN is filled only where a local mapping exists; blank EN means untranslated proper noun. Notes name the specific missing effect/ability IDs and the open value, duration, condition, or target questions for mapped parts.

| id | ja | en | status | note |
|---|---|---|---|---|
| 11 |  |  | Missing | missing: no parsed ops |
| 12 | 強化パネル | Boost Panel | Implemented | done: skill_damage applies on acquisition; unsure: skill_damage magnitude text_value 40; skill_damage default 2-action duration |
| 13 | 弱体パネル | Weaken Panel | Implemented | done: skill_damage applies on acquisition; unsure: skill_damage magnitude text_value 40; skill_damage default 2-action duration |
| 14 | バーストパネル | Burst Panel | Missing | missing: no parsed ops |
| 15 | 麻痺パネル | Paralysis Panel | Implemented | done: ailment applies on acquisition; unsure: ailment default 2-action duration; ailment paralysis rate 95 |
| 16 | 暗闇パネル | Blindness Panel | Implemented | done: ailment applies on acquisition; unsure: ailment default 2-action duration; ailment darkness rate 95 |
| 17 | バーストパネル | Burst Panel | Missing | missing: no parsed ops |
| 18 | 麻痺パネル | Paralysis Panel | Implemented | done: ailment applies on acquisition; unsure: ailment default 2-action duration; ailment paralysis rate 95 |
| 19 | 麻痺パネル | Paralysis Panel | Implemented | done: ailment applies on acquisition; unsure: ailment default 2-action duration; ailment paralysis rate 95 |
| 20 | 暗闇パネル | Blindness Panel | Implemented | done: ailment applies on acquisition; unsure: ailment default 2-action duration; ailment darkness rate 95 |
| 21 | 暗闇パネル | Blindness Panel | Implemented | done: ailment applies on acquisition; unsure: ailment default 2-action duration; ailment darkness rate 95 |
| 22 | 強化パネル | Boost Panel | Implemented | done: break_damage applies on acquisition; unsure: break_damage magnitude text_value 40; break_damage default 2-action duration |
| 23 | 書き換え用 | For Conversion | Missing | missing: no parsed ops |
| 24 | 強化+パネル | Boost+ Panel | Implemented | done: skill_damage applies on acquisition; unsure: skill_damage magnitude text_value 100; skill_damage default 2-action duration |
| 26 | 弱体+パネル | Weaken+ Panel | Implemented | done: skill_damage applies on acquisition; unsure: skill_damage magnitude text_value 60; skill_damage default 2-action duration |
| 30 | クリティカルパネル | Critical Panel | Missing | missing: crit_force panel op records-only |
| 33 | 加護強化パネル | Protection Boost Panel | Implemented | done: taken_damage applies on acquisition; unsure: taken_damage magnitude text_value 40; taken_damage default 2-action duration |
| 36 | 加護弱化パネル | Protection Weaken Panel | Implemented | done: taken_damage applies on acquisition; unsure: taken_damage magnitude text_value 40; taken_damage default 2-action duration |
| 39 | ブレイク強化パネル | Stun Boost Panel | Implemented | done: break_damage applies on acquisition; unsure: break_damage magnitude text_value 40; break_damage default 2-action duration |
| 42 | HP回復パネル | HP Recovery Panel | Implemented | done: heal applies on acquisition; unsure: heal magnitude text_value 25 |
| 45 | 火傷パネル | Burn Panel | Implemented | done: ailment_dot applies on acquisition; unsure: ailment_dot default 2-action duration |
| 46 | 麻痺+パネル | Paralysis+ Panel | Implemented | done: ailment applies on acquisition; crit_rate applies on acquisition; taken_damage applies on acquisition; unsure: ailment default 2-action duration; ailment paralysis rate 95; crit_rate magnitude text_value 100; crit_rate default 2-action duration; taken_damage magnitude text_value 30; taken_damage default 2-action duration |
| 51 | 浮き輪パネル | Tube Panel | Implemented | done: taken_damage applies on acquisition; crit_damage applies on acquisition; unsure: taken_damage magnitude text_value 40; taken_damage durations actions=0 hits=1; taken_damage holder enemy targeting; crit_damage magnitude text_value 100; crit_damage durations actions=1 hits=0; crit_damage holder ally targeting |
| 52 | 麦わらパネル | Straw Hat Panel | Partial | done: crit_rate applies on acquisition; missing: unmapped panel op; unsure: crit_rate magnitude text_value 40; crit_rate durations actions=1 hits=0; crit_rate holder ally targeting |
| 53 | 劇薬パネル | Chem Panel | Implemented | done: stat_down applies on acquisition; skill_damage applies on acquisition; taken_damage applies on acquisition; unsure: stat_down magnitude text_value 3; stat_down durations actions=2 hits=0; stat_down holder enemy targeting; skill_damage magnitude text_value 50; skill_damage durations actions=1 hits=0; skill_damage holder ally targeting +3 more |
| 54 | 叡智解放パネル | Wisdom Release Panel | Partial | done: skill_power applies on acquisition; stat_up applies on acquisition; missing: unmapped panel op; unsure: skill_power magnitude text_value 40; skill_power durations actions=1 hits=0; skill_power holder ally targeting; stat_up magnitude text_value 5; stat_up default 2-action duration; stat_up holder ally targeting |
| 63 | マルテラートパネル | Maltherate Panel | Implemented | done: ailment applies on acquisition; skill_damage applies on acquisition; unsure: ailment durations actions=1 hits=0; ailment holder enemy targeting; ailment paralysis rate 95; skill_damage magnitude text_value 15; skill_damage durations actions=1 hits=0; skill_damage holder ally targeting |
| 65 | 猛る炎パネル | Raging Flame Panel | Partial | done: crit_damage applies on acquisition; missing: taken_crit_damage panel op records-only; unsure: crit_damage magnitude text_value 75; crit_damage durations actions=1 hits=0; crit_damage holder ally targeting |
| 66 | 聖夜のまごころパネル | Holy Night Sincerity Panel | Partial | done: skill_damage applies on acquisition; missing: resist_down panel op records-only; unsure: skill_damage magnitude text_value 75; skill_damage durations actions=2 hits=0; skill_damage holder ally targeting |
| 67 | 赫の凶弾パネル | Crimson Bullet Panel | Implemented | done: penetration applies on acquisition; break_damage applies on acquisition; unsure: penetration magnitude text_value 60; penetration durations actions=0 hits=1; penetration holder enemy targeting; break_damage magnitude text_value 75; break_damage durations actions=1 hits=0; break_damage holder ally targeting |
