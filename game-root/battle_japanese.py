"""Offline generated battle simulation (approximate, crash-free).

Covers entering any quest/exploration/gacha battle, resolving player and
enemy actions round by round, and finishing with quest rewards. Combat math
follows the community damage/break/wait formulas (see COMBAT_IMPLEMENTATION.md);
the response shapes mirror captured traffic.

EST markers call out behavior estimated without capture evidence:
- wait-derived move steps, enemy initial waits, enemy AI order/targeting
- score components, subspace support scaling, per-character burst stocks
- equipment/battle-tool trait effect mapping, Memoria exact battle formula
- omitted systems: research, emblems, leader/passive abilities (neutral 1.0),
  skill panel overwrites, ailment behavior details, task-count updates,
  level-ups, item mix, transformations, range switching
"""

from __future__ import annotations

import gzip
import json
import random
import struct
import time
import uuid
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

BATTLE_MASTER_DIRNAME = "battle-master"
PROGRESSION_MASTER_DIRNAME = "progression-master"

# attack_attributes ids: 1 slash, 2 strike(impact), 3 stab(piercing),
# 4 wind, 5 fire, 6 ice, 7 bolt. Element ids 2/4/6 are estimated from game
# knowledge (no capture preview used them); physical ids use attack/defense
# with slashing/impact/piercing resistance, magic ids use magic/mental.
PHYSICAL_ATTRS = {1, 2, 3}
MAGIC_ATTRS = {4, 5, 6, 7}
ATTR_ELEMENT = {1: "slashing", 2: "impact", 3: "piercing", 4: "wind", 5: "fire", 6: "ice", 7: "lightning"}
STATUS_TYPE_TO_STAT = {
    1: "hp",
    2: "speed",
    3: "attack",
    4: "defense",
    5: "magic",
    6: "mental",
}

# Community damage model: base = 112/9 * attack * (level+9) * skill_mult / def,
# then multiplicative slots (same-category bonuses add, slots multiply).
DAMAGE_BASE_NUM = 112
DAMAGE_BASE_DEN = 9
DAMAGE_CAP = 9999999999
MIN_BATTLE_STAT = 1
WEAK_MULT = 1.5
RESIST_MULT = 0.5
WEAK_THRESHOLD = -25
RESIST_THRESHOLD = 25
CRIT_RATE = 0.10
ALLY_CRIT_RATE = 0.10
ENEMY_CRIT_RATE = 0.0
ITEM_CRIT_RATE = 0.0
CRIT_MULT = 1.5
DAMAGE_SCALE = 9.0
HEAL_SCALE = 0.45
RAND_LOW = 1.0
RAND_HIGH = 1.01

# Timeline panels: id -> skill-damage multiplier. Panel 14/17 also allow
# burst skills. Captured schedules are fixed per battle (218 distinct
# schedules across 518 starts) with no placement table in master data, so
# placement is a deterministic per-battle hash (estimated).
PANEL_OUTGOING = {}
PANEL_SKILL_DMG = {12: 1.4, 13: 0.6}
PANEL_TAKEN = {33: 0.6}
BURST_PANELS = {14, 17}
PANEL_COUNT = 10

# Item gauge (party-wide): starts at 50%, +10% per ally action, usable at
# 100%, reset on use. Burst gauges are per ally, 0-100: skill 1 +10,
# skill 2 +20, panel/no-post-action skills excluded, burst use consumes 100.
GAUGE_START = 500
GAUGE_PER_REQUEST = 100
GAUGE_MAX = 1000
GAUGE_BURST_RESET = 100
BURST_GAUGE_MAX = 100
BURST_GAIN_SKILL1 = 10
BURST_GAIN_SKILL2 = 20

WAIT_BASE = 300
PREVIEW_DAMAGE_RATE = 110.0
DAMAGE_RESULT_RATE = 110.0
CANNON_ATTACK_MODE = 9

BREAK_TAKEN_MULT = 2.0

# Score components fitted from one observed finish (estimated weights).
SCORE_TURN_BASE = 150000
SCORE_TURN_PER_TURN = 8000
SCORE_MAX_DMG_FACTOR = 0.03
SCORE_RECEIVED_BASE = 89250
SCORE_RECEIVED_PER_HP = 25
SCORE_DEAD_BASE = 53550
SCORE_DEAD_PER_ALLY = 17850


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            raise ValueError("varint is too long")
    raise ValueError("truncated varint")


def write_varint(value: int) -> bytes:
    value = int(value)
    if value < 0:
        value &= (1 << 64) - 1
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def write_sint(value: int) -> bytes:
    value = int(value)
    return write_varint((value << 1) ^ (value >> 63))


def read_wire_fields(data: bytes) -> list[tuple[int, int, object]]:
    fields: list[tuple[int, int, object]] = []
    offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if number <= 0:
            raise ValueError("invalid protobuf field number")
        if wire == 0:
            value, offset = read_varint(data, offset)
        elif wire == 1:
            value = data[offset:offset + 8]
            if len(value) != 8:
                raise ValueError("truncated fixed64 field")
            offset += 8
        elif wire == 2:
            length, offset = read_varint(data, offset)
            value = data[offset:offset + length]
            if len(value) != length:
                raise ValueError("truncated length-delimited field")
            offset += length
        elif wire == 5:
            value = data[offset:offset + 4]
            if len(value) != 4:
                raise ValueError("truncated fixed32 field")
            offset += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        fields.append((number, wire, value))
    return fields


def write_field(field_number: int, wire_type: int, value: object) -> bytes:
    encoded = write_varint((field_number << 3) | wire_type)
    if wire_type == 0:
        return encoded + write_varint(int(value))  # type: ignore[arg-type]
    if wire_type == 2:
        payload = bytes(value)  # type: ignore[arg-type]
        return encoded + write_varint(len(payload)) + payload
    return encoded + bytes(value)  # type: ignore[arg-type]


def write_wrapped_varint(field_number: int, value: int) -> bytes:
    return write_field(field_number, 2, write_field(1, 0, value))


def write_optional_wrapped_varint(field_number: int, value: int) -> bytes:
    return write_field(
        field_number,
        2,
        write_field(1, 0, value) if int(value) != 0 else b"",
    )


def write_timestamp_message(seconds: int | None = None) -> bytes:
    return write_field(1, 0, int(time.time() if seconds is None else seconds))


def varint_field(data: bytes, field_number: int, default: int = 0) -> int:
    for number, wire_type, value in read_wire_fields(data):
        if number == field_number and wire_type == 0:
            return int(value)
    return default


def wrapped_varint_field(data: bytes, field_number: int, default: int | None = None) -> int | None:
    for number, wire_type, value in read_wire_fields(data):
        if number == field_number and wire_type == 2:
            return varint_field(bytes(value), 1, 0 if default is None else default)
    return default


def packed_varint_field(data: bytes, field_number: int) -> list[int]:
    values: list[int] = []
    for number, wire_type, value in read_wire_fields(data):
        if number != field_number:
            continue
        if wire_type == 0:
            values.append(int(value))
        elif wire_type == 2:
            raw = bytes(value)
            offset = 0
            while offset < len(raw):
                current, offset = read_varint(raw, offset)
                values.append(current)
    return values


def profile_resources(profile_plaintext: bytes) -> bytes:
    return next(
        bytes(value)
        for number, wire_type, value in read_wire_fields(profile_plaintext)
        if number == 1 and wire_type == 2
    )


_BATTLE_TABLES: dict[str, dict] = {}
_PROG_TABLES: dict[str, dict] = {}


def battle_table(game_dir: Path, name: str) -> dict:
    key = str(game_dir / BATTLE_MASTER_DIRNAME / name)
    cached = _BATTLE_TABLES.get(key)
    if cached is not None:
        return cached
    data = json.loads((game_dir / BATTLE_MASTER_DIRNAME / f"{name}.json").read_text(encoding="utf-8"))
    table = data if isinstance(data, dict) else {str(i): v for i, v in enumerate(data)}
    _BATTLE_TABLES[key] = table
    return table


def prog_table(game_dir: Path, name: str) -> dict:
    key = str(game_dir / PROGRESSION_MASTER_DIRNAME / name)
    cached = _PROG_TABLES.get(key)
    if cached is not None:
        return cached
    raw = json.loads(
        (game_dir / PROGRESSION_MASTER_DIRNAME / f"{name}.json").read_text(encoding="utf-8-sig")
    )
    if isinstance(raw, list):
        table = {str(v["id"]): v for v in raw if isinstance(v, dict) and "id" in v}
    else:
        table = {str(k): v for k, v in raw.items()}
    _PROG_TABLES[key] = table
    return table


def character_level_for_exp(game_dir: Path, exp: int) -> int:
    table = prog_table(game_dir, "character_level")
    level = 1
    for key, row in table.items():
        try:
            threshold = int(row["exp"])
        except (KeyError, TypeError, ValueError):
            continue
        if exp >= threshold:
            level = max(level, int(key))
    return level


def ally_battle_stats(
    game_dir: Path,
    char_record: bytes,
    character_master: dict,
    growth_master: dict,
    rarity_master: dict,
) -> dict:
    """Effective battle stats for one profile character record.

    Base + level growth + rarity coefficients + stored growboard stats.
    Equipment/memoria/research/support/leader/passive contributions are
    not modeled (documented gap); the returned buff_base multiplier is 1.0.
    """
    character_id = varint_field(char_record, 1, -1)
    rarity = varint_field(char_record, 11, 1)
    exp = varint_field(char_record, 12, 0)
    level = character_level_for_exp(game_dir, exp)
    # Callers normally pass the selected character row. Accept the full table
    # too for tests/tools that already hold it.
    master = (
        character_master
        if "initial_status" in character_master
        else character_master.get(str(character_id), {})
    )
    initial = master.get("initial_status", {}) or {}
    growth_id = master.get("character_growth_id")
    coeffs = (growth_master.get(str(growth_id), {}) or {}).get("level_coefficients", {}) or {}
    stats: dict[str, int] = {}
    for stat in ("hp", "attack", "magic", "defense", "mental", "speed"):
        base = int(initial.get(stat, 0) or 0)
        gain = int(coeffs.get(stat, 0) or 0) * max(level - 1, 0) // 1000
        stats[stat] = base + gain
    rarity_row = rarity_master.get(str(rarity), {}) or {}
    for stat, coef in (rarity_row.get("status_coefficients", {}) or {}).items():
        if stat in stats:
            stats[stat] = stats[stat] * int(coef) // 100
    growboard_map = {
        "hp": 19, "speed": 20, "attack": 21, "magic": 22, "defense": 23, "mental": 24,
    }
    for stat, field_number in growboard_map.items():
        stats[stat] += varint_field(char_record, field_number, 0)
    all_rate = varint_field(char_record, 26, 0)
    if all_rate:
        for stat in stats:
            stats[stat] += stats[stat] * all_rate // 10000
    return {
        "character_id": character_id,
        "rarity": rarity,
        "level": level,
        "stats": stats,
    }


def add_equipment_status_buffs(stats: dict[str, int], buffs: list[dict]) -> dict[str, int]:
    """Apply the flat/profile status buffs on equipped Japanese tools."""
    out = dict(stats)
    flat: dict[str, int] = {}
    rate: dict[str, int] = {}
    for buff in buffs:
        stat = STATUS_TYPE_TO_STAT.get(int(buff.get("status_type") or 0))
        if stat is None:
            continue
        value = int(buff.get("value") or 0)
        if int(buff.get("change_method") or 1) == 1:
            flat[stat] = flat.get(stat, 0) + value
        else:
            rate[stat] = rate.get(stat, 0) + value
    for stat, value in flat.items():
        out[stat] = out.get(stat, 0) + value
    for stat, value in rate.items():
        out[stat] = out.get(stat, 0) + out.get(stat, 0) * value // 10000
    return out


def memoria_level_for_exp(game_dir: Path, record: bytes, master: dict) -> int:
    levels = prog_table(game_dir, "memoria_level")
    exp = varint_field(record, 4, 0)
    level = max(
        (
            int(key)
            for key, row in levels.items()
            if int(row.get("exp", 0) or 0) <= exp
        ),
        default=1,
    )
    rarity = prog_table(game_dir, "memoria_rarity").get(str(master.get("rarity", 1)), {})
    level_limit = int(rarity.get("level_limit", level) or level)
    return min(level, level_limit)


def add_memoria_status_buffs(
    game_dir: Path,
    stats: dict[str, int],
    record: bytes,
    master: dict,
    rate: int = 10000,
) -> tuple[dict[str, int], list[int]]:
    """Apply profile-owned Memoria stat growth and return unlocked abilities."""
    out = dict(stats)
    level = memoria_level_for_exp(game_dir, record, master)
    limit_break = varint_field(record, 3, 0)
    growths = prog_table(game_dir, "memoria_buff_growth")
    rate_buffs: dict[str, int] = {}
    for buff in master.get("status_buffs") or []:
        stat = STATUS_TYPE_TO_STAT.get(int(buff.get("type", 0) or 0))
        if stat is None:
            continue
        growth = growths.get(str(buff.get("growth_id", 0)), {})
        values = growth.get("values") or []
        if not values:
            continue
        value = int(values[min(max(level - 1, 0), len(values) - 1)] or 0)
        initial_values = buff.get("initial_values") or []
        if initial_values:
            value += int(initial_values[min(max(limit_break, 0), len(initial_values) - 1)] or 0)
        rate_buffs[stat] = rate_buffs.get(stat, 0) + value * rate // 10000
    for stat, value in rate_buffs.items():
        out[stat] = out.get(stat, 0) + out.get(stat, 0) * value // 10000
    ability_ids = [int(value) for value in master.get("ability_ids") or []]
    unlocked = min(len(ability_ids), max(1, limit_break + 1))
    return out, ability_ids[:unlocked]


def enemy_battle_stats(enemy_master: dict, level: int) -> dict:
    """Effective enemy stats. Growth is linear in (level-1)/100 with a
    sanity clamp; speed scales mildly with level (both estimated)."""
    status = enemy_master.get("status", {}) or {}
    growth = enemy_master.get("growth", {}) or {}
    ratio = min(max((level - 1) / 100, -0.1), 1.2)
    stats: dict[str, int] = {}
    for stat in ("hp", "attack", "defense"):
        stats[stat] = int((status.get(stat, 0) or 0) + (growth.get(stat, 0) or 0) * ratio)
    stats["speed"] = int((status.get("speed", 0) or 0) * (1 + max(level - 1, 0) / 200))
    stats["magic"] = 0
    stats["mental"] = 0
    break_max = max(10, round(stats["hp"] * 0.011))
    return {"stats": stats, "break_max": break_max}

def affinity_elements(attrs: list[int]) -> tuple[str, list[str]]:
    """Return (category, elements). Category is 'physical' or 'magic'."""
    if any(a in MAGIC_ATTRS for a in attrs):
        return "magic", [ATTR_ELEMENT[a] for a in attrs if a in ATTR_ELEMENT]
    return "physical", [ATTR_ELEMENT.get(a, "slashing") for a in attrs]


def combined_resistance(elements: list[str], resistance: dict, buffs: list | None = None,
                          sim=None, target: dict | None = None) -> int:
    """Weakest-link resistance across the skill elements (integer percent).

    Multi-attribute hits use the lowest enemy resistance, matching the
    mixed-attribute behavior documented for item mix. Granted elemental
    resistance buffs (e.g. item-trait resistance) add per element, as do
    conditional passive resistance mods evaluated live.
    """
    bonus = 0
    if buffs:
        for buff in buffs or []:
            if buff.get("kind") == "resist_elem" and buff.get("attr") in elements:
                bonus += int(buff.get("value", 0) or 0) // 100
    if sim is not None and target is not None:
        ctx = mod_context(sim, target, None, None)
        for mod in target.get("mods", []):
            if mod.get("code") != "resist_up" or not mod.get("conds"):
                continue
            if not conds_pass(mod.get("conds"), ctx):
                continue
            for attr in mod.get("attrs", []):
                if attr in elements:
                    bonus += int(mod.get("value", 0) or 0) // 100
                    break
    values = [int(resistance.get(e, 0) or 0) + bonus for e in elements]
    return min(values) if values else bonus


def is_weak_hit(elements: list[str], resistance: dict, buffs: list | None = None,
                sim=None, target: dict | None = None) -> bool:
    return combined_resistance(elements, resistance, buffs, sim, target) <= WEAK_THRESHOLD


def is_resist_hit(elements: list[str], resistance: dict, buffs: list | None = None,
                  sim=None, target: dict | None = None) -> bool:
    return combined_resistance(elements, resistance, buffs, sim, target) >= RESIST_THRESHOLD


def resistance_mult(res_value: int, broken: bool) -> float:
    """Resistance slot multiplier. Broken targets count -50 all-resistance."""
    res = int(res_value)
    if broken:
        res -= 50
    return (100 - res) / 100


def buff_attack_mult(buffs: list[dict]) -> float:
    """Outgoing attack/magic slot. Same-category bonuses are additive."""
    total = 0
    for buff in buffs:
        if buff.get("kind") == "out":
            total += buff.get("value", 0)
    return 1.0 + total / 10000


def buff_defense_mult(buffs: list[dict]) -> float:
    """Damage-taken slot. Taken-up bonuses add; each taken-down debuff
    multiplies separately (never added)."""
    up = 0
    mult = 1.0
    for buff in buffs:
        if buff.get("kind") != "taken":
            continue
        value = buff.get("value", 0)
        if value >= 0:
            up += value
        else:
            mult *= 1.0 + value / 10000
    return (1.0 + up / 10000) * mult


def buff_crit_rate_bonus(buffs: list[dict]) -> float:
    total = 0.0
    for buff in buffs:
        if buff.get("kind") == "crit_rate" and buff.get("id"):
            total += buff.get("value", 0) / 10000
    return total


def buff_crit_damage_bonus(buffs: list[dict]) -> float:
    total = 0.0
    for buff in buffs:
        if buff.get("kind") == "crit_damage" and buff.get("id"):
            total += buff.get("value", 0) / 10000
    return total


def buff_break_damage_bonus(buffs: list[dict]) -> float:
    total = 0
    for buff in buffs:
        if buff.get("kind") == "break_up":
            total += buff.get("value", 0)
    return total / 10000


def buff_break_power_mult(buffs: list[dict]) -> float:
    mult = 1.0
    for buff in buffs:
        if buff.get("kind") == "break_power":
            mult *= 1.0 + buff.get("value", 0) / 10000
    return mult


def buff_recovery_given_bonus(buffs: list[dict]) -> float:
    total = 0
    for buff in buffs:
        if buff.get("kind") == "recovery_given":
            total += buff.get("value", 0)
    return total / 10000


def buff_recovery_received_bonus(buffs: list[dict]) -> float:
    total = 0
    for buff in buffs:
        if buff.get("kind") == "recovery_received":
            total += buff.get("value", 0)
    return total / 10000


def buff_penetration(buffs: list[dict]) -> float:
    total = 0.0
    for buff in buffs:
        if buff.get("kind") == "penetration" and buff.get("id"):
            total += buff.get("value", 0) / 10000
    return total


def penetration_mult(penetration: float) -> float:
    penetration = max(float(penetration), 0.0)
    if penetration <= 0:
        return 1.0
    return (10 * penetration + 3000) / (3 * penetration + 3000)


def penetration_taken_factor(penetration: float) -> float:
    penetration = max(float(penetration), 0.0)
    if penetration <= 0:
        return 1.0
    return (penetration + 2000) / (10 * penetration + 2000)


def compute_hit(
    rng: random.Random,
    power: int,
    attack_stat: int,
    defense_stat: int,
    level: int,
    res_value: int,
    broken: bool,
    force_crit: bool,
    crit_rate: float,
    skill_damage_mult: float,
    skill_power_mult: float,
    outgoing_mult: float,
    taken_mult: float,
    penetration: float = 0.0,
    crit_bonus: float = 0.0,
    taken_crit: float = 0.0,
) -> tuple[int, bool]:
    attack = max(int(attack_stat), MIN_BATTLE_STAT)
    defense = max(int(defense_stat), MIN_BATTLE_STAT)
    damage = (
        DAMAGE_BASE_NUM
        / DAMAGE_BASE_DEN
        * attack
        * (max(int(level), 1) + 9)
        * max(int(power), 0)
        / 100
        / defense
        * max(skill_damage_mult, 0.0)
        * max(skill_power_mult, 0.0)
        * outgoing_mult
        * taken_mult
        * resistance_mult(res_value, broken)
        * penetration_mult(penetration)
        * (BREAK_TAKEN_MULT if broken else 1.0)
        * rng.uniform(RAND_LOW, RAND_HIGH)
    )
    critical = force_crit or rng.random() < max(crit_rate, 0.0)
    if critical:
        damage *= (CRIT_MULT + max(crit_bonus, 0.0)) * (1.0 + max(taken_crit, 0.0))
    return min(max(int(damage), 0), DAMAGE_CAP), critical


def compute_preview_damage(
    power: int,
    attack_stat: int,
    defense_stat: int,
    level: int,
    res_value: int,
    broken: bool,
    skill_damage_mult: float,
    skill_power_mult: float,
    outgoing_mult: float,
    taken_mult: float,
    penetration: float = 0.0,
) -> int:
    """Minimum-damage preview (no random factor, no crit)."""
    attack = max(int(attack_stat), MIN_BATTLE_STAT)
    defense = max(int(defense_stat), MIN_BATTLE_STAT)
    damage = (
        DAMAGE_BASE_NUM
        / DAMAGE_BASE_DEN
        * attack
        * (max(int(level), 1) + 9)
        * max(int(power), 0)
        / 100
        / defense
        * max(skill_damage_mult, 0.0)
        * max(skill_power_mult, 0.0)
        * outgoing_mult
        * taken_mult
        * resistance_mult(res_value, broken)
        * penetration_mult(penetration)
        * (BREAK_TAKEN_MULT if broken else 1.0)
    )
    return min(max(int(damage), 0), DAMAGE_CAP)


def compute_break_hit(
    rng: random.Random | None,
    attack_stat: int,
    skill_break_pct: float,
    res_value: int,
    break_damage_bonus: float = 0.0,
    break_power_mult: float = 1.0,
) -> int:
    """Community break formula: 125 * (1 - 100/(atk+100)) * break_mult
    * (break_up + taken_break_up) * break_power * resistance * random."""
    attack = max(int(attack_stat), 0)
    damage = (
        125
        * (1 - 100 / (attack + 100))
        * max(float(skill_break_pct), 0.0)
        * (1.0 + break_damage_bonus)
        * max(break_power_mult, 0.0)
        * (100 - int(res_value))
        / 100
    )
    if rng is not None:
        damage *= rng.uniform(RAND_LOW, RAND_HIGH)
    return max(int(damage), 0)


def compute_heal(
    rng: random.Random | None,
    power: int,
    attack_stat: int,
    recovery_bonus: float = 0.0,
) -> int:
    heal = (
        max(int(power), 0)
        * max(int(attack_stat), 0)
        / 100
        * HEAL_SCALE
        * (1.0 + recovery_bonus)
    )
    if rng is not None:
        heal *= rng.uniform(RAND_LOW, RAND_HIGH)
    return max(int(heal), 0)


def effective_wait(speed: int, master_wait: int) -> int:
    """Wait value for timeline placement: floor(57600/speed) + master wait.

    Master wait rows already encode the standard -200 offset (a standard
    skill carries wait 0, fast skills carry negative waits).
    """
    return 57600 // max(int(speed), 1) + int(master_wait or 0)


_COMBAT_MAPS: dict[str, dict] = {}


def combat_map(game_dir: Path) -> dict:
    """Derived combat map (states, panels, effects, research, emblems, mix).

    Built from community master data by build_combat_map.py; ASCII-coded.
    Missing file degrades to {} (all lookups neutral).
    """
    key = str(game_dir)
    if key not in _COMBAT_MAPS:
        try:
            raw = (game_dir / BATTLE_MASTER_DIRNAME / "combat_map.json").read_text(encoding="utf-8")
            _COMBAT_MAPS[key] = json.loads(raw)
        except (OSError, ValueError):
            _COMBAT_MAPS[key] = {}
    return _COMBAT_MAPS[key]


def cmap_states(game_dir: Path) -> dict:
    return combat_map(game_dir).get("states", {})


def cmap_effects(game_dir: Path) -> dict:
    return combat_map(game_dir).get("effects", {})


def cmap_panels(game_dir: Path) -> dict:
    return combat_map(game_dir).get("panels", {})


def cmap_skill_behavior(game_dir: Path) -> dict:
    return combat_map(game_dir).get("skill_behavior", {})


def state_kind(game_dir: Path, state_id: int) -> dict:
    info = cmap_states(game_dir).get(str(state_id))
    if info is None:
        return {"kind": "special"}
    return info


def parsed_effect(game_dir: Path, effect_id: int) -> dict:
    info = cmap_effects(game_dir).get(str(effect_id))
    if info is None:
        return {"code": "unmapped"}
    return info


def effect_magnitude(parsed: dict, runtime_value: int) -> int:
    """Resolve an effect value to basis points.

    Explicit N% text wins; otherwise the runtime value (trait rank value,
    ability value, or skill effect value) is already in basis points.
    """
    if parsed.get("placeholder"):
        return int(runtime_value or 0)
    text_value = int(parsed.get("text_value") or 0)
    if text_value:
        return text_value * 100
    return int(runtime_value or 0)


def pct_heal_fraction(value_bp: int) -> float:
    """Percent-of-max-HP fraction. Values over 1000 are basis points."""
    value = int(value_bp or 0)
    if value > 1000:
        return value / 10000
    return value / 100


def conds_pass(conds: list | None, ctx: dict) -> bool:
    """Evaluate parsed effect conditions. Unknown conditions fail closed."""
    for cond in conds or []:
        name = cond.get("cond")
        if name == "role":
            role_names = {1: "attacker", 2: "breaker", 3: "defender", 4: "supporter"}
            if role_names.get(ctx.get("role")) != cond.get("role"):
                return False
        elif name == "attr":
            if cond.get("attr") not in (ctx.get("owner_attrs") or []) and \
                    cond.get("attr") not in (ctx.get("attrs") or []):
                return False
        elif name == "target_state":
            if cond.get("state") == "broken":
                if not ctx.get("target_broken"):
                    return False
            elif not ctx.get("target_states", {}).get(cond.get("state")):
                return False
        elif name == "target_broken":
            if not ctx.get("target_broken"):
                return False
        elif name == "hp_above":
            if ctx.get("actor_hp_frac", 1.0) * 100 < cond.get("value", 0):
                return False
        elif name == "hp_below":
            if ctx.get("actor_hp_frac", 1.0) * 100 > cond.get("value", 100):
                return False
        elif name == "crit":
            if not ctx.get("critical"):
                return False
        elif name == "ko":
            if not ctx.get("ko"):
                return False
        elif name == "boss":
            if not ctx.get("boss"):
                return False
        elif name == "weak_hit":
            if not ctx.get("weak"):
                return False
        elif name == "scope":
            if ctx.get("scope") != cond.get("scope"):
                return False
        elif name == "skill_ids":
            if ctx.get("skill_id", 0) not in (cond.get("skills") or []):
                return False
        elif name == "skill_attr":
            if cond.get("attr") not in (ctx.get("attrs") or []):
                return False
        elif name == "panel":
            if ctx.get("panel_cat") != cond.get("panel"):
                return False
        elif name == "tag_count":
            tag = cond.get("tag", 0)
            if not tag or sum(1 for m in ctx.get("party", []) if tag in (m.get("tags") or [])) < cond.get("min", 1):
                return False
        elif name == "gauge_above":
            if int(owner_gauge(ctx)) < cond.get("value", 0):
                return False
        else:
            return False
    return True


def owner_gauge(ctx: dict) -> int:
    member = ctx.get("owner_member")
    if isinstance(member, dict):
        return int(member.get("burst_gauge", 0) or 0)
    return 0


def burst_max(member: dict) -> int:
    """Per-ally burst gauge cap: 100 per stocked gauge from burst-stock mods."""
    return max(int(member.get("burst_max", 0) or BURST_GAUGE_MAX), BURST_GAUGE_MAX)


PANEL_CATS = {1: "empty", 2: "plus", 3: "minus", 4: "burst"}


def panel_cat(game_dir: Path, panel_id: int | None) -> str:
    if panel_id is None:
        return ""
    return PANEL_CATS.get(int(battle_table(game_dir, "timeline_panel").get(str(panel_id), {}).get("type", 0) or 0), "")


def mod_context(sim: "BattleSim", actor: dict, target: dict | None, skill: dict | None,
                is_aoe: bool = False, is_item: bool = False, is_cannon: bool = False,
                is_burst: bool = False, weak: bool = False, critical: bool = False) -> dict:
    """Evaluation context for owner modifiers and effect conditions."""
    elements: list[str] = []
    if skill:
        _, elements = affinity_elements(skill.get("attrs") or [])
    target_states: dict[str, bool] = {}
    target_broken = False
    boss = False
    target_hp_frac = 1.0
    if target is not None:
        target_broken = bool(target.get("broken"))
        boss = bool(target.get("boss"))
        target_hp_frac = target.get("hp", 1) / max(target.get("max_hp", 1), 1)
        for buff in target.get("buffs", []):
            ailment = buff.get("ailment")
            if ailment:
                target_states[ailment] = True
    actor_hp = actor.get("hp", 1)
    return {
        "role": actor.get("role"),
        "owner_attrs": actor.get("attrs") or [],
        "attrs": elements,
        "scope": "aoe" if is_aoe else "single",
        "weak": weak,
        "critical": critical,
        "ko": False,
        "boss": boss,
        "target_broken": target_broken,
        "target_states": target_states,
        "target_hp_frac": target_hp_frac,
        "actor_hp_frac": actor_hp / max(actor.get("max_hp", 1), 1),
        "foe_count": len(sim.alive_foes()) if sim is not None else 1,
        "is_item": is_item,
        "is_cannon": is_cannon,
        "is_burst": is_burst,
        "party": sim.alive_allies() if sim is not None else [],
    }


# Modifier codes that feed the damage slots. direction +1 adds, -1 subtracts.
SLOT_CODES = {
    "skill_damage", "dealt_damage", "skill_power", "taken_damage",
    "crit_rate", "crit_damage", "break_damage", "taken_break",
    "burst_damage",
}


def sum_slot_mods(mods: list[dict], codes: set[str], ctx: dict,
                  require_item: bool = False, require_cannon: bool = False,
                  require_burst: bool = False) -> int:
    total = 0
    for mod in mods or []:
        code = mod.get("code")
        if code not in codes:
            continue
        if mod.get("foe"):
            continue
        if code in ("item_damage", "item_heal") and not (ctx.get("is_item") or require_item):
            continue
        if code in ("cannon_damage", "cannon_crit") and not (ctx.get("is_cannon") or require_cannon):
            continue
        if code == "burst_damage" and not (ctx.get("is_burst") or require_burst):
            continue
        if not conds_pass(mod.get("conds"), ctx):
            continue
        direction = mod.get("direction", 1)
        total += direction * int(mod.get("value", 0) or 0)
    return total


def collect_owner_mods(game_dir: Path, parsed_list: list[tuple[dict, int]]) -> list[dict]:
    """Turn (parsed effect, runtime value) pairs into owner modifier entries."""
    mods = []
    for parsed, runtime_value in parsed_list:
        code = parsed.get("code")
        if code in (None, "unmapped"):
            continue
        mods.append({
            "code": code,
            "value": effect_magnitude(parsed, runtime_value),
            "conds": parsed.get("conds") or [],
            "direction": parsed.get("direction", 1),
            "rate": parsed.get("rate", 100),
            "cap": parsed.get("cap", 0),
            "fixed": bool(parsed.get("fixed")),
            "dur_actions": parsed.get("dur_actions", 0),
            "dur_hits": parsed.get("dur_hits", 0),
            "perm": bool(parsed.get("perm")),
            "foe": bool(parsed.get("foe")),
            "slot": parsed.get("slot"),
            "attr": parsed.get("attr"),
        })
    return mods


def ability_parsed_parts(game_dir: Path, ability_ids: list[int]) -> tuple[list, list, list]:
    """Split parsed ability descriptions into battle-long mods.

    Returns (own_mods, party_mods, triggers). Party mods carry scope
    all_allies and are fanned out to every ally at battle setup; triggers
    fire on their parsed events with per-member use counters.
    """
    table = combat_map(game_dir).get("ability_parsed", {})
    own, party, triggers = [], [], []
    for ability_id in ability_ids or []:
        entry = table.get(str(ability_id))
        if not entry:
            continue
        for mod in entry.get("mods", []):
            (party if mod.get("scope") == "all_allies" else own).append(mod)
        triggers.extend(entry.get("triggers", []))
    return own, party, triggers


def ability_mods(game_dir: Path, ability_ids: list[int]) -> list[dict]:
    """Resolve ability ids to owner modifier entries via parsed descriptions."""
    own, _, _ = ability_parsed_parts(game_dir, ability_ids)
    return own


def trait_mods(game_dir: Path, trait_table: dict, traits: list[tuple[int, int]]) -> list[dict]:
    """Resolve (trait_id, rank) pairs. Battle-tool traits carry rank-indexed
    value arrays; equipment traits resolve through ability ids."""
    abilities = combat_map(game_dir).get("abilities", {})
    effects = cmap_effects(game_dir)
    pairs = []
    for trait_id, rank in traits or []:
        row = trait_table.get(str(trait_id), {})
        if row.get("ability_ids"):
            ability_list = row.get("ability_ids") or []
            ability_id = ability_list[min(max(rank, 1), len(ability_list)) - 1] if ability_list else 0
            entry = abilities.get(str(ability_id))
            if entry:
                for effect in entry.get("effects") or []:
                    parsed = effects.get(str(effect.get("id")), {"code": "unmapped"})
                    pairs.append((parsed, effect.get("value") or 0))
            continue
        for effect in row.get("effects") or []:
            values = effect.get("values") or []
            if not values:
                continue
            value = values[min(max(rank, 1), len(values)) - 1]
            parsed = effects.get(str(effect.get("id")), {"code": "unmapped"})
            pairs.append((parsed, value))
    return collect_owner_mods(game_dir, pairs)


RANGE_IN_STATE = 610239
RANGE_OUT_STATE = 610227


def lamp_skill_for_member(member: dict, variants: list) -> int:
    """Resolve a lamp skill name to the member's own rank variant."""
    if not variants:
        return 0
    owned = set((member.get("skills") or {}).values())
    for variant in variants:
        if variant in owned:
            return variant
    rank = max(int(member.get("skill_rank2", 5) or 5), 1)
    return variants[min(rank, len(variants)) - 1]


def collect_lamp_bonus(triggers: list, rank2: int) -> list[dict]:
    """Per-lamp damage rules with skill variants resolved to rank rows."""
    rules = []
    for trig in triggers or []:
        if trig.get("op") != "lamp_bonus":
            continue
        variants = trig.get("skill_variants") or []
        skill_id = variants[min(max(rank2, 1), len(variants)) - 1] if variants else 0
        rules.append({"skill_id": skill_id, "code": trig.get("code"),
                      "direction": trig.get("direction", 1),
                      "per_lamp_value": trig.get("per_lamp_value", 0)})
    return rules


def lamp_max_for_skill(game_dir: Path, skill_id: int) -> int:
    return int(combat_map(game_dir).get("skills", {}).get(str(skill_id), {}).get("lamp_max", 0) or 0)


def light_lamp(member: dict, skill_id: int, count: int, lamp_max: int) -> int:
    """Light skill lamps up to the skill maximum. Returns lamps added."""
    if not skill_id or lamp_max <= 0:
        return 0
    lit = member.setdefault("lamp_lit", {})
    before = int(lit.get(skill_id, 0) or 0)
    after = min(before + max(int(count), 0), lamp_max)
    lit[skill_id] = after
    return after - before


def lamp_damage_bonus(game_dir: Path, actor: dict, skill_id: int) -> int:
    """Per-lamp skill-damage bonus in basis points for the resolved skill."""
    total = 0
    lit = (actor.get("lamp_lit") or {}).get(skill_id, 0)
    if not lit:
        return 0
    for rule in actor.get("lamp_bonus") or []:
        if rule.get("skill_id") != skill_id:
            continue
        if rule.get("code") != "skill_damage":
            continue
        total += int(rule.get("direction", 1)) * int(rule.get("per_lamp_value", 0) or 0) * int(lit)
    return total


def heal_member(sim: "BattleSim", member: dict, amount: int, fire: bool = True) -> int:
    """Heal with optional heal-received trigger firing. Returns HP restored."""
    if not member.get("alive") or amount <= 0:
        return 0
    before = member["hp"]
    member["hp"] = min(before + amount, member.get("max_hp", before))
    restored = member["hp"] - before
    if fire and restored > 0 and member["side"] == 0:
        fire_triggers(sim, "heal_received", member, {})
    return restored


def resolve_trigger_owners(sim: "BattleSim", owner: dict, scope: str, target: str, ctx: dict) -> list[dict]:
    """Resolve which members a trigger payload applies to."""
    if target == "extreme_enemy_hp_max":
        foes = sim.alive_foes()
        return [max(foes, key=lambda m: m.get("hp", 0))] if foes else []
    if target == "extreme_enemy_hp_min":
        foes = sim.alive_foes()
        return [min(foes, key=lambda m: m.get("hp", 0))] if foes else []
    if target == "extreme_enemy_break_max":
        foes = [m for m in sim.alive_foes() if m.get("break_cur") is not None]
        if foes:
            return [max(foes, key=lambda m: m.get("break_cur", 0))]
        foes = sim.alive_foes()
        return [foes[0]] if foes else []
    if target == "skill_target" and ctx.get("target_member") is not None:
        return [ctx["target_member"]]
    if target == "attacker" and ctx.get("attacker_member") is not None:
        return [ctx["attacker_member"]]
    if scope == "all_allies":
        return sim.alive_allies() if owner["side"] == 0 else sim.alive_foes()
    if scope == "all_enemies":
        return sim.alive_foes() if owner["side"] == 0 else sim.alive_allies()
    return [owner]


def grant_trigger_buff(sim: "BattleSim", giver: dict, owner: dict, entry: dict) -> None:
    """Apply a trigger payload buff as a hidden member buff."""
    code = entry.get("code")
    value = int(entry.get("value", 0) or 0)
    direction = int(entry.get("direction", 1))
    rest = int(entry.get("dur_actions", 0) or 0) or 2
    buff = {"id": 0, "value": direction * value, "rest": rest,
            "display": False}
    if code in ("skill_damage", "skill_power", "crit_rate", "crit_damage",
                "break_damage", "taken_break", "penetration"):
        buff["kind"] = code
    elif code == "taken_damage":
        buff["kind"] = "taken"
    elif code == "dealt_damage":
        buff["kind"] = "skill_damage"
    elif code in ("stat_up", "stat_down"):
        stat = entry.get("stat")
        if stat in ("attack", "magic"):
            buff["kind"] = "out"
        elif stat in ("defense", "mental"):
            buff["kind"] = "defense"
        elif stat == "speed":
            buff["kind"] = "speed"
        else:
            return
    elif code in ("heal_given", "heal_received"):
        buff["kind"] = "recovery_given" if code == "heal_given" else "recovery_received"
    elif code == "burst_damage":
        buff["kind"] = "burst_damage"
    elif code == "resist_up":
        buff["kind"] = "resist_up"
        buff["ailment"] = entry.get("ailment")
    elif code == "resist_down":
        buff["kind"] = "resist_down"
        buff["attr"] = entry.get("attr", "unknown")
    elif code == "ailment_resist":
        buff["kind"] = "resist_up"
        buff["ailment"] = entry.get("ailment")
    elif code == "panel_null":
        buff["kind"] = "panel_null"
    elif code in ("ailment", "ailment_dot", "regen", "barrier", "evade",
                  "reflect", "cover", "null_damage", "counter", "break_power"):
        buff["kind"] = code
        for key in ("ailment", "reflect"):
            if entry.get(key) is not None:
                buff[key] = entry[key]
    else:
        return
    if entry.get("dur_hits"):
        buff["hits"] = int(entry["dur_hits"])
    if entry.get("perm"):
        buff["rest"] = None
    owner["buffs"].append(buff)


def fire_action_triggers(sim: "BattleSim", actor: dict, skill_id: int, results: list,
                         target_member: dict | None, panel: int | None,
                         is_item: bool = False, is_cannon: bool = False,
                         is_aoe: bool = False) -> None:
    """Fire post-resolution trigger events for one ally action.

    Shared by skill, tool, cannon, mix, and active actions so item traits
    and ability triggers observe every action kind.
    """
    post_ctx = {
        "skill_id": skill_id,
        "target_member": target_member,
        "panel_cat": panel_cat(sim.game_dir, panel),
        "weak": any(isinstance(r, dict) and r.get("weak") for r in results),
        "critical": any(isinstance(r, dict) and r.get("critical") for r in results),
        "ko": any(isinstance(r, dict) and r.get("killed") for r in results),
        "is_item": is_item,
        "is_cannon": is_cannon,
        "scope": "aoe" if is_aoe else "single",
    }
    fire_triggers(sim, "skill_use", actor, post_ctx)
    fire_triggers(sim, "post_attack", actor, post_ctx)
    if post_ctx["weak"]:
        fire_triggers(sim, "weak_hit", actor, post_ctx)
    if post_ctx["critical"]:
        fire_triggers(sim, "crit", actor, post_ctx)
    if post_ctx["ko"]:
        fire_triggers(sim, "ko", actor, post_ctx)
    if target_member is not None and target_member.get("broken"):
        fire_triggers(sim, "break_hit", actor, post_ctx)
    if target_member is not None and any(
        b.get("kind") == "ailment" for b in target_member.get("buffs", [])
    ):
        fire_triggers(sim, "target_ailment_hit", actor, post_ctx)


def execute_trigger_code(sim: "BattleSim", owner: dict, targets: list[dict], code: str, value: int) -> None:
    """Execute non-buff trigger payload codes."""
    if code == "cleanse":
        for target in targets:
            remove_debuffs(target)
    elif code == "heal":
        for target in targets:
            heal_member(sim, target, int(target.get("max_hp", 0) * pct_heal_fraction(value)), fire=False)
    elif code == "item_gauge":
        sim.party_gauge = min(sim.party_gauge + int(GAUGE_MAX * pct_heal_fraction(value)), GAUGE_MAX)
    elif code == "burst_gauge":
        owner["burst_gauge"] = min(int(owner.get("burst_gauge", 0) or 0) + int(pct_heal_fraction(value) * BURST_GAUGE_MAX), BURST_GAUGE_MAX)
    elif code == "turn_swap" and targets:
        swap_order_positions(sim, owner["id"], targets[0]["id"])
    elif code == "turn_erase" and targets:
        erase_order_entry(sim, targets[0]["id"])
    elif code == "delay_turn":
        for target in targets:
            shift_order(sim, target["id"], +2)
    elif code == "hasten_turn":
        for target in targets:
            shift_order(sim, target["id"], -1)
    elif code == "range_swap":
        set_member_range(sim, owner, "out" if owner.get("range", "in") == "in" else "in")


def set_member_range(sim: "BattleSim", member: dict, new_range: str) -> None:
    """Flip a member's range state with display buffs."""
    if member.get("range", "in") == new_range:
        return
    member["range"] = new_range
    member["buffs"] = [b for b in member.get("buffs", [])
                       if b.get("id") not in (RANGE_IN_STATE, RANGE_OUT_STATE)]
    state_id = RANGE_IN_STATE if new_range == "in" else RANGE_OUT_STATE
    member["buffs"].append({"id": state_id, "value": 0, "rest": None,
                            "kind": "special", "display": True})


def effective_skill1(game_dir: Path, member: dict) -> int:
    """Skill-1 id honoring range: out-range members use the destination skill."""
    skills = member.get("skills") or {}
    base = skills.get(1, 0)
    if member.get("range", "in") == "out" and base:
        dest = combat_map(game_dir).get("skills", {}).get(str(base), {}).get("dest", 0)
        if dest:
            return int(dest)
    return base


def fire_triggers(sim: "BattleSim", event: str, owner: dict, ctx: dict | None = None) -> list:
    """Fire an owner's ability triggers for one combat event.

    Guarded against cascade loops; per-trigger use caps are tracked on
    the owner. Returns fired action blobs (panel/additional skills).
    """
    if owner is None or owner.get("side") != 0:
        return []
    if sim.trigger_depth >= 2:
        return []
    fired = []
    base = mod_context(sim, owner, (ctx or {}).get("target_member"), None)
    base.update(ctx or {})
    base["owner_member"] = owner
    for index, trig in enumerate(owner.get("triggers", [])):
        if trig.get("event") != event:
            continue
        uses_max = int(trig.get("uses_max", 0) or 0)
        if uses_max:
            used = owner.setdefault("trigger_uses", {}).get(index, 0)
            if used >= uses_max:
                continue
            owner["trigger_uses"][index] = used + 1
        if not conds_pass(trig.get("conds"), base):
            continue
        op = trig.get("op")
        if op == "lamp_light":
            skill_id = lamp_skill_for_member(owner, trig.get("skill_variants") or [])
            count = int(trig.get("count", 0) or 0)
            if count > 10:
                count //= 100
            light_lamp(owner, skill_id, count, lamp_max_for_skill(sim.game_dir, skill_id))
        elif op == "lamp_bonus":
            continue
        elif op == "lamp_scaled":
            skill_id = lamp_skill_for_member(owner, trig.get("skill_variants") or [])
            lamp_max = max(lamp_max_for_skill(sim.game_dir, skill_id), 1)
            lit = max(min(int(owner.get("lamp_lit", {}).get(skill_id, 0) or 0), lamp_max), 1)
            span = max(lamp_max - 1, 1)
            value = int(trig.get("lo_value", 0) or 0) + (
                int(trig.get("hi_value", 0) or 0) - int(trig.get("lo_value", 0) or 0)
            ) * (lit - 1) // span
            buff = {"id": 0, "value": int(trig.get("direction", 1)) * value,
                    "rest": int(trig.get("dur_actions", 0) or 0) or 1, "display": False}
            code = trig.get("code")
            if code in ("skill_damage", "skill_power", "crit_rate", "crit_damage",
                        "break_damage", "taken_break", "penetration"):
                buff["kind"] = code
            elif code == "taken_damage":
                buff["kind"] = "taken"
            else:
                continue
            owner["buffs"].append(buff)
        elif op == "range_swap":
            execute_trigger_code(sim, owner, [owner], "range_swap", 0)
        elif op == "buff":
            buff = trig.get("buff", {})
            if buff.get("code") in ("heal", "item_gauge", "burst_gauge", "cleanse",
                                    "turn_swap", "turn_erase", "delay_turn", "hasten_turn",
                                    "field", "revive", "panel_generate", "panel_convert",
                                    "panel_enhance", "extra_attack", "transform", "lamp",
                                    "pioneer", "drain", "accuracy_down", "resist_down"):
                owners = resolve_trigger_owners(sim, owner, buff.get("scope", "self"),
                                                trig.get("target", "context"), base)
                execute_trigger_code(sim, owner, owners, buff["code"], int(buff.get("value", 0) or 0))
            else:
                owners = resolve_trigger_owners(sim, owner, buff.get("scope", "self"),
                                                trig.get("target", "context"), base)
                for member in owners:
                    if member.get("alive"):
                        grant_trigger_buff(sim, owner, member, buff)
        elif op in ("panel_skill", "extra_attack"):
            owners = resolve_trigger_owners(sim, owner, "self", trig.get("target", "context"), base)
            target_id = owners[0]["id"] if owners else None
            if trig.get("consume"):
                owner["burst_gauge"] = max(int(owner.get("burst_gauge", 0) or 0) - int(trig["consume"]), 0)
            sim.trigger_depth += 1
            try:
                results, blobs, skill_id, _ = resolve_ally_action(
                    sim, owner, 1, target_id,
                    next((t for mid, t in sim.order if mid == owner["id"]), sim.turn),
                    panel_for_turn(sim.game_dir, sim.battle_id,
                                   next((t for mid, t in sim.order if mid == owner["id"]), sim.turn)),
                    skill_id_override=trig.get("skill_id"), post_hooks=False,
                )
            finally:
                sim.trigger_depth -= 1
            blob = build_action(
                sim, sim.action_no + 1, owner, skill_id, None, target_id,
                results, blobs, [], sim.total_dealt_hp_damage,
            )
            sim.action_no += 1
            sim.actions.append(blob)
            fired.append(blob)
    return fired


ATTR_ID_TO_ELEMENT = {1: "slashing", 2: "impact", 3: "piercing", 4: "wind", 5: "fire", 6: "ice", 7: "lightning"}
ROLE_ID_TO_NAME = {1: "attacker", 2: "breaker", 3: "defender", 4: "supporter"}


def character_elements(master: dict) -> list[str]:
    return [ATTR_ID_TO_ELEMENT[a] for a in master.get("attack_attributes") or [] if a in ATTR_ID_TO_ELEMENT]


def start_mod_context(entry: dict) -> dict:
    """Condition context at battle start (no target yet)."""
    return {
        "role": entry.get("role"),
        "owner_attrs": entry.get("attrs") or [],
        "attrs": entry.get("attrs") or [],
        "scope": "single",
        "weak": False,
        "critical": False,
        "ko": False,
        "boss": False,
        "target_broken": False,
        "target_states": {},
        "target_hp_frac": 1.0,
        "actor_hp_frac": 1.0,
        "foe_count": 1,
        "is_item": False,
        "is_cannon": False,
        "is_burst": False,
    }


def apply_start_stat_mods(stats: dict, mods: list[dict], ctx: dict) -> dict:
    """Apply battle-long percentage stat modifiers (traits, research)."""
    out = dict(stats)
    for mod in mods:
        if mod.get("code") not in ("stat_up", "stat_down"):
            continue
        if not conds_pass(mod.get("conds"), ctx):
            continue
        stat = mod.get("stat")
        if stat not in out:
            continue
        value = int(mod.get("value", 0) or 0)
        if mod.get("code") == "stat_down":
            value = -value
        out[stat] = max(int(out.get(stat, 0) * (1 + value / 10000)), MIN_BATTLE_STAT)
    return out


def research_stat_levels(game_dir: Path, profile_plaintext: bytes) -> dict:
    """Profile research groups {group_id: level} from resource field 30."""
    levels: dict[int, int] = {}
    try:
        resources = profile_resources(profile_plaintext)
    except (ValueError, StopIteration):
        return levels
    for number, wire, value in read_wire_fields(resources):
        if number != 30 or wire != 2:
            continue
        record = bytes(value)
        group = varint_field(record, 1, 0)
        level = varint_field(record, 2, 0)
        if group:
            levels[group] = max(levels.get(group, 0), level)
    return levels


def research_start_mods(game_dir: Path, profile_plaintext: bytes, entry: dict) -> list[dict]:
    """Research stat bonuses for one party entry. Research is never boosted
    by potency systems; role-scoped rows apply to matching roles only."""
    tables = combat_map(game_dir).get("research", {})
    levels = research_stat_levels(game_dir, profile_plaintext)
    mods = []
    for group, level in levels.items():
        rows = tables.get(str(group), {})
        row = rows.get(str(level))
        if not row:
            continue
        for effect in row.get("effects") or []:
            value = int(effect.get("value", 0) or 0)
            for buff in effect.get("status_buffs") or []:
                stat = STATUS_TYPE_TO_STAT.get(int(buff.get("status_type") or 0))
                if stat is None:
                    continue
                roles = buff.get("role")
                role_list = roles if isinstance(roles, list) else ([roles] if roles else [])
                if role_list and entry.get("role") not in role_list:
                    continue
                mods.append({"code": "stat_up", "stat": stat, "value": value,
                             "conds": [], "direction": 1})
    return mods


def emblem_records(profile_plaintext: bytes) -> list[tuple[int, int]]:
    """Owned emblems as (emblem_id, rarity) from resource field 19."""
    owned = []
    try:
        resources = profile_resources(profile_plaintext)
    except (ValueError, StopIteration):
        return owned
    for number, wire, value in read_wire_fields(resources):
        if number != 19 or wire != 2:
            continue
        record = bytes(value)
        emblem_id = varint_field(record, 1, 0)
        rarity = varint_field(record, 2, 1)
        if emblem_id:
            owned.append((emblem_id, rarity))
    return owned


def emblem_start_mods(game_dir: Path, profile_plaintext: bytes, entry: dict) -> tuple[list[dict], list[dict]]:
    """Emblem stat bonuses and combat mods for one party entry.

    Values resolve from the emblem rarity table; effect templates map
    through the combat map with attribute conditions.
    """
    cmap = combat_map(game_dir)
    table = cmap.get("emblems", {})
    values = cmap.get("emblem_values", {})
    ctx = start_mod_context(entry)
    stat_mods = []
    combat_mods = []
    for emblem_id, rarity in emblem_records(profile_plaintext):
        rows = values.get(str(emblem_id), [])
        row = None
        for candidate in rows:
            if int(candidate.get("rarity", 0) or 0) <= rarity:
                row = candidate
        if row is None:
            continue
        value = int(row.get("value", 0) or 0)
        for buff in row.get("status_buffs") or []:
            stat = STATUS_TYPE_TO_STAT.get(int(buff.get("status_type") or 0))
            if stat is not None:
                stat_mods.append({"code": "stat_up", "stat": stat, "value": value,
                                  "conds": [], "direction": 1})
        parsed = (table.get(str(emblem_id), {}) or {}).get("parsed") or {}
        if parsed.get("code") in (None, "unmapped"):
            continue
        mod = {"code": parsed["code"], "value": effect_magnitude(parsed, value),
               "conds": parsed.get("conds") or [], "direction": parsed.get("direction", 1)}
        if not conds_pass(mod["conds"], ctx):
            continue
        if mod["code"] in ("stat_up", "stat_down"):
            stat_mods.append(mod)
        else:
            combat_mods.append(mod)
    return stat_mods, combat_mods


def leader_mods_for_member(game_dir: Path, leader_master: dict, entry: dict) -> tuple[list, list]:
    """Leader-skill parsed mods and triggers applying to one party entry.

    Conditions (tags, roles, attributes, series) come from the leader
    condition table; unmatched members get nothing. Returns
    (mods, triggers); triggers are only returned for the leader's own
    entry so party-wide effects fire exactly once.
    """
    leader_skill = leader_master.get("leader_skill") or {}
    abilities = leader_skill.get("abilities") or []
    if not abilities:
        return [], []
    conditions = combat_map(game_dir).get("leader_conditions", {})
    mods, triggers = [], []
    for ability in abilities:
        ok = True
        for condition_id in ability.get("condition_ids") or []:
            cond = conditions.get(str(condition_id))
            if cond is None:
                ok = False
                break
            if cond.get("tags") and not set(cond["tags"]) & set(entry.get("tags") or []):
                ok = False
                break
            if cond.get("roles") and entry.get("role") not in cond["roles"]:
                ok = False
                break
            if cond.get("attrs") and not set(cond["attrs"]) & set(
                    master_attr_ids(entry)):
                ok = False
                break
            if cond.get("series") and entry.get("series") not in cond["series"]:
                ok = False
                break
        if not ok:
            continue
        own, party, trigs = ability_parsed_parts(game_dir, [int(ability.get("ability_id") or 0)])
        mods.extend(own)
        mods.extend(party)
        if entry.get("leader"):
            triggers.extend(trigs)
    return mods, triggers


def master_attr_ids(entry: dict) -> list[int]:
    inv = {v: k for k, v in ATTR_ID_TO_ELEMENT.items()}
    return [inv[e] for e in entry.get("attrs") or [] if e in inv]


def ailment_resist_chance(buffs: list[dict], ailment: str) -> int:
    """Percent-point ailment resistance from resist_up buffs (basis points)."""
    total = 0
    for buff in buffs or []:
        if buff.get("kind") != "resist_up":
            continue
        target = buff.get("ailment")
        if target in (None, "all", ailment):
            total += int(buff.get("value", 0) or 0)
    return total // 100


def has_ailment(member: dict, ailment: str) -> bool:
    return any(buff.get("kind") == "ailment" and buff.get("ailment") == ailment
               for buff in member.get("buffs", []))


def ailment_application_chance(sim: "BattleSim", actor: dict, target: dict,
                               ailment: str, rate: int) -> int:
    for buff in target.get("buffs", []):
        if buff.get("kind") == "ailment_immune":
            return 0
    ctx = mod_context(sim, actor, target, None)
    if any(m.get("code") == "ailment_immune" and conds_pass(m.get("conds"), ctx)
           for m in target.get("mods", [])):
        return 0
    chance = int(rate or 100)
    chance += sum_slot_mods(actor.get("mods", []), {"ailment_rate"}, ctx) // 100
    chance -= ailment_resist_chance(target.get("buffs", []), ailment)
    return max(min(chance, 100), 0)


def buff_resist_bonus(buffs: list[dict], elements: list[str]) -> int:
    """Extra integer resistance from resist_up buffs (empty: none mapped)."""
    return 0


def eff_speed(member: dict) -> int:
    """Battle speed with temporary speed buffs (panel 53 style)."""
    total = 0
    for buff in member.get("buffs", []):
        if buff.get("kind") == "speed":
            total += int(buff.get("value", 0) or 0)
    return max(int(int(member.get("speed", 0) or 0) * (1 + total / 10000)), 1)


def panel_skill_damage_mult(panel_id: int | None) -> float:
    if panel_id is None:
        return 1.0
    return PANEL_SKILL_DMG.get(panel_id, 1.0)


def panel_for_turn(game_dir: Path, battle_id: int, turn: int) -> int | None:
    # Panel schedules are fixed per battle: the master battle row lists panel
    # ids in turn order (e.g. [11, 12, 13, 14]), cycled each turn. Captured
    # starts across 518 battles match per-battle lists, not random placement.
    # Battles with no panel list keep the old deterministic hash (estimated).
    try:
        panels = battle_table(game_dir, "battle").get(str(battle_id), {}).get("panels") or []
    except (OSError, ValueError):
        panels = []
    if panels:
        return panels[max(int(turn) - 1, 0) % len(panels)]
    slot = (battle_id * 31 + turn * 17) % 10
    return {0: 13, 2: 12, 5: 14, 7: 30, 9: 17}.get(slot)


def panel_outgoing_mult(panel_id: int | None) -> float:
    if panel_id is None:
        return 1.0
    return PANEL_OUTGOING.get(panel_id, 1.0)


class BattleSim:
    """Server-side battle state machine (approximate)."""

    def __init__(
        self,
        game_dir: Path,
        kind: str,
        ref_id: int,
        party_number: int,
        party_members: list[dict],
        battle_id: int,
        wave_ids: list[int],
        panels: list[int],
        countdown: int | None,
        quest: dict | None,
        seed: int | None = None,
        profile_plaintext: bytes = b"",
    ):
        self.game_dir = game_dir
        self.kind = kind
        self.ref_id = ref_id
        self.party_number = party_number
        self.battle_id = battle_id
        self.wave_ids = wave_ids
        self.panels = panels
        self.countdown = countdown
        self.quest = quest or {}
        self.rng = random.Random(seed)
        self.members: dict[int, dict] = {}
        self.order: list[tuple[int, int]] = []
        self.enemy_groups: dict[int, int] = {}
        self.turn = 1
        self.total_turn = 1
        self.request_count = 0
        self.action_no = 0
        self.setup_no = 0
        self.setups: list[bytes] = []
        self.actions: list[bytes] = []
        self.wave_starts: list[bytes] = []
        # High-water marks: how many wave starts, setups, and actions have
        # already been sent to the client. Attack responses are incremental
        # (captured histories carry only new entries, not full replays).
        self.sent_waves = 0
        self.sent_setups = 0
        self.sent_actions = 0
        self.wave_index = 0
        self.party_gauge = GAUGE_START
        self.status = 0
        self.start_txid = str(uuid.uuid4())
        self.max_dealt = 0
        self.total_dealt_hp_damage = 0
        self.received = 0
        self.deaths = 0
        self.previous_state: bytes | None = None
        self.previous_formation: bytes | None = None
        self.start_state: bytes | None = None
        self.tools: list[dict] = []
        self.cannons: list[dict] = []
        self.command_actor_id: int | None = None
        self.extra_turns_total = 0
        self.trigger_depth = 0
        self.staged_party_mods: list[dict] = []
        self.opening_damage_capped = False
        self.auto = False
        self.profile_plaintext = profile_plaintext
        self.field_effect: int | None = None
        self.finish_bundle: dict = {}
        self.leader_master: dict = {}
        for entry in party_members:
            if entry.get("leader"):
                self.leader_master = entry.get("master") or {}
                break
        for position, entry in enumerate(party_members, 1):
            self.add_ally(position, entry)
        for member in self.members.values():
            if member["side"] == 0:
                member["mods"].extend(self.staged_party_mods)
        self.staged_party_mods = []
        for member in self.members.values():
            if member["side"] == 0:
                fire_triggers(self, "battle_start", member, {})
        self.start_wave(0)
        self.order = self.initial_order()
        self.turn = 2

    def initial_order(self) -> list[tuple[int, int]]:
        """Wait-based initial order: floor(57600/speed) + skill-2 wait.

        Ties break left to right (member id order); enemies use a zero
        master wait since enemy skill waits are not in master data.
        """
        skills = battle_table(self.game_dir, "skill")
        keyed = []
        for member in self.members.values():
            if not member["alive"]:
                continue
            if member["side"] == 0:
                skill_id = (member.get("skills") or {}).get(2, 0)
                master_wait = int(skills.get(str(skill_id), {}).get("wait", 0) or 0)
            else:
                master_wait = 0
            wait_value = effective_wait(eff_speed(member), master_wait)
            pioneer = bool(member.get("pioneer")) and member["side"] == 0
            keyed.append((not pioneer, wait_value, member["id"]))
        keyed.sort()
        return [(member_id, 1) for _, _, member_id in keyed]

    # -- setup ---------------------------------------------------------
    def add_ally(self, position: int, entry: dict) -> None:
        record = entry["record"]
        master = entry["master"]
        stats = entry["stats"]
        member_id = position
        skills = skill_ids_for_character(record, master)
        skill_table = battle_table(self.game_dir, "skill")
        skill_lamps = {}
        for skill_type, skill_id in skills.items():
            if skill_id:
                lamp = int(skill_table.get(str(skill_id), {}).get("lamp", 0) or 0)
                if lamp > 0:
                    skill_lamps[skill_type] = lamp
        active_skills = active_skill_ids_for_character(master)
        active_rest = {}
        for active_type, active_id in active_skills.items():
            limit = int(skill_table.get(str(active_id), {}).get("limit", 0) or 0)
            if limit > 0:
                active_rest[active_type] = limit
        extra_skill = extra_skill_for_character(master, max(varint_field(record, 9, 1), 1))
        rank2 = max(varint_field(record, 9, 1), 1)
        mods: list[dict] = []
        staged_party: list[dict] = []
        triggers: list[dict] = []
        for equipped in entry.get("equipment", []):
            mods.extend(trait_mods(self.game_dir, entry.get("equipment_trait_rows") or {}, equipped.get("traits") or []))
        own, party, trigs = ability_parsed_parts(
            self.game_dir, (entry.get("memoria_ability_ids") or []) + (entry.get("character_ability_ids") or []))
        mods.extend(own)
        staged_party.extend(party)
        triggers.extend(trigs)
        leader_mods, leader_trigs = leader_mods_for_member(self.game_dir, self.leader_master, entry)
        mods.extend(leader_mods)
        triggers.extend(leader_trigs)
        self.staged_party_mods.extend(staged_party)
        start_stats = apply_start_stat_mods(stats, mods, start_mod_context(entry))
        start_stats = apply_start_stat_mods(
            start_stats,
            research_start_mods(self.game_dir, self.profile_plaintext, entry), start_mod_context(entry))
        emblem_stats, emblem_combat = emblem_start_mods(self.game_dir, self.profile_plaintext, entry)
        start_stats = apply_start_stat_mods(start_stats, emblem_stats, start_mod_context(entry))
        mods.extend(emblem_combat)
        burst_stocks = max(
            [int(m.get("stocks", 1) or 1) for m in mods if m.get("code") == "burst_stocks"] + [1]
        )
        start_res = dict(master.get("resistance", {}) or {})
        for mod in mods:
            if mod.get("code") != "resist_up" or mod.get("conds"):
                continue
            for attr in mod.get("attrs", []):
                start_res[attr] = int(start_res.get(attr, 0) or 0) + int(mod.get("value", 0) or 0) // 100
        self.members[member_id] = {
            "id": member_id,
            "side": 0,
            "character_id": entry["character_id"],
            "level": entry.get("level", 1),
            "role": entry.get("role"),
            "attrs": entry.get("attrs") or [],
            "tags": entry.get("tags") or [],
            "hp": entry.get("hp") or start_stats["hp"],
            "max_hp": entry.get("hp") or start_stats["hp"],
            "alive": True,
            "speed": start_stats["speed"],
            "attack": start_stats["attack"],
            "magic": start_stats["magic"],
            "defense": start_stats["defense"],
            "mental": start_stats["mental"],
            "res": start_res,
            "skills": skills,
            "skill_lamps": skill_lamps,
            "skill_rank2": rank2,
            "active_skills": active_skills,
            "active_rest": active_rest,
            "extra_skill": extra_skill,
            "burst_gauge": 0,
            "burst_max": 100 * burst_stocks,
            "leader": bool(entry.get("leader")),
            "buffs": [],
            "mods": mods,
            "triggers": triggers,
            "trigger_uses": {},
            "lamp_lit": {},
            "lamp_bonus": collect_lamp_bonus(triggers, rank2),
            "pioneer": any(m.get("code") == "pioneer" for m in mods),
            "range": "in",
            "transformed": False,
            "abilities": entry.get("abilities", []),
            "stun": False,
            "broken": False,
        }

    def start_wave(self, wave_index: int) -> None:
        wave = battle_table(self.game_dir, "wave")[str(self.wave_ids[wave_index])]
        self.wave_index = wave_index
        self.field_effect = wave.get("field")
        enemy_ids = []
        enemy_table = battle_table(self.game_dir, "enemy")
        enemy_rows = []
        group_counts: dict[int, int] = {}
        for foe in wave.get("enemies") or []:
            master = enemy_table.get(str(foe["id"]), {})
            base_enemy_id = int(master.get("base_enemy_id") or foe["id"])
            enemy_rows.append((foe, master, base_enemy_id))
            group_counts[base_enemy_id] = group_counts.get(base_enemy_id, 0) + 1
        self.enemy_groups = group_counts
        group_numbers: dict[int, int] = {}
        for offset, (foe, master, base_enemy_id) in enumerate(enemy_rows):
            member_id = 11 + offset
            level = int(foe.get("level") or 1)
            computed = enemy_battle_stats(master, level)
            stats = computed["stats"]
            group_numbers[base_enemy_id] = group_numbers.get(base_enemy_id, 0) + 1
            self.members[member_id] = {
                "id": member_id,
                "side": 1,
                "enemy_id": int(foe["id"]),
                "base_enemy_id": base_enemy_id,
                "base_enemy_number": (
                    group_numbers[base_enemy_id] if group_counts[base_enemy_id] > 1 else None
                ),
                "level": level,
                "hp": stats["hp"],
                "max_hp": stats["hp"],
                "alive": True,
                "speed": stats["speed"],
                "attack": stats["attack"],
                "magic": stats["attack"],
                "defense": stats["defense"],
                "mental": stats["defense"],
                "res": dict(master.get("res", {}) or {}),
                "ai": list(
                    battle_table(self.game_dir, "enemy_ai").get(str(master.get("ai")), [])
                ),
                "ai_cursor": 0,
                "burst": master.get("burst"),
                "burst_cd": 0,
                "boss": bool(master.get("boss")),
                "buffs": [],
                "break_max": computed["break_max"],
                "break_cur": computed["break_max"],
                "broken": False,
                "stun": False,
                "base_num": offset + 1,
            }
            enemy_ids.append(member_id)
        for member_id in enemy_ids:
            self.order.append((member_id, self.turn))
            self.turn += 1
        for member in self.members.values():
            if member["side"] == 0 and member.get("alive"):
                fire_triggers(self, "wave_start", member, {})

    # -- accessors -----------------------------------------------------
    def alive_allies(self) -> list[dict]:
        return [m for m in self.members.values() if m["side"] == 0 and m["alive"]]

    def alive_foes(self) -> list[dict]:
        return [m for m in self.members.values() if m["side"] == 1 and m["alive"]]

    def current_actor(self) -> dict | None:
        for member_id, _ in self.order:
            member = self.members.get(member_id)
            if member is not None and member["alive"] and member["side"] == 0 and not member["stun"]:
                return member
        for member_id, _ in self.order:
            member = self.members.get(member_id)
            if member is not None and member["alive"] and member["side"] == 0:
                return member
        return None

def skill_ids_for_character(record: bytes, master: dict) -> dict[int, int]:
    """Skill id per skill_type from profile ranks and evolve flags.

    skill_type 1 normal1, 2 normal2, 3 burst. Normal ranks come from
    profile fields 8/9 (1-based index into the 5-entry tables). Burst
    follows rarity: the 7-entry tables hold the same id three times for
    rarity 1-3, then one id per rarity 4/5/6/7, so index rarity-1 (capped).
    Season2 captures confirm rarity 7 uses the last entry.
    """
    normal1 = master.get("normal1_skill_ids") or []
    normal2 = master.get("normal2_skill_ids") or []
    burst = master.get("burst_skill_ids") or []
    evolved1 = master.get("evolved_normal1_skill_ids") or []
    evolved2 = master.get("evolved_normal2_skill_ids") or []
    evolved_burst = master.get("evolved_burst_skill_ids") or []
    rank1 = max(varint_field(record, 8, 1), 1)
    rank2 = max(varint_field(record, 9, 1), 1)
    rarity = max(varint_field(record, 11, 1), 1)
    use_evolved = bool(varint_field(record, 33, 0))
    table1 = evolved1 if (use_evolved and evolved1) else normal1
    table2 = evolved2 if (use_evolved and evolved2) else normal2
    table3 = evolved_burst if (use_evolved and evolved_burst) else burst
    burst_index = min(max(rarity - 1, 0), len(table3) - 1) if table3 else 0
    return {
        1: table1[min(rank1, len(table1)) - 1] if table1 else 0,
        2: table2[min(rank2, len(table2)) - 1] if table2 else 0,
        3: table3[burst_index] if table3 else 0,
    }


def extra_skill_for_character(master: dict, rank2: int) -> int:
    """Extra-turn skill id replacing skill 2 on an extra turn.

    Five-entry tables are rank-indexed like normal2; eleven-entry tables
    (a 14-series head plus 11/12 rank ladders) pick the ladder matching
    the character's normal2 id prefix; shorter tables are rank-indexed
    with capping. Returns 0 when the character has no extra skills.
    """
    entries = list(master.get("extra_skill_ids") or [])
    if not entries:
        return 0
    normal2 = master.get("normal2_skill_ids") or []
    prefix = str(normal2[0])[:2] if normal2 else ""
    pool = [e for e in entries if prefix and str(e).startswith(prefix)] or entries
    if len(pool) > 5:
        pool = pool[:5]
    return pool[min(max(rank2, 1), len(pool)) - 1]


def active_skill_ids_for_character(master: dict) -> dict[int, int]:
    """Active skill id per 1-based slot from the progression character master.

    Slots with null ids are omitted (e.g. Totori 26904 carries only
    active1_skill_id 14002908). Rest counts come from skill.master limits.
    """
    out = {}
    for slot in (1, 2, 3):
        skill_id = master.get(f"active{slot}_skill_id")
        if skill_id:
            out[slot] = int(skill_id)
    return out


def skill_targets(skill: dict, actor: dict, sim: "BattleSim", main_target: int | None) -> list[dict]:
    target_type = int(skill.get("target") or 0)
    allies = sim.alive_allies()
    foes = sim.alive_foes()
    own_side = allies if actor["side"] == 0 else foes
    opposing_side = foes if actor["side"] == 0 else allies
    if target_type == 1:
        return [actor] if actor.get("alive", True) else []
    if target_type == 2:
        pool = own_side
    elif target_type == 3:
        pool = opposing_side
    elif target_type == 4:
        return list(own_side)
    elif target_type == 5:
        return list(opposing_side)
    else:
        pool = own_side if skill.get("effect") == 2 else opposing_side
    if not pool:
        return []
    if main_target is not None:
        chosen = next((m for m in pool if m["id"] == main_target), None)
        if chosen is not None:
            return [chosen]
    fixed = fixed_skill_target(sim, skill, pool, opposing_side)
    if fixed is not None:
        return [fixed]
    if skill.get("effect") == 2:
        wounded = [m for m in pool if m["hp"] < m["max_hp"]]
        if wounded:
            return [min(wounded, key=lambda m: (m["hp"] / max(m["max_hp"], 1), sim_turn_index(sim, m["id"])))]
    taunter = next((m for m in pool if has_ailment(m, "taunt")), None)
    if taunter is not None and target_type in (2, 3):
        # Taunt fixes single-target selection. Fixed item/forced targeting
        # above already overrides it, matching captures.
        return [taunter]
    if target_type == 3 and actor["side"] == 1:
        return [aggro_pick(sim, pool)]
    return [pool[0]]


def sim_turn_index(sim: "BattleSim", member_id: int) -> int:
    """Timeline position for tie-breaks (nearest next turn wins)."""
    for index, (mid, _) in enumerate(sim.order):
        if mid == member_id:
            return index
    return len(sim.order)


def fixed_skill_target(sim: "BattleSim", skill: dict, pool: list[dict], opposing: list[dict]) -> dict | None:
    """Fixed targeting from skill-effect tags (e.g. highest max-HP ally).

    Single-target battle items carry fixed conditions that override taunt
    and cannot be manually selected.
    """
    for effect in skill.get("effects") or []:
        parsed = parsed_effect(sim.game_dir, int(effect.get("id", 0) or 0))
        target = parsed.get("target") or "context"
        if target == "extreme_ally_maxhp":
            return max(pool, key=lambda member: member.get("max_hp", 0))
        if target == "extreme_enemy_hp_max":
            candidates = opposing or pool
            return max(candidates, key=lambda member: member.get("hp", 0))
        if target == "extreme_ally_patk_max":
            return max(pool, key=lambda member: member.get("attack", 0))
        if target == "extreme_ally_matk_max":
            return max(pool, key=lambda member: member.get("magic", 0))
        if target == "extreme_ally_hp_min":
            wounded = [m for m in pool if m["hp"] < m["max_hp"]] or pool
            return min(wounded, key=lambda member: (member["hp"], sim_turn_index(sim, member["id"])))
    if any(
        int(effect.get("id", 0) or 0) in (6001150, 6001151)
        for effect in skill.get("effects") or []
    ):
        return max(pool, key=lambda member: member.get("max_hp", 0))
    return None


def aggro_pick(sim: "BattleSim", pool: list[dict]) -> dict:
    """Enemy single-target choice. Defenders draw attacks; targeted and
    random-flagged actions ignore aggro (handled by callers)."""
    weights = []
    for member in pool:
        weight = 1.0 + float(member.get("aggro", 0) or 0)
        if member.get("role") == 3:
            weight += 2.0
        if any(m.get("code") == "aggro" for m in member.get("mods", [])):
            weight += 2.0
        weights.append(weight)
    total = sum(weights)
    roll = sim.rng.uniform(0, total)
    for member, weight in zip(pool, weights):
        roll -= weight
        if roll <= 0:
            return member
    return pool[-1]


def preview_targets(skill: dict, actor: dict, sim: "BattleSim") -> list[dict]:
    """All selectable targets for setup previews.

    Captured single-target selections list every living candidate (e.g.
    all 3 foes for target 3), not just the auto-battle pick. Actual
    resolution still uses skill_targets with the chosen main_target.
    """
    target_type = int(skill.get("target") or 0)
    allies = sim.alive_allies()
    foes = sim.alive_foes()
    own_side = allies if actor["side"] == 0 else foes
    opposing_side = foes if actor["side"] == 0 else allies
    if target_type == 1:
        return [actor] if actor.get("alive", True) else []
    if target_type == 2:
        return list(own_side)
    if target_type == 3:
        return list(opposing_side)
    if target_type == 4:
        return list(own_side)
    if target_type == 5:
        return list(opposing_side)
    return list(own_side if skill.get("effect") == 2 else opposing_side)


def apply_skill_effects(
    sim: "BattleSim", actor: dict, skill: dict, targets: list[dict]
) -> list[dict]:
    """Apply modeled state effects and return their captured result records.

    Only effects whose id exists in the state-change master are recorded
    as member buffs (field 14): the client resolves buff icons by state id
    and crashes on unknown ids (seen live as a StateChangeIcon NRE that
    softlocks the battle). Captured tool/cannon effect ids (6001150 and
    friends) keep their combat multipliers as hidden buffs; effect results
    (field 11) are still emitted for every effect as in captures.

    Buff amounts granted here scale with the giver's potency (given plus
    for enhancements, given minus for weakenings) and the target's
    received potency, matching the community amount rules. Granted
    effects use the amount at grant time; passive owner modifiers are
    separate and immune to buff wipes.
    """
    results: list[dict] = []
    states = battle_table(sim.game_dir, "state_change")
    moved = False
    for effect in skill.get("effects") or []:
        effect_id = int(effect.get("id", 0) or 0)
        value = int(effect.get("value", 0) or 0)
        if not effect_id:
            continue
        parsed = parsed_effect(sim.game_dir, effect_id)
        info = states.get(str(effect_id))
        if parsed.get("code") in ("turn_swap", "turn_erase"):
            # Skills like Totori 14002908 carry two swap entries for one
            # logical swap; applying both would cancel out.
            if moved:
                continue
            moved = True
        for target in targets:
            dealt_state = None
            if effect_id in (6001150, 6001151):
                # These captured Battle Tool effects increase the target's
                # physical/magical defense for two hits.
                target["buffs"].append(
                    {
                        "id": effect_id,
                        "value": -value,
                        "rest": 2,
                        "kind": "taken",
                        "display": False,
                    }
                )
            elif effect_id == 6001256:
                target["buffs"].append(
                    {
                        "id": effect_id,
                        "value": value,
                        "rest": 2,
                        "kind": "out",
                        "display": False,
                    }
                )
            elif info is not None:
                dealt_state = grant_state_buff(sim, actor, target, effect_id, value, parsed)
            elif parsed.get("code") in ("skill_damage", "dealt_damage", "skill_power",
                                        "crit_rate", "crit_damage", "break_damage",
                                        "taken_break", "taken_crit_damage", "penetration",
                                        "taken_damage", "burst_damage", "heal_given",
                                        "heal_received", "ailment", "resist_up",
                                        "resist_down", "target_debuff"):
                dealt_state = grant_parsed_slot_buff(sim, actor, target, value, parsed)
            else:
                apply_parsed_skill_effect(sim, actor, targets, effect_id, value, parsed)
            # All other effect ids (item gauge, crit lamp, unmodeled
            # traits) apply no combat buff and must never reach field 14.
            results.append(
                {
                    "effector": actor["id"],
                    "target": target["id"],
                    "effect_id": effect_id,
                    "value": value,
                    "rest": 2,
                    "is_skill": True,
                    "dealt_state_change": dealt_state,
                }
            )
    return results


SLOT_BUFF_KINDS = {
    "skill_damage": "skill_damage", "dealt_damage": "skill_damage",
    "skill_power": "skill_power", "crit_rate": "crit_rate",
    "crit_damage": "crit_damage", "break_damage": "break_damage",
    "taken_break": "taken_break", "taken_crit_damage": "taken_crit_damage",
    "penetration": "penetration", "taken_damage": "taken",
    "burst_damage": "burst_damage", "heal_given": "recovery_given",
    "heal_received": "recovery_received", "resist_up": "resist_up",
    "resist_down": "resist_down", "pre_resist_down_target": "resist_down",
}


def grant_parsed_slot_buff(sim: "BattleSim", actor: dict, target: dict,
                           value: int, parsed: dict) -> dict | None:
    """Grant a hidden slot buff from a mapped skill effect.

    Foe-flagged effects land on enemy targets, everything else on the
    acting member. Ailments roll application; amounts scale with potency.
    """
    code = parsed.get("code")
    if code == "ailment":
        ailment = parsed.get("ailment", "unknown")
        chance = ailment_application_chance(
            sim, actor, target, ailment, int(parsed.get("rate", 100) or 100))
        if sim.rng.randint(1, 100) > chance:
            return None
        buff = {"id": 0, "value": int(value or 0), "rest": 2, "kind": "ailment",
                "ailment": ailment, "display": False}
    else:
        if code == "target_debuff":
            kind = parsed.get("slot", "skill_damage")
            if kind not in ("skill_damage", "out", "defense", "speed", "taken"):
                return None
        else:
            kind = SLOT_BUFF_KINDS.get(code)
            if kind is None:
                return None
        rate = int(parsed.get("rate", 100) or 100)
        if rate < 100 and sim.rng.randint(1, 100) > rate:
            return None
        magnitude = effect_magnitude(parsed, value)
        magnitude = apply_potency(actor, target, kind if kind in ("taken",) else "out", magnitude)
        buff = {"id": 0, "value": direction_sign(parsed) * magnitude, "rest": 2,
                "kind": kind, "display": False}
        if kind == "resist_up":
            buff["ailment"] = parsed.get("ailment")
        if kind == "resist_down":
            buff["attr"] = parsed.get("attr", "unknown")
    owner = target if parsed.get("foe") else actor
    if not owner.get("alive"):
        return None
    dur_actions = int(parsed.get("dur_actions", 0) or 0)
    dur_hits = int(parsed.get("dur_hits", 0) or 0)
    if dur_actions:
        buff["rest"] = dur_actions
    if dur_hits:
        buff["hits"] = dur_hits
    owner["buffs"].append(buff)
    return buff if buff.get("id") else None


def direction_sign(parsed: dict) -> int:
    return int(parsed.get("direction", 1) or 1)


def grant_state_buff(sim: "BattleSim", actor: dict, target: dict, state_id: int,
                     value: int, parsed: dict | None = None) -> dict | None:
    """Grant one state-table buff with potency, duration, and ailment rolls.

    Returns the granted buff dict for effect-result linkage, or None when
    the application roll fails (ailments) or the state is unknown.
    """
    kind_info = state_kind(sim.game_dir, state_id)
    kind = kind_info.get("kind", "special")
    if kind in ("special", "dummy", "counter_state"):
        return None
    parsed = parsed if parsed is not None else parsed_effect(sim.game_dir, state_id)
    rate = int(parsed.get("rate", 100) or 100)
    if kind == "ailment":
        ailment = kind_info.get("ailment", "unknown")
        chance = ailment_application_chance(sim, actor, target, ailment, rate)
        if sim.rng.randint(1, 100) > chance:
            return None
    magnitude = effect_magnitude(parsed, value)
    magnitude = apply_potency(actor, target, kind, magnitude)
    buff: dict = {
        "id": state_id,
        "value": magnitude,
        "rest": 2,
        "kind": kind,
        "display": True,
    }
    if kind == "ailment":
        buff["ailment"] = kind_info.get("ailment", "unknown")
    if kind == "resist_up":
        buff["ailment"] = kind_info.get("ailment")
    if kind == "reflect":
        buff["reflect"] = kind_info.get("reflect", "any")
    dur_actions = int(parsed.get("dur_actions", 0) or 0)
    dur_hits = int(parsed.get("dur_hits", 0) or 0)
    if dur_actions:
        buff["rest"] = dur_actions
    if dur_hits:
        buff["hits"] = dur_hits
    if parsed.get("perm"):
        buff["rest"] = None
    cap = int(parsed.get("cap", 0) or 0)
    if cap:
        buff["cap"] = cap
    target["buffs"].append(buff)
    return buff


def apply_potency(actor: dict, target: dict, kind: str, value: int) -> int:
    """Scale a granted buff amount by giver/receiver potency modifiers."""
    actor_mods = actor.get("mods", []) if isinstance(actor, dict) else []
    target_mods = target.get("mods", []) if isinstance(target, dict) else []
    given_plus = sum_slot_mods(actor_mods, {"potency_given_plus"}, {}) // 100
    given_minus = sum_slot_mods(actor_mods, {"potency_given_minus"}, {}) // 100
    received = sum_slot_mods(target_mods, {"potency_received"}, {}) // 100
    if kind in ("out", "regen", "barrier", "evade", "heal"):
        factor = 1.0 + given_plus / 100 + received / 100
    elif kind in ("taken", "ailment", "ailment_dot"):
        factor = 1.0 + given_minus / 100 + received / 100
    else:
        factor = 1.0
    return int(value * factor)


def apply_parsed_skill_effect(sim: "BattleSim", actor: dict, targets: list[dict],
                              effect_id: int, value: int, parsed: dict) -> None:
    """Structured skill effects without state-table ids: timeline moves,
    gauge heals, break restoration, field changes, and cleanses."""
    code = parsed.get("code")
    if code == "turn_swap" and targets:
        swap_order_positions(sim, actor["id"], targets[0]["id"])
    elif code == "turn_erase" and targets:
        erase_order_entry(sim, targets[0]["id"])
    elif code == "delay_turn":
        for target in targets:
            shift_order(sim, target["id"], +2)
    elif code == "hasten_turn":
        for target in targets:
            shift_order(sim, target["id"], -1)
    elif code == "item_gauge":
        sim.party_gauge = min(sim.party_gauge + int(GAUGE_MAX * pct_heal_fraction(value)), GAUGE_MAX)
    elif code == "burst_gauge":
        actor["burst_gauge"] = min(int(actor.get("burst_gauge", 0) or 0) + int(pct_heal_fraction(value) * BURST_GAUGE_MAX), BURST_GAUGE_MAX)
    elif code == "break_gauge_heal":
        for target in targets:
            if target["side"] == 1:
                target["break_cur"] = min(target.get("break_cur", 0) + max(int(value or 0), 0), target.get("break_max", 0))
    elif code == "field" and parsed.get("field_effect_id"):
        sim.field_effect = int(parsed["field_effect_id"])
    elif code == "cleanse":
        for target in targets:
            remove_debuffs(target)
    elif code == "dispel":
        kind = parsed.get("dispel", "")
        ailment = parsed.get("ailment")
        for target in targets:
            target["buffs"] = [b for b in target.get("buffs", [])
                               if b.get("kind") != kind
                               and not (ailment and b.get("ailment") == ailment)]


def shift_order(sim: "BattleSim", member_id: int, steps: int) -> bool:
    """Shift a member along the timeline (positive delays)."""
    index = next((i for i, (mid, _) in enumerate(sim.order) if mid == member_id), None)
    if index is None:
        return False
    entry = sim.order.pop(index)
    sim.order.insert(min(max(index + steps, 0), len(sim.order)), entry)
    return True


def tick_buffs(member: dict) -> None:
    kept = []
    for buff in member.get("buffs", []):
        rest = buff.get("rest", 1)
        if rest is None:
            kept.append(buff)
            continue
        rest = int(rest) - 1
        if rest > 0:
            buff["rest"] = rest
            kept.append(buff)
    member["buffs"] = kept


def tick_hit_buffs(member: dict) -> None:
    """Consume use-limited (N hits taken) buffs after the owner takes a hit."""
    kept = []
    for buff in member.get("buffs", []):
        hits = buff.get("hits")
        if hits is None:
            kept.append(buff)
            continue
        hits = int(hits) - 1
        if hits > 0:
            buff["hits"] = hits
            kept.append(buff)
    member["buffs"] = kept


def remove_ailments(member: dict, ailments: set[str] | None = None) -> int:
    """Cleanse ailment (and optionally taken) buffs. Returns removed count."""
    kept = []
    removed = 0
    for buff in member.get("buffs", []):
        if buff.get("kind") == "ailment" and (
            ailments is None or buff.get("ailment") in ailments
        ):
            removed += 1
            continue
        kept.append(buff)
    member["buffs"] = kept
    return removed


def resolve_attack_local_mods(sim: "BattleSim", actor: dict, skill_id: int) -> list[dict]:
    """Confirmed per-skill behaviors from combat_map skill_behavior."""
    return cmap_skill_behavior(sim.game_dir).get(str(skill_id), [])


def action_fail_roll(sim: "BattleSim", actor: dict) -> str | None:
    """Turn-start action failure: stun, sleep, or paralysis (20%)."""
    if not actor.get("alive"):
        return "dead"
    if actor.get("stun") or has_ailment(actor, "stun"):
        return "stun"
    if has_ailment(actor, "sleep"):
        return "sleep"
    for buff in actor.get("buffs", []):
        if buff.get("kind") == "ailment" and buff.get("ailment") == "paralysis":
            if sim.rng.randint(1, 100) <= 20:
                return "paralysis"
            break
    return None


def tick_start_of_turn(sim: "BattleSim", member: dict) -> None:
    """Poison/burn/venom damage and regen healing at the owner's turn start."""
    if not member.get("alive"):
        return
    max_hp = max(member.get("max_hp", 1), 1)
    for buff in list(member.get("buffs", [])):
        if buff.get("kind") != "ailment":
            continue
        ailment = buff.get("ailment")
        if ailment == "poison":
            member["hp"] = max(member["hp"] - max(int(max_hp * 0.02), 1), 0)
        elif ailment == "burn":
            member["hp"] = max(member["hp"] - max(int(max_hp * 0.01), 1), 0)
        elif ailment == "venom":
            member["hp"] = 0
    for buff in list(member.get("buffs", [])):
        if buff.get("kind") == "regen":
            heal_member(sim, member, int(max_hp * pct_heal_fraction(buff.get("value", 0))))
    if member["hp"] <= 0 and member["alive"]:
        member["hp"] = 0
        member["alive"] = False
        if member["side"] == 0:
            sim.deaths += 1


def cover_redirect(sim: "BattleSim", actor: dict, target: dict) -> tuple[dict, int | None]:
    """Redirect an enemy single-target hit to a covering ally."""
    if actor["side"] != 1 or target["side"] != 0:
        return target, None
    for member in sim.alive_allies():
        if member["id"] == target["id"]:
            continue
        if any(buff.get("kind") == "cover" for buff in member.get("buffs", [])):
            return member, member["id"]
    return target, None


def apply_hit(
    sim: "BattleSim",
    actor: dict,
    target: dict,
    skill: dict,
    elements: list[str],
    use_magic: bool,
    panel: int | None,
    local: dict,
    ctx_flags: dict,
) -> dict:
    """Resolve one damage hit with miss, barrier, break, and reactions."""
    result: dict = {"target": target["id"]}
    if has_ailment(actor, "darkness"):
        if sim.rng.randint(1, 100) <= 25:
            result["miss"] = True
            return result
    for buff in target.get("buffs", []):
        if buff.get("kind") == "evade":
            chance = buff.get("value", 0)
            chance = chance / 100 if chance > 1000 else chance
            if sim.rng.uniform(0, 100) < chance:
                result["miss"] = True
                return result
            break
    force_crit = panel == 30 or has_ailment(target, "frozen")
    if target["side"] == 0:
        defense_stat = target["mental"] if use_magic else target["defense"]
    else:
        defense_stat = target["defense"]
    defense_stat = max(int(defense_stat * (1 + buff_slot_bonus(target.get("buffs", []), "defense"))), MIN_BATTLE_STAT)
    attack_stat = actor["magic"] if use_magic else actor["attack"]
    broken = bool(target.get("broken"))
    res_value = combined_resistance(elements, target.get("res", {}), target.get("buffs", []), sim, target)
    res_value -= resist_down_bonus(target.get("buffs", []), elements)
    weak = res_value <= WEAK_THRESHOLD
    resist = (not weak) and res_value >= RESIST_THRESHOLD
    ctx = mod_context(sim, actor, target, skill, is_aoe=ctx_flags.get("is_aoe", False),
                      is_item=ctx_flags.get("is_item", False),
                      is_cannon=ctx_flags.get("is_cannon", False),
                      is_burst=ctx_flags.get("is_burst", False), weak=weak)
    slots = damage_slot_mults(sim, actor, target, skill, panel, local, ctx)
    base_crit = ALLY_CRIT_RATE if actor["side"] == 0 else ENEMY_CRIT_RATE
    if ctx_flags.get("is_item"):
        base_crit = ITEM_CRIT_RATE
    crit_rate = base_crit + slots["crit_rate"]
    damage, critical = compute_hit(
        sim.rng,
        skill.get("power", 0),
        attack_stat,
        defense_stat,
        actor.get("level", 1),
        res_value,
        broken,
        force_crit,
        crit_rate,
        slots["skill_damage"],
        slots["skill_power"],
        slots["outgoing"],
        slots["taken"],
        slots["penetration"],
        crit_bonus=slots["crit_damage"],
        taken_crit=slots["taken_crit"],
    )
    ctx["critical"] = critical
    for buff in target.get("buffs", []):
        if buff.get("kind") == "null_damage":
            if damage <= target.get("max_hp", 0) * 0.25:
                result["invalid"] = True
                return result
            break
    barrier_blocked = 0
    for buff in list(target.get("buffs", [])):
        if buff.get("kind") == "barrier":
            absorb = min(int(buff.get("value", 0) or 0), damage)
            buff["value"] = int(buff.get("value", 0) or 0) - absorb
            damage -= absorb
            barrier_blocked += absorb
            result["barrier_damage"] = barrier_blocked
            if buff["value"] <= 0:
                target["buffs"].remove(buff)
                result["barrier_broken"] = True
            break
    target["hp"] -= damage
    tick_hit_buffs(target)
    break_hit = 0
    if target["side"] == 1:
        break_hit = compute_break_hit(
            sim.rng, attack_stat, (skill.get("break", 0) or 0) / 100,
            res_value, slots["break_up"], slots["break_power"],
        )
        target["break_cur"] = target.get("break_cur", 0) - break_hit
        if target["break_cur"] <= 0 and target["alive"]:
            target["broken"] = True
            target["break_cur"] = target.get("break_max", break_hit)
    killed = False
    if target["hp"] <= 0:
        target["hp"] = 0
        target["alive"] = False
        killed = True
        ctx["ko"] = True
        if target["side"] == 0:
            sim.deaths += 1
    else:
        if target["side"] == 0:
            sim.received += damage
        for buff in target.get("buffs", []):
            if buff.get("kind") == "counter":
                result.setdefault("effects", []).append(
                    {"effector": target["id"], "target": actor["id"],
                     "effect_id": buff.get("id", 0), "counter": True}
                )
    if target["side"] == 1:
        sim.max_dealt = max(sim.max_dealt, damage)
        sim.total_dealt_hp_damage += damage
    reflect = reflect_percent(target.get("buffs", []), use_magic)
    if reflect and damage > 0 and actor.get("alive"):
        reflected = max(int(damage * reflect / 100), 0)
        if reflected:
            actor["hp"] = max(actor["hp"] - reflected, 0)
            result["reflected"] = reflected
            if actor["hp"] <= 0 and actor["alive"]:
                actor["alive"] = False
                if actor["side"] == 0:
                    sim.deaths += 1
    drain_pct = slots["drain"]
    if drain_pct and damage > 0 and actor.get("alive"):
        actor["hp"] = min(actor["hp"] + int(damage * drain_pct / 100), actor.get("max_hp", actor["hp"]))
    for buff in target.get("buffs", []):
        if buff.get("kind") == "reactive_heal":
            heal_member(sim, target, int(target.get("max_hp", 0) * pct_heal_fraction(buff.get("value", 0))))
            break
    if damage > 0 and target.get("alive"):
        for mod in actor.get("mods", []):
            if mod.get("code") != "on_hit_resist":
                continue
            if not conds_pass(mod.get("conds"), ctx):
                continue
            grant = {"id": 0, "value": int(mod.get("value", 0) or 0), "rest": 2,
                     "kind": "resist_elem", "attr": mod.get("attr", "unknown"), "display": False}
            if int(mod.get("dur_hits", 0) or 0):
                grant["hits"] = int(mod["dur_hits"])
            target["buffs"].append(grant)
        for mod in actor.get("mods", []):
            if mod.get("code") != "resist_down":
                continue
            if not conds_pass(mod.get("conds"), ctx):
                continue
            target["buffs"].append({"id": 0, "value": int(mod.get("value", 0) or 0), "rest": 2,
                                    "kind": "resist_down", "attr": mod.get("attr", "unknown"),
                                    "display": False})
        for mod in actor.get("mods", []):
            if mod.get("code") not in ("target_debuff", "taken_break", "taken_crit_damage"):
                continue
            if not mod.get("foe"):
                continue
            if not conds_pass(mod.get("conds"), ctx):
                continue
            kind = {"target_debuff": mod.get("slot", "skill_damage")}.get(mod.get("code"), mod.get("code"))
            if kind not in ("skill_damage", "out", "defense", "speed", "taken",
                            "taken_break", "taken_crit_damage"):
                continue
            value = int(mod.get("direction", -1) or -1) * abs(int(mod.get("value", 0) or 0))
            target["buffs"].append({"id": 0, "value": value, "rest": 2,
                                    "kind": kind, "display": False})
    if has_ailment(target, "sleep"):
        remove_ailments(target, {"sleep"})
    if target["side"] == 0 and damage > 0:
        fire_triggers(sim, "attacked", target, {"attacker_member": actor})
    result.update(
        {
            "damage": damage,
            "break": break_hit,
            "break_type": 2 if target.get("broken") and break_hit else 0,
            "weak": weak,
            "resist": resist,
            "critical": critical,
            "critical_damage": (
                damage if critical else max(int(damage * (CRIT_MULT + slots["crit_damage"])), 0)
            ),
            "damage_rate": DAMAGE_RESULT_RATE,
            "killed": killed,
        }
    )
    return result


def resist_down_bonus(buffs: list[dict], elements: list[str]) -> int:
    total = 0
    for buff in buffs or []:
        if buff.get("kind") != "resist_down":
            continue
        attr = buff.get("ailment") or buff.get("attr")
        if attr in (None, "all", "unknown") or attr in elements:
            total += int(buff.get("value", 0) or 0) // 100
    return total


def reflect_percent(buffs: list[dict], use_magic: bool) -> int:
    for buff in buffs or []:
        if buff.get("kind") != "reflect":
            continue
        which = buff.get("reflect", "any")
        if which == "any" or (which == "magic" and use_magic) or (which == "phys" and not use_magic):
            value = int(buff.get("value", 0) or 0)
            return value if value <= 100 else value // 100
    return 0


def buff_slot_bonus(buffs: list[dict], kind: str) -> float:
    """Additive slot bonus from synthetic panel/trigger buffs of that kind.

    Only id-less buffs count here; state-table buffs keep flowing through
    the legacy readers so nothing is double-counted.
    """
    total = 0
    for buff in buffs or []:
        if buff.get("kind") == kind and not buff.get("id"):
            total += int(buff.get("value", 0) or 0)
    return total / 10000


def damage_slot_mults(sim: "BattleSim", actor: dict, target: dict, skill: dict,
                      panel: int | None, local: dict, ctx: dict) -> dict:
    """Combine buff, owner-modifier, panel, and attack-local damage slots."""
    actor_mods = actor.get("mods", [])
    target_mods = target.get("mods", [])
    skill_damage = panel_skill_damage_mult(panel)
    skill_damage *= 1 + buff_slot_bonus(actor["buffs"], "skill_damage")
    skill_damage *= 1 + sum_slot_mods(actor_mods, {"skill_damage", "dealt_damage"}, ctx) / 10000
    if ctx.get("is_item"):
        skill_damage *= 1 + sum_slot_mods(actor_mods, {"item_damage"}, ctx, require_item=True) / 10000
    if ctx.get("is_cannon"):
        skill_damage *= 1 + sum_slot_mods(actor_mods, {"cannon_damage"}, ctx, require_cannon=True) / 10000
    skill_id = local.get("skill_id", 0)
    if skill_id:
        skill_damage *= 1 + lamp_damage_bonus(sim.game_dir, actor, skill_id) / 10000
    skill_power = 1 + buff_slot_bonus(actor["buffs"], "skill_power")
    skill_power *= 1 + sum_slot_mods(actor_mods, {"skill_power"}, ctx) / 10000
    outgoing = buff_attack_mult(actor["buffs"]) * panel_outgoing_mult(panel)
    taken = buff_defense_mult(target["buffs"])
    taken *= 1 + sum_slot_mods(target_mods, {"taken_damage"}, ctx) / 10000
    for mod in target_mods:
        if mod.get("code") == "taken_damage" and int(mod.get("direction", 1)) < 0:
            taken *= 1 + int(mod.get("value", 0) or 0) / 10000
    penetration = buff_penetration(actor["buffs"])
    penetration += buff_slot_bonus(actor["buffs"], "penetration")
    penetration += sum_slot_mods(actor_mods, {"penetration"}, ctx) / 10000
    crit_rate = buff_crit_rate_bonus(actor["buffs"])
    crit_rate += buff_slot_bonus(actor["buffs"], "crit_rate")
    crit_rate += sum_slot_mods(actor_mods, {"crit_rate"}, ctx) / 10000
    crit_damage = buff_crit_damage_bonus(actor["buffs"])
    crit_damage += buff_slot_bonus(actor["buffs"], "crit_damage")
    crit_damage += sum_slot_mods(actor_mods, {"crit_damage"}, ctx) / 10000
    if ctx.get("is_item"):
        crit_damage += sum_slot_mods(actor_mods, {"item_crit"}, ctx, require_item=True) / 10000
    if ctx.get("is_cannon"):
        crit_damage += sum_slot_mods(actor_mods, {"cannon_crit"}, ctx, require_cannon=True) / 10000
    break_up = buff_break_damage_bonus(actor["buffs"])
    break_up += buff_slot_bonus(actor["buffs"], "break_damage")
    break_up += buff_slot_bonus(actor["buffs"], "taken_break")
    break_up += sum_slot_mods(actor_mods, {"break_damage", "taken_break"}, ctx) / 10000
    if crit_rate > 1.0:
        excess_caps = [int(m.get("cap", 0) or 0) / 10000
                       for m in actor_mods if m.get("code") == "excess_crit"
                       and conds_pass(m.get("conds"), ctx)]
        if excess_caps:
            move = min(crit_rate - 1.0, max(excess_caps))
            crit_rate -= move
            crit_damage += move
    break_power = buff_break_power_mult(actor["buffs"])
    taken_crit = buff_slot_bonus(target.get("buffs", []), "taken_crit_damage")
    taken_crit += sum_slot_mods(target_mods, {"taken_crit_damage"}, ctx) / 10000
    drain = sum_slot_mods(actor_mods, {"drain"}, ctx) // 100
    for behavior in local.get("behaviors", []):
        code = behavior.get("code")
        value = int(behavior.get("value", 0) or 0)
        if code == "atk_crit_damage":
            crit_damage += value / 10000
        elif code == "atk_crit_rate":
            crit_rate += value / 10000
        elif code == "atk_penetration":
            penetration += value / 10000
        elif code == "weak_break_up" and ctx.get("weak"):
            break_up += value / 10000
        elif code == "weak_dealt_up" and ctx.get("weak"):
            skill_damage *= 1 + value / 10000
        elif code == "scaling_damage" and scaling_cond_pass(behavior, sim, actor, target):
            skill_damage *= 1 + value / 10000
    return {
        "skill_damage": skill_damage, "skill_power": skill_power,
        "outgoing": outgoing, "taken": taken, "penetration": penetration,
        "crit_rate": crit_rate, "crit_damage": crit_damage,
        "taken_crit": taken_crit,
        "break_up": break_up, "break_power": break_power, "drain": drain,
    }


def scaling_cond_pass(behavior: dict, sim: "BattleSim", actor: dict, target: dict) -> bool:
    cond = behavior.get("cond")
    if cond == "hp_high":
        return actor.get("hp", 1) >= actor.get("max_hp", 1) * 0.5
    if cond == "hp_low":
        return actor.get("hp", 1) <= actor.get("max_hp", 1) * 0.5
    if cond == "many_foes":
        return len(sim.alive_foes()) >= 3
    if cond == "few_foes":
        return len(sim.alive_foes()) <= 1
    return False


def apply_post_behaviors(sim: "BattleSim", actor: dict, skill_id: int,
                         targets: list[dict], effect_blobs: list[dict]) -> list[dict]:
    """Post-attack skill behaviors (heals, self/taken buffs, gauge, swap)."""
    extra_results = []
    for behavior in resolve_attack_local_mods(sim, actor, skill_id):
        code = behavior.get("code")
        value = int(behavior.get("value", 0) or 0)
        if code == "post_heal_self":
            heal = heal_member(sim, actor, int(actor.get("max_hp", 0) * pct_heal_fraction(value)))
            extra_results.append({"target": actor["id"], "heal": heal})
        elif code == "post_heal_allies":
            for member in sim.alive_allies():
                heal = heal_member(sim, member, int(member.get("max_hp", 0) * pct_heal_fraction(value)))
                extra_results.append({"target": member["id"], "heal": heal})
        elif code == "post_break_up_self":
            actor["buffs"].append({"id": 0, "value": value, "rest": 2, "kind": "break_up", "display": False})
        elif code == "post_taken_up_target":
            for target in targets:
                if target.get("alive"):
                    target["buffs"].append({"id": 0, "value": value, "rest": 2, "kind": "taken", "display": False})
        elif code == "pre_resist_down_target":
            for target in targets:
                if target.get("alive"):
                    target["buffs"].append({"id": 0, "value": value, "rest": 2, "kind": "resist_down",
                                            "attr": behavior.get("attr", "unknown"), "display": False})
        elif code == "item_gauge":
            sim.party_gauge = min(sim.party_gauge + int(GAUGE_MAX * pct_heal_fraction(value)), GAUGE_MAX)
        elif code == "turn_swap" and targets:
            swap_order_positions(sim, actor["id"], targets[0]["id"])
        elif code == "cleanse_self_pre":
            remove_debuffs(actor)
    for mod in actor.get("mods", []):
        if mod.get("code") == "post_skill_heal" and conds_pass(mod.get("conds"), mod_context(sim, actor, None, None)):
            heal = heal_member(sim, actor, int(actor.get("max_hp", 0) * pct_heal_fraction(mod.get("value", 0))))
            extra_results.append({"target": actor["id"], "heal": heal})
    return extra_results


def remove_debuffs(member: dict) -> int:
    kept = []
    removed = 0
    for buff in member.get("buffs", []):
        if buff.get("kind") in ("taken", "ailment"):
            removed += 1
            continue
        kept.append(buff)
    member["buffs"] = kept
    return removed


def swap_order_positions(sim: "BattleSim", first_id: int, second_id: int) -> bool:
    first = next((i for i, (mid, _) in enumerate(sim.order) if mid == first_id), None)
    second = next((i for i, (mid, _) in enumerate(sim.order) if mid == second_id), None)
    if first is None or second is None or first == second:
        return False
    sim.order[first], sim.order[second] = sim.order[second], sim.order[first]
    return True


def grant_extra_turn(sim: BattleSim, actor: dict, skill_id: int, results: list[dict]) -> bool:
    """Grant an extra turn after a skill whose summary generates one.

    Conditions come from the combat map: unconditional, on-crit, or a
    named-state presence (level gates are presence checks since state
    levels are not tracked). Capped per battle against runaway chains.
    """
    if not actor.get("extra_skill") or sim.extra_turns_total >= 5:
        return False
    for behavior in resolve_attack_local_mods(sim, actor, skill_id):
        if behavior.get("code") != "extra_turn_grant":
            continue
        cond = behavior.get("cond")
        if cond == "on_crit" and not any(
            isinstance(r, dict) and r.get("critical") for r in results
        ):
            continue
        if cond == "state_present" and not any(
            b.get("id") == behavior.get("state_id") for b in actor.get("buffs", [])
        ):
            continue
        if cond not in ("unconditional", "on_crit", "state_present"):
            continue
        actor["extra_turn"] = True
        sim.extra_turns_total += 1
        return True
    return False


def erase_order_entry(sim: BattleSim, member_id: int) -> bool:
    found = False
    kept = []
    for mid, turn in sim.order:
        if mid == member_id and not found:
            found = True
            continue
        kept.append((mid, turn))
    sim.order = kept
    if found:
        member = sim.members.get(member_id)
        if member is not None:
            member["turn_erased"] = True
    return found


def apply_panel_acquisition(sim: "BattleSim", actor: dict, panel: int | None) -> None:
    """Apply exact panel effects to the acquiring side on acquisition."""
    if panel is None:
        return
    entry = cmap_panels(sim.game_dir).get(str(panel))
    if not entry:
        return
    holder = "ally" if actor["side"] == 0 else "enemy"
    allies = sim.alive_allies() if actor["side"] == 0 else sim.alive_foes()
    foes = sim.alive_foes() if actor["side"] == 0 else sim.alive_allies()
    for op in entry.get("ops", []):
        side = op.get("holder", "holder")
        if side == "holder":
            owners = [actor]
        elif (side == "ally") == (holder == "ally"):
            owners = list(allies)
        else:
            owners = list(foes)
        grant_panel_op(sim, actor, owners, op)
    fire_triggers(sim, "panel_gain", actor, {"panel_cat": panel_cat(sim.game_dir, panel)})


def grant_panel_op(sim: "BattleSim", actor: dict, owners: list[dict], op: dict) -> None:
    code = op.get("op") or op.get("code")
    if code in (None, "unmapped", "unmapped_panel"):
        return
    value = int(op.get("text_value", 0) or 0) * 100
    rest = int(op.get("dur_actions", 0) or 0) or 2
    hits = int(op.get("dur_hits", 0) or 0)
    for owner in owners:
        if not owner.get("alive"):
            continue
        if code in ("skill_damage", "skill_power", "crit_rate", "crit_damage",
                    "break_damage", "taken_break", "penetration"):
            owner["buffs"].append({"id": 0, "value": value, "rest": rest,
                                   "kind": code, "display": False})
            if hits:
                owner["buffs"][-1]["hits"] = hits
        elif code == "taken_damage":
            direction = int(op.get("direction", -1))
            owner["buffs"].append({"id": 0, "value": direction * value, "rest": rest,
                                   "kind": "taken", "display": False})
            if hits:
                owner["buffs"][-1]["hits"] = hits
        elif code in ("stat_up", "stat_down"):
            stat = op.get("stat")
            if stat == "spd":
                owner["buffs"].append({"id": 0, "value": value if code == "stat_up" else -value,
                                       "rest": rest, "kind": "speed", "display": False})
            elif stat:
                mult = 1 + (value if code == "stat_up" else -value) / 10000
                owner[stat] = max(int(owner.get(stat, 0) * mult), MIN_BATTLE_STAT)
        elif code == "heal":
            frac = (value / 10000) if value else 0.25
            heal_member(sim, owner, int(owner.get("max_hp", 0) * frac))
        elif code == "ailment":
            ailment = op.get("ailment", "unknown")
            chance = ailment_application_chance(sim, actor, owner, ailment, int(op.get("rate", 95) or 95))
            if sim.rng.randint(1, 100) <= chance:
                owner["buffs"].append({"id": 0, "value": value, "rest": rest,
                                       "kind": "ailment", "ailment": ailment, "display": False})
        elif code == "ailment_dot":
            ailment = op.get("ailment", "burn")
            owner["buffs"].append({"id": 0, "value": value, "rest": rest,
                                   "kind": "ailment", "ailment": ailment, "display": False})


def resolve_ally_action(
    sim: "BattleSim",
    actor: dict,
    skill_type: int,
    main_target: int | None,
    turn: int,
    panel: int | None,
    skill_id_override: int | None = None,
    post_hooks: bool = True,
) -> tuple[list[dict], list[dict], int, int]:
    """Resolve one ally action. Returns (skill_results, effect_blobs, skill_id, wait).

    Panel and additional-attack skills pass post_hooks=False: they resolve
    damage, buffs, and effect records but consume no status turns and
    trigger no post-action behavior.
    """
    skills = battle_table(sim.game_dir, "skill")
    skill_id = (
        skill_id_override
        if skill_id_override is not None
        else actor["skills"].get(skill_type) or actor["skills"].get(1, 0)
    )
    skill = skills.get(str(skill_id), {"power": 0, "attrs": [], "target": 3, "effect": 1, "wait": 0, "effects": [], "break": 0})
    if actor.get("mix_skill_power"):
        skill = dict(skill, power=actor["mix_skill_power"])
    is_burst = skill_type == 3 and skill_id_override is None
    if is_burst and skill_id:
        if int(actor.get("burst_gauge", 0) or 0) >= burst_max(actor) or panel in BURST_PANELS:
            actor["burst_gauge"] = 0
        else:
            skill_id = actor["skills"].get(1, 0)
            skill = skills.get(str(skill_id), skill)
            is_burst = False
    behaviors = resolve_attack_local_mods(sim, actor, skill_id)
    local = {"behaviors": behaviors, "skill_id": skill_id}
    for behavior in behaviors:
        if behavior.get("code") == "cleanse_self_pre":
            remove_debuffs(actor)
    targets = skill_targets(skill, actor, sim, main_target)
    category, elements = affinity_elements(skill.get("attrs") or [])
    use_magic = category == "magic"
    is_aoe = skill.get("target") in (4, 5)
    skill_results = []
    effect_blobs: list[dict] = []
    for target in targets:
        if not target["alive"]:
            continue
        attack_stat = actor["magic"] if use_magic else actor["attack"]
        if skill.get("effect") == 2 and target["side"] == 0:
            recovery = buff_recovery_given_bonus(actor["buffs"]) + buff_recovery_received_bonus(target["buffs"])
            if skill_id_override and (actor.get("pooled") or actor.get("mixer")):
                item_ctx = mod_context(sim, actor, target, skill, is_item=True)
                recovery += sum_slot_mods(actor.get("mods", []), {"item_heal"}, item_ctx, require_item=True) / 10000
            heal = compute_heal(sim.rng, skill.get("power", 0), attack_stat, recovery)
            restored = heal_member(sim, target, heal)
            skill_results.append({"target": target["id"], "heal": restored})
            continue
        if skill.get("effect") == 3:
            skill_results.append({"target": target["id"]})
            continue
        final_target, protector = cover_redirect(sim, actor, target)
        result = apply_hit(
            sim, actor, final_target, skill, elements, use_magic, panel, local,
            {"is_aoe": is_aoe, "is_burst": is_burst,
             "is_item": bool(skill_id_override and (actor.get("pooled") or actor.get("mixer"))),
             "is_cannon": bool(skill_id_override and actor.get("cannon_pooled"))},
        )
        if protector is not None:
            result["protector"] = protector
        for extra in result.pop("effects", []):
            effect_blobs.append(extra)
        skill_results.append(result)
    effect_blobs.extend(apply_skill_effects(sim, actor, skill, targets))
    if post_hooks:
        skill_results.extend(apply_post_behaviors(sim, actor, skill_id, targets, effect_blobs))
        tick_buffs(actor)
    return skill_results, effect_blobs, skill_id, skill.get("wait", 0)


def resolve_enemy_action(sim: "BattleSim", actor: dict, turn: int, panel: int | None) -> tuple[list[dict], list[dict], int, int]:
    skills = battle_table(sim.game_dir, "skill")
    ai_cycle = actor.get("ai") or []
    skill_id = 0
    burst_now = False
    if actor.get("burst") and actor.get("burst_cd", 0) <= 0:
        skill_id = actor["burst"]
        burst_now = True
        actor["burst_cd"] = 5
    elif ai_cycle:
        skill_id = ai_cycle[actor.get("ai_cursor", 0) % len(ai_cycle)]
        actor["ai_cursor"] = actor.get("ai_cursor", 0) + 1
    else:
        actor["burst_cd"] = max(actor.get("burst_cd", 0) - 1, 0)
        return [], [], 0, 0
    actor["burst_cd"] = max(actor.get("burst_cd", 0) - 1, 0)
    skill = skills.get(str(skill_id), {"power": 50, "attrs": [1], "target": 3, "effect": 1, "wait": 0, "effects": [], "break": 10})
    allies = sim.alive_allies()
    if not allies:
        return [], [], 0, 0
    targets = skill_targets(skill, actor, sim, None)
    if int(skill.get("target") or 0) == 3 and targets:
        targets = [aggro_pick(sim, targets)]
    behaviors = resolve_attack_local_mods(sim, actor, skill_id)
    local = {"behaviors": behaviors}
    for behavior in behaviors:
        if behavior.get("code") == "cleanse_self_pre":
            remove_debuffs(actor)
    category, elements = affinity_elements(skill.get("attrs") or [])
    use_magic = category == "magic"
    is_aoe = skill.get("target") in (4, 5)
    skill_results = []
    effect_blobs: list[dict] = []
    for target in targets:
        if not target["alive"]:
            continue
        attack_stat = actor["magic"] if use_magic else actor["attack"]
        if skill.get("effect") == 2 and target["side"] == actor["side"]:
            recovery = buff_recovery_given_bonus(actor["buffs"]) + buff_recovery_received_bonus(target["buffs"])
            heal = compute_heal(sim.rng, skill.get("power", 0), attack_stat, recovery)
            target["hp"] = min(target["hp"] + heal, target["max_hp"])
            skill_results.append({"target": target["id"], "heal": heal})
            continue
        if skill.get("effect") == 3:
            skill_results.append({"target": target["id"]})
            continue
        final_target, protector = cover_redirect(sim, actor, target)
        result = apply_hit(
            sim, actor, final_target, skill, elements, use_magic, panel, local,
            {"is_aoe": is_aoe},
        )
        if protector is not None:
            result["protector"] = protector
        for extra in result.pop("effects", []):
            effect_blobs.append(extra)
        if result.get("damage") is not None and final_target["side"] == 0:
            result["break"] = 0
            result["break_type"] = 0
        skill_results.append(result)
    effect_blobs = apply_skill_effects(sim, actor, skill, targets)
    skill_results.extend(apply_post_behaviors(sim, actor, skill_id, targets, effect_blobs))
    tick_buffs(actor)
    return skill_results, effect_blobs, skill_id, skill.get("wait", 0)

def current_stats(member: dict) -> dict:
    mult = buff_attack_mult(member.get("buffs", []))
    return {
        "speed": member["speed"],
        "attack": int(member["attack"] * mult),
        "magic": int(member["magic"] * mult),
        "defense": int(member["defense"] * mult),
        "mental": int(member["mental"] * mult),
    }


def build_status(stats: dict) -> bytes:
    out = bytearray(write_field(1, 0, stats["speed"]))
    out.extend(write_field(2, 0, stats["attack"]))
    out.extend(write_field(3, 0, stats["magic"]))
    out.extend(write_field(4, 0, stats["defense"]))
    out.extend(write_field(5, 0, stats["mental"]))
    return bytes(out)


def build_resistance(res: dict) -> bytes:
    out = bytearray()
    for number, key in ((1, "slashing"), (2, "impact"), (3, "piercing"), (5, "fire"), (6, "ice"), (7, "lightning"), (8, "wind")):
        value = int(res.get(key, 0) or 0)
        if value:
            out.extend(write_varint((number << 3) | 0))
            out.extend(write_sint(value))
    return bytes(out)


def build_state_change(buff: dict) -> bytes:
    out = bytearray(write_field(1, 0, buff["id"]))
    if buff.get("rest"):
        out.extend(write_field(3, 0, buff["rest"]))
    out.extend(write_field(4, 0, buff.get("value", 0)))
    if buff.get("kind") == "ailment" and buff.get("ailment") == "taunt":
        out.extend(write_field(7, 0, 1))
    if buff.get("kind") == "barrier":
        out.extend(write_field(11, 0, 1))
    if buff.get("kind") in ("null_damage",):
        out.extend(write_field(9, 0, 1))
    if not buff.get("display", True):
        out.extend(write_field(10, 0, 1))
    if buff.get("level") is not None:
        out.extend(write_field(8, 2, write_field(1, 0, buff["level"])))
    return bytes(out)


def build_member(member: dict) -> bytes:
    out = bytearray(write_field(1, 0, member["id"]))
    if member["side"] == 1:
        out.extend(write_field(2, 0, 1))
    out.extend(write_field(3, 0, member["max_hp"]))
    out.extend(write_field(4, 0, member["hp"]))
    if member["alive"]:
        out.extend(write_field(5, 0, 1))
    if member.get("stun"):
        out.extend(write_field(16, 0, 1))
    if member["side"] == 0:
        out.extend(
            write_field(
                6,
                2,
                build_status(
                    {
                        "speed": member["speed"],
                        "attack": member["attack"],
                        "magic": member["magic"],
                        "defense": member["defense"],
                        "mental": member["mental"],
                    }
                ),
            )
        )
        out.extend(write_field(7, 2, build_status(current_stats(member))))
    else:
        out.extend(write_field(6, 2, write_field(1, 0, member["speed"])))
        out.extend(write_field(7, 2, write_field(1, 0, member["speed"])))
    out.extend(write_field(8, 2, build_resistance(member.get("res", {}))))
    if member["side"] == 0:
        ally = bytearray(write_field(1, 0, member["character_id"]))
        ally.extend(write_field(5, 0, member["character_id"]))
        skill_lamps = member.get("skill_lamps", {}) or {}
        for skill_type in (1, 2, 3):
            skill_id = member["skills"].get(skill_type, 0)
            if skill_id:
                skill_blob = write_field(1, 0, skill_id) + write_field(2, 0, skill_type)
                lamp = int(skill_lamps.get(skill_type, 0) or 0)
                if lamp > 0:
                    skill_blob += write_field(5, 0, lamp)
                ally.extend(write_field(3, 2, skill_blob))
        for active_type, active_id in (member.get("active_skills") or {}).items():
            rest = int((member.get("active_rest") or {}).get(active_type, 0) or 0)
            if not active_id or rest <= 0:
                continue
            ally.extend(
                write_field(
                    7,
                    2,
                    write_field(1, 0, active_id)
                    + write_field(2, 0, active_type)
                    + write_field(3, 0, rest),
                )
            )
        if member.get("leader"):
            ally.extend(write_field(4, 0, 1))
        out.extend(write_field(12, 2, bytes(ally)))
        for ability_id in member.get("abilities", []):
            out.extend(write_field(15, 2, write_field(1, 0, ability_id)))
    else:
        foe = bytearray(write_field(1, 0, member["enemy_id"]))
        foe.extend(write_field(3, 0, member["break_max"]))
        foe.extend(write_field(4, 0, member["break_cur"]))
        if member.get("broken"):
            foe.extend(write_field(5, 0, 1))
        if member.get("base_enemy_number") is not None:
            foe.extend(write_wrapped_varint(6, member["base_enemy_number"]))
        foe.extend(write_field(7, 0, 1))
        foe.extend(write_field(9, 2, write_field(27, 0, 1)))
        out.extend(write_field(13, 2, bytes(foe)))
    for buff in member.get("buffs", []):
        if not buff.get("display", True):
            continue
        out.extend(write_field(14, 2, build_state_change(buff)))
    out.extend(write_field(19, 0, member["max_hp"]))
    barriers = [b for b in member.get("buffs", []) if b.get("kind") == "barrier"]
    for index, barrier in enumerate(barriers):
        durability = max(int(barrier.get("value", 0) or 0), 0)
        out.extend(
            write_field(
                21, 2,
                write_field(1, 0, index + 1)
                + write_field(2, 0, durability)
                + write_field(3, 0, durability),
            )
        )
        out.extend(write_field(22, 0, durability))
    out.extend(build_burst_gauge(int(member.get("burst_gauge", 0) or 0) if member["side"] == 0 else 0))
    ship_memoria = member.get("ship_memoria")
    if member["side"] == 0 and ship_memoria:
        out.extend(write_field(27, 2, ship_memoria))
    return bytes(out)


def build_burst_gauge(current: int = 0) -> bytes:
    return write_field(
        25, 2,
        write_field(1, 0, max(min(int(current), BURST_GAUGE_MAX), 0))
        + write_field(2, 0, 100),
    )


def build_ship_main_memoria_blob(game_dir: Path, profile_plaintext: bytes) -> bytes | None:
    """Serialize the ship-party main support Memoria for battle members.

    BattleShipMainMemoria carries the support Memoria id, its top unlocked
    ability, computed level, and limit break. The value coefficient grows
    with supporting Memoria by an unreversed formula, so it is omitted;
    see BATTLE.md.
    """
    ship_party, _ = selected_ship_party(profile_plaintext)
    if ship_party is None:
        return None
    main_entity = wrapped_varint_field(ship_party, 3, None)
    if main_entity is None:
        return None
    resources = profile_resources(profile_plaintext)
    record = next(
        (
            bytes(value)
            for number, wire, value in read_wire_fields(resources)
            if number == 29 and wire == 2
            and varint_field(bytes(value), 1, -1) == main_entity
        ),
        b"",
    )
    if not record:
        return None
    memoria_id = varint_field(record, 2, 0)
    master = prog_table(game_dir, "memoria").get(str(memoria_id), {})
    abilities = [int(value) for value in master.get("ability_ids") or []]
    if not memoria_id or not abilities:
        return None
    limit_break = max(varint_field(record, 3, 0), 0)
    level = memoria_level_for_exp(game_dir, record, master)
    top = abilities[min(limit_break, len(abilities) - 1)]
    out = bytearray(write_field(1, 0, memoria_id))
    out.extend(write_field(2, 2, write_varint(top)))
    out.extend(write_field(3, 0, level))
    out.extend(write_field(4, 0, limit_break))
    return bytes(out)


def build_unit(member_id: int, turn: int, position: int, enemy_skill_type: int | None = None, strong: bool = False) -> bytes:
    out = bytearray(write_field(1, 0, member_id))
    out.extend(write_field(2, 0, turn))
    if enemy_skill_type is not None:
        out.extend(write_wrapped_varint(3, enemy_skill_type))
    if strong:
        out.extend(write_field(4, 0, 1))
    if position > 0:
        out.extend(write_field(6, 0, position))
    return bytes(out)


def build_panel(turn: int, panel_id: int | None) -> bytes:
    out = bytearray(write_field(1, 0, turn))
    if panel_id is not None:
        out.extend(write_wrapped_varint(2, panel_id))
    return bytes(out)


def build_selection_timeline_move(
    sim: "BattleSim | None", actor: dict, skill: dict
) -> bytes:
    """Estimate the acting member's timeline move shown in skill previews."""
    if sim is None:
        return b""
    frm = next(
        (i for i, (member_id, _) in enumerate(sim.order) if member_id == actor["id"]),
        0,
    )
    wait = int(skill.get("wait", 0) or 0)
    wait_value = effective_wait(eff_speed(actor), wait)
    steps = max(1, wait_value // 100)
    to = min(max(len(sim.order) - 1, 0), frm + steps)
    timeline_wait = max(0, wait_value)
    return (
        write_field(1, 0, actor["id"])
        + write_field(2, 0, sim.request_count + 2)
        + write_field(3, 0, 4)
        + write_optional_wrapped_varint(4, frm)
        + write_optional_wrapped_varint(5, to)
        + write_optional_wrapped_varint(6, timeline_wait)
    )


def build_state(sim: "BattleSim") -> bytes:
    out = bytearray(write_field(1, 0, sim.battle_id))
    for wave_id in sim.wave_ids:
        out.extend(write_field(2, 0, wave_id))
    out.extend(write_field(3, 0, sim.wave_index + 1))
    out.extend(write_field(4, 0, sim.total_turn))
    for member in sim.members.values():
        out.extend(write_field(5, 2, build_member(member)))
    for cycle in range(2):
        for slot, (member_id, turn) in enumerate(sim.order):
            member = sim.members.get(member_id)
            if member is None or not member["alive"]:
                continue
            position = slot * 8 if cycle == 0 else 240 + slot * 8
            out.extend(
                write_field(
                    6,
                    2,
                    build_unit(
                        member_id,
                        turn + cycle,
                        position,
                        member.get("next_enemy_skill"),
                        member.get("strong_next", False),
                    ),
                )
            )
    for tool in sim.tools:
        out.extend(write_field(8, 2, build_tool_blob(tool)))
    panel_start = sim.request_count + 1
    for turn in range(panel_start, panel_start + PANEL_COUNT):
        out.extend(write_field(15, 2, build_panel(turn, panel_for_turn(sim.game_dir, sim.battle_id, turn))))
    if sim.party_gauge:
        out.extend(write_field(14, 0, sim.party_gauge))
    if sim.field_effect is not None:
        out.extend(write_field(16, 2, write_field(1, 0, sim.field_effect)))
    for base_enemy_id, count in sim.enemy_groups.items():
        group = bytearray(write_field(1, 0, base_enemy_id))
        if count > 1:
            group.extend(write_wrapped_varint(2, count))
        out.extend(write_field(17, 2, bytes(group)))
    # Japanese BattleState includes this empty message in captures; keep
    # presence so the client initializes start-perform state consistently.
    out.extend(write_field(19, 2, b""))
    for cannon in sim.cannons:
        out.extend(write_field(21, 2, build_cannon_blob(cannon)))
    return bytes(out)


def build_battle_start_state(sim: "BattleSim") -> bytes:
    """Build the pre-wave state stored in BattleHistory.start.

    Captured starts keep this distinct from the active wave snapshot: it
    contains the party and tools, but no enemies, timeline units, or panels.
    """
    out = bytearray(write_field(1, 0, sim.battle_id))
    for wave_id in sim.wave_ids:
        out.extend(write_field(2, 0, wave_id))
    out.extend(write_field(3, 0, sim.wave_index + 1))
    out.extend(write_field(4, 0, sim.total_turn))
    for member in sim.members.values():
        if member["side"] == 0:
            out.extend(write_field(5, 2, build_member(member)))
    for tool in sim.tools:
        out.extend(write_field(8, 2, build_tool_blob(tool)))
    out.extend(write_field(14, 0, sim.party_gauge))
    out.extend(write_field(19, 2, b""))
    for cannon in sim.cannons:
        out.extend(write_field(21, 2, build_cannon_blob(cannon)))
    return bytes(out)


def build_start_changed_resources(profile_plaintext: bytes) -> bytes:
    """Echo the task-count resource present in captured battle-start replies."""
    try:
        resources = profile_resources(profile_plaintext)
    except (ValueError, StopIteration):
        return b""
    out = bytearray()
    for number, wire, value in read_wire_fields(resources):
        if number != 32 or wire != 2:
            continue
        record = bytes(value)
        if varint_field(record, 1, -1) == 81:
            out.extend(write_field(32, 2, record))
    return bytes(out)


def build_move(
    member_id: int, turn: int, reason: int, frm: int, to: int, wait: int = 0
) -> bytes:
    return (
        write_field(1, 0, member_id)
        + write_field(2, 0, turn)
        + (write_field(3, 0, reason) if reason else b"")
        + write_optional_wrapped_varint(4, frm)
        + write_optional_wrapped_varint(5, to)
        + write_optional_wrapped_varint(6, wait)
    )


def build_selection_target(
    sim: "BattleSim",
    actor: dict,
    skill: dict,
    target: dict,
    outgoing: float,
    force_crit: bool,
    preview: bool,
    include_timeline: bool = True,
    multi: bool = False,
) -> bytes:
    category, elements = affinity_elements(skill.get("attrs") or [])
    use_magic = category == "magic"
    attack_stat = actor["magic"] if use_magic else actor["attack"]
    out = bytearray(write_field(1, 0, target["id"]))
    if preview and skill.get("effect") not in (1, 2):
        # Captured buff/state previews (e.g. Rorona 12002902, target 4)
        # carry only the target id, plus timeline moves when the skill
        # has wait (Totori active 14002902, wait -200, shows one move).
        if include_timeline and int(skill.get("wait", 0) or 0):
            out.extend(
                write_field(8, 2, build_selection_timeline_move(sim, actor, skill))
            )
        return bytes(out)
    if preview:
        out.extend(write_field(12, 2, b""))
    if skill.get("effect") == 2 and target["side"] == 0:
        heal = compute_heal(
            None, skill.get("power", 0), attack_stat,
            buff_recovery_given_bonus(actor["buffs"]) + buff_recovery_received_bonus(target["buffs"]),
        )
        out.extend(write_wrapped_varint(4, heal))
        out.extend(write_field(12, 2, b""))
        out.extend(write_field(16, 0, 1))
        return bytes(out)
    defense_stat = target["mental"] if (use_magic and target["side"] == 0) else target["defense"]
    broken = bool(target.get("broken"))
    res_value = combined_resistance(elements, target.get("res", {}), target.get("buffs", []), sim, target)
    res_value -= resist_down_bonus(target.get("buffs", []), elements)
    weak = res_value <= WEAK_THRESHOLD
    resist = (not weak) and res_value >= RESIST_THRESHOLD
    taken = buff_defense_mult(target["buffs"])
    skill_damage = panel_skill_damage_mult(None)
    if preview:
        damage = compute_preview_damage(
            int(skill.get("power", 0) or 0),
            attack_stat,
            defense_stat,
            actor.get("level", 1),
            res_value,
            broken,
            skill_damage,
            1.0,
            outgoing,
            taken,
        )
        critical = False
        break_hit = compute_break_hit(
            None, attack_stat, (skill.get("break", 0) or 0) / 100, res_value,
        )
    else:
        damage, critical = compute_hit(
            sim.rng,
            skill.get("power", 0),
            attack_stat,
            defense_stat,
            actor.get("level", 1),
            res_value,
            broken,
            force_crit,
            ALLY_CRIT_RATE if actor["side"] == 0 else ENEMY_CRIT_RATE,
            skill_damage,
            1.0,
            outgoing,
            taken,
        )
        break_hit = compute_break_hit(
            sim.rng, attack_stat, (skill.get("break", 0) or 0) / 100, res_value,
        )
    out.extend(write_wrapped_varint(3, damage))
    out.extend(write_wrapped_varint(5, break_hit))
    if weak:
        out.extend(write_field(6, 0, 1))
    if resist:
        out.extend(write_field(7, 0, 1))
    if preview:
        if include_timeline and int(skill.get("wait", 0) or 0):
            out.extend(
                write_field(8, 2, build_selection_timeline_move(sim, actor, skill))
            )
        out.extend(write_field(12, 2, b""))
        if multi:
            # Captured multi-candidate damage previews mark every target
            # is_killed=1 (meaning unknown); single-candidate starts omit it.
            out.extend(write_field(14, 0, 1))
        out.extend(
            write_field(15, 2, write_field(1, 0, max(int(damage * CRIT_MULT), 0)))
        )
        if multi:
            out.extend(write_field(16, 0, 1))
        if multi or (sim is not None and sim.request_count == 0):
            out.extend(write_field(17, 5, struct.pack("<f", PREVIEW_DAMAGE_RATE)))
    if critical and not preview:
        out.extend(write_field(11, 0, 1))
    return bytes(out)


def build_setup(
    sim: "BattleSim", actor: dict, number: int, include_tool_selections: bool = True
) -> bytes:
    skills = battle_table(sim.game_dir, "skill")
    outgoing = buff_attack_mult(actor["buffs"])
    out = bytearray(write_field(1, 0, number))
    out.extend(write_field(2, 2, build_state(sim)))
    if actor["side"]:
        out.extend(write_field(3, 0, actor["side"]))
    out.extend(write_field(4, 0, actor["id"]))
    for skill_type in (1, 2, 3):
        skill_id = actor.get("skills", {}).get(skill_type, 0) if actor["side"] == 0 else 0
        if skill_type == 1 and actor.get("range", "in") == "out":
            skill_id = effective_skill1(sim.game_dir, actor) or skill_id
        if skill_type == 2 and actor.get("extra_turn") and actor.get("extra_skill"):
            skill_id = actor["extra_skill"]
        if not skill_id:
            continue
        if skill_type == 3 and int(actor.get("burst_gauge", 0) or 0) < burst_max(actor):
            continue
        skill = skills.get(str(skill_id), {})
        targets = preview_targets(skill, actor, sim)
        is_all = skill.get("target") in (4, 5)
        sel = bytearray(write_field(1, 0, skill_type))
        sel.extend(write_field(6, 0, skill_id))
        if is_all:
            sel.extend(write_field(4, 0, 1))
            if int(skill.get("wait", 0) or 0):
                sel.extend(
                    write_field(3, 2, build_selection_timeline_move(sim, actor, skill))
                )
        multi = len(targets) > 1
        for target in targets:
            sel.extend(
                write_field(
                    2,
                    2,
                    build_selection_target(
                        sim, actor, skill, target, outgoing, False, True, not is_all,
                        multi,
                    ),
                )
            )
        out.extend(write_field(8, 2, bytes(sel)))
    if actor["side"] == 0:
        for active_type, active_id in (actor.get("active_skills") or {}).items():
            rest = int((actor.get("active_rest") or {}).get(active_type, 0) or 0)
            if not active_id or rest <= 0:
                continue
            skill = skills.get(str(active_id), {})
            targets = preview_targets(skill, actor, sim)
            is_all = skill.get("target") in (4, 5)
            sel = bytearray(write_field(1, 0, active_type))
            if is_all:
                sel.extend(write_field(4, 0, 1))
                if int(skill.get("wait", 0) or 0):
                    sel.extend(
                        write_field(3, 2, build_selection_timeline_move(sim, actor, skill))
                    )
            multi = len(targets) > 1
            for target in targets:
                sel.extend(
                    write_field(
                        2,
                        2,
                        build_selection_target(
                            sim, actor, skill, target, outgoing, False, True, not is_all,
                            multi,
                        ),
                    )
                )
            sel.extend(write_field(5, 0, active_id))
            out.extend(write_field(15, 2, bytes(sel)))
    if include_tool_selections and sim.party_gauge >= GAUGE_MAX:
        for tool in sim.tools:
            if tool.get("uses", 0) <= 0:
                continue
            tool_skill_id = int(tool.get("skill_id", 0) or 0)
            skill = skills.get(str(tool_skill_id))
            if skill is None:
                continue
            targets = preview_targets(skill, actor, sim)
            selection = bytearray(write_field(1, 0, tool["number"]))
            is_all = skill.get("target") in (4, 5)
            if is_all:
                selection.extend(write_field(4, 0, 1))
                if int(skill.get("wait", 0) or 0):
                    selection.extend(
                        write_field(3, 2, build_selection_timeline_move(sim, actor, skill))
                    )
            multi = len(targets) > 1
            for target in targets:
                selection.extend(
                    write_field(
                        2,
                        2,
                        build_selection_target(
                            sim, actor, skill, target, outgoing, False, True, not is_all,
                            multi,
                        ),
                    )
                )
            out.extend(write_field(9, 2, bytes(selection)))
    out.extend(write_field(12, 2, b""))
    return bytes(out)

def rebuild_order(sim: BattleSim) -> None:
    alive = [(mid, turn) for mid, turn in sim.order if sim.members.get(mid, {}).get("alive")]
    seen = set()
    compact: list[tuple[int, int]] = []
    for mid, turn in alive:
        if mid in seen:
            continue
        seen.add(mid)
        compact.append((mid, turn))
    for mid, member in sim.members.items():
        if member.get("turn_erased"):
            member["turn_erased"] = False
            continue
        if member["alive"] and mid not in seen:
            compact.append((mid, sim.turn))
            sim.turn += 1
    sim.order = compact


def move_actor_back(sim: BattleSim, member_id: int, wait: int) -> tuple[int, int, int]:
    """Move the actor back on the timeline; returns (turn, frm, to)."""
    member = sim.members.get(member_id, {})
    wait_value = effective_wait(eff_speed(member), wait)
    frm = next((i for i, (mid, _) in enumerate(sim.order) if mid == member_id), 0)
    sim.order = [(mid, turn) for mid, turn in sim.order if mid != member_id]
    steps = max(1, wait_value // 100)
    to = min(len(sim.order), frm + steps)
    turn = sim.turn
    sim.turn += 1
    sim.order.insert(to, (member_id, turn))
    return turn, frm, to


def pooled_item_actor(sim: BattleSim, actor: dict) -> dict:
    """Items and cannons use the party's average stats without ally buffs."""
    allies = sim.alive_allies()
    count = max(len(allies), 1)
    pooled = dict(actor)
    for stat in ("attack", "magic", "defense", "mental", "speed"):
        pooled[stat] = sum(int(member.get(stat, 0) or 0) for member in allies) // count
    pooled["level"] = sum(int(member.get("level", 1) or 1) for member in allies) // count
    pooled["buffs"] = []
    pooled["pooled"] = True
    # General ally modifiers do not apply to items/cannons; only effects
    # that specifically target items or cannons carry over.
    pooled["mods"] = [
        mod for mod in actor.get("mods", [])
        if mod.get("code") in ("item_damage", "item_heal", "cannon_damage",
                               "cannon_crit", "ailment_rate", "on_hit_resist")
    ]
    return pooled


def build_action(
    sim: "BattleSim",
    number: int,
    actor: dict,
    skill_id: int,
    skill_type: int | None,
    main_target: int | None,
    skill_results: list[dict],
    effect_blobs: list[dict],
    moves: list[dict],
    total_dealt: int,
    tool_number: int | None = None,
    action_type: int | None = None,
    cannon_number: int | None = None,
    active_skill_type: int | None = None,
) -> bytes:
    if actor["side"] == 1 and main_target is None and skill_results:
        main_target = skill_results[0].get("target")
    if main_target is None and skill_results:
        main_target = skill_results[0].get("target")
    if action_type is None:
        action_type = 1 if tool_number is not None else 0
    out = bytearray(write_field(1, 0, number))
    out.extend(write_field(2, 2, build_state(sim)))
    if action_type:
        out.extend(write_field(18, 0, action_type))
    if actor["side"]:
        out.extend(write_field(3, 0, actor["side"]))
    out.extend(write_field(4, 0, actor["id"]))
    out.extend(write_field(5, 0, skill_id))
    if skill_type is not None:
        out.extend(write_wrapped_varint(6, skill_type))
    if main_target is not None:
        out.extend(write_field(7, 0, main_target))
    if tool_number is not None:
        out.extend(write_wrapped_varint(10, tool_number))
    if cannon_number is not None:
        out.extend(write_field(31, 2, write_field(1, 0, cannon_number)))
    if active_skill_type is not None:
        out.extend(write_field(28, 0, active_skill_type))
    protector = next((r.get("protector") for r in skill_results if r.get("protector") is not None), None)
    if protector is not None:
        out.extend(write_optional_wrapped_varint(19, protector))
    skipped = any(r.get("skipped") for r in skill_results)
    if skipped:
        out.extend(write_field(21, 0, 1))
    for result in skill_results:
        res = bytearray(write_field(1, 0, result["target"]))
        if result.get("miss"):
            res.extend(write_field(2, 0, 1))
        elif result.get("invalid"):
            res.extend(write_field(14, 0, 1))
        elif result.get("heal") is not None:
            res.extend(write_wrapped_varint(8, result["heal"]))
        elif result.get("damage") is not None:
            res.extend(write_wrapped_varint(7, result["damage"]))
            if result.get("break", 0):
                res.extend(write_wrapped_varint(13, result["break"]))
            if result.get("weak"):
                res.extend(write_field(9, 0, 1))
            if result.get("resist"):
                res.extend(write_field(10, 0, 1))
            if result.get("critical"):
                res.extend(write_field(11, 0, 1))
            if result.get("guard"):
                res.extend(write_field(12, 0, 1))
            if result.get("break_type"):
                res.extend(write_field(15, 0, result["break_type"]))
            if result.get("barrier_damage"):
                res.extend(write_wrapped_varint(16, result["barrier_damage"]))
            else:
                res.extend(write_field(16, 2, b""))
            if result.get("barrier_broken"):
                res.extend(write_field(17, 0, 1))
            critical_damage = result.get("critical_damage")
            if critical_damage is not None:
                res.extend(write_wrapped_varint(18, critical_damage))
            damage_rate = result.get("damage_rate")
            if damage_rate is not None:
                res.extend(write_field(19, 5, struct.pack("<f", float(damage_rate))))
            if result.get("killed"):
                res.extend(write_field(6, 0, 1))
        out.extend(write_field(8, 2, bytes(res)))
    for move in moves:
        out.extend(
            write_field(
                22,
                2,
                build_move(
                    move["member"],
                    move.get("turn", 0),
                    move.get("reason", 0),
                    move.get("frm", 0),
                    move.get("to", 0),
                    move.get("wait", 0),
                ),
            )
        )
    action_effects = list(effect_blobs)
    if action_type == 0 and actor["side"] == 0 and skill_id:
        action_effects.append(
            {
                "effector": actor["id"],
                "target": actor["id"],
                "effect_id": 2000392,
                "motion": 70,
            }
        )
    for effect in action_effects:
        out.extend(write_field(11, 2, build_effect_result(effect)))
    if total_dealt:
        out.extend(write_field(26, 0, total_dealt))
    return bytes(out)


def build_effect_result(effect: dict) -> bytes:
    """Serialize a captured skill-motion or applied state-change result."""
    effector_id = int(effect["effector"])
    target_id = int(effect["target"])
    effect_id = int(effect["effect_id"])
    out = bytearray(write_wrapped_varint(1, target_id))
    out.extend(write_field(2, 0, effect_id))
    if effect.get("value") is not None:
        out.extend(write_field(3, 0, 1))
    out.extend(write_field(14, 0, effector_id))
    if effect.get("value") is not None:
        state = (
            write_field(1, 0, effect_id)
            + write_field(3, 0, int(effect.get("rest", 1)))
            + write_field(4, 0, int(effect["value"]))
        )
        out.extend(write_field(21, 2, state))
        if effect.get("is_skill"):
            out.extend(write_field(23, 0, 1))
        out.extend(write_wrapped_varint(24, effect_id))
    dealt = effect.get("dealt_state_change")
    if dealt is not None:
        out.extend(write_field(21, 2, build_state_change(dealt)))
    if effect.get("counter"):
        out.extend(write_field(15, 0, 1))
    if effect.get("motion") is not None:
        out.extend(
            write_field(35, 2, write_field(1, 0, int(effect["motion"])))
        )
    return bytes(out)


def build_history(
    sim: "BattleSim",
    include_prev: bool,
    include_formation: bool = True,
    since: tuple[int, int, int] | None = None,
) -> bytes:
    """Serialize battle history, optionally only entries after `since`.

    Captured attack responses are incremental: they carry only the wave
    starts, setups, and actions the client has not seen yet (plus the
    start snapshot, previous state, and formation every time). Resending
    full history makes the client replay stale turns in a loop.
    """
    start = since or (0, 0, 0)
    out = bytearray()
    if sim.status != 0:
        out.extend(write_field(1, 0, sim.status))
    for blob in sim.wave_starts[start[0]:]:
        out.extend(write_field(2, 2, blob))
    for blob in sim.setups[start[1]:]:
        out.extend(write_field(3, 2, blob))
    for blob in sim.actions[start[2]:]:
        out.extend(write_field(4, 2, blob))
    start_state = sim.start_state if sim.start_state is not None else build_state(sim)
    out.extend(write_field(6, 2, write_field(1, 2, start_state)))
    if include_prev and sim.previous_state is not None:
        out.extend(write_field(10, 2, sim.previous_state))
    if include_formation and sim.previous_formation is not None:
        out.extend(write_field(9, 2, sim.previous_formation))
    out.extend(write_field(13, 2, b""))
    return bytes(out)


def build_context(sim: "BattleSim") -> bytes:
    out = bytearray()
    if sim.kind == "quest":
        out.extend(write_field(1, 0, sim.ref_id))
    elif sim.kind == "exploration":
        out.extend(write_field(2, 0, sim.ref_id))
    elif sim.kind == "gacha":
        out.extend(write_field(5, 0, sim.ref_id))
    out.extend(write_field(3, 2, sim.start_txid.encode("ascii")))
    if sim.kind == "quest":
        out.extend(write_wrapped_varint(4, sim.party_number))
    return bytes(out)


def default_formation(sim: "BattleSim") -> bytes:
    coords = [(3.8, -2.0), (-3.8, -2.0), (-2.3, -5.0), (1.5, -5.0), (0.0, -2.0)]
    out = bytearray()
    for member in sim.members.values():
        if member["side"] == 0:
            x, z = coords[(member["id"] - 1) % len(coords)]
        else:
            x, z = -2.0 + (member["id"] - 11) * 1.75, 2.0 + (member["id"] - 11) % 2 * 4.0
        out.extend(
            write_field(
                2,
                2,
                write_field(1, 0, member["id"])
                + write_field(2, 5, struct.pack("<f", x))
                + write_field(3, 5, struct.pack("<f", z)),
            )
        )
    return bytes(out)


def snapshot_state(sim: "BattleSim") -> bytes:
    return build_state(sim)


def check_battle_end(sim: "BattleSim") -> int:
    if not sim.alive_allies():
        sim.status = 2
        return 2
    if not sim.alive_foes():
        if sim.wave_index + 1 < len(sim.wave_ids):
            sim.start_wave(sim.wave_index + 1)
            rebuild_order(sim)
            sim.wave_starts.append(
                write_field(1, 0, sim.request_count + 1) + write_field(2, 2, build_state(sim))
            )
            return 0
        sim.status = 1
        return 1
    if sim.countdown is not None and sim.request_count + 1 > sim.countdown:
        sim.status = 2
        return 2
    return 0

_ACTIVE: dict | None = None


def active_battle() -> dict | None:
    return _ACTIVE


def clear_battle() -> None:
    global _ACTIVE
    _ACTIVE = None


def do_action(
    sim: BattleSim,
    actor: dict,
    kind: str,
    skill_type: int | None,
    main_target: int | None,
    tool_number: int | None,
) -> bytes:
    """Resolve one action and return the action blob."""
    turn = next((t for mid, t in sim.order if mid == actor["id"]), sim.turn)
    panel = panel_for_turn(sim.game_dir, sim.battle_id, turn)
    tick_start_of_turn(sim, actor)
    if actor.get("alive"):
        fire_triggers(sim, "turn_start", actor, {})
    if not actor.get("alive"):
        blob = build_action(
            sim, sim.action_no + 1, actor, 0, skill_type, main_target,
            [{"target": actor["id"], "skipped": True}], [], [], 0,
        )
        sim.action_no += 1
        sim.actions.append(blob)
        sim.total_turn += 1
        rebuild_order(sim)
        return blob
    fail = action_fail_roll(sim, actor) if kind in ("skill", "auto") else None
    if fail is not None:
        if fail == "stun":
            actor["stun"] = False
            remove_ailments(actor, {"stun"})
        tick_buffs(actor)
        blob = build_action(
            sim, sim.action_no + 1, actor, 0, skill_type, main_target,
            [{"target": actor["id"], "skipped": True}], [], [], 0,
        )
        frm = next((i for i, (mid, _) in enumerate(sim.order) if mid == actor["id"]), 0)
        turn, frm, to = move_actor_back(sim, actor["id"], 0)
        sim.action_no += 1
        sim.actions.append(blob)
        sim.total_turn += 1
        rebuild_order(sim)
        return blob
    if kind == "tool" and tool_number is not None:
        tool = next((t for t in sim.tools if t["number"] == tool_number and t["uses"] > 0), None)
        if tool is None:
            raise ValueError(f"battle tool number={tool_number} is unavailable")
        tool_row = prog_table(sim.game_dir, "battle_tool").get(str(tool.get("tool_id", 0)), {})
        uses_done = max(int(tool_row.get("usage_count", 0) or 0) - int(tool.get("uses", 0) or 0), 0)
        tool["uses"] -= 1
        tool_skill_id = int(tool.get("skill_id", 0) or 0)
        tool_actor = pooled_item_actor(sim, actor)
        if uses_done <= 0:
            for mod in actor.get("mods", []):
                if mod.get("code") == "first_use_damage":
                    tool_actor["mods"].append({"code": "skill_damage",
                                               "value": int(mod.get("value", 0) or 0),
                                               "conds": [], "direction": 1})
        if tool_skill_id:
            results, effect_blobs, skill_id, _ = resolve_ally_action(
                sim,
                tool_actor,
                1,
                main_target,
                turn,
                panel,
                skill_id_override=tool_skill_id,
            )
        else:
            results, effect_blobs, skill_id = [], [], 0
        if main_target is None and results:
            main_target = results[0].get("target")
        tool_member = sim.members.get(main_target) if isinstance(main_target, int) else None
        tool_skill = battle_table(sim.game_dir, "skill").get(str(skill_id), {})
        fire_action_triggers(sim, actor, skill_id, results, tool_member, panel,
                             is_item=True, is_aoe=tool_skill.get("target") in (4, 5))
        blob = build_action(
            sim,
            sim.action_no + 1,
            actor,
            skill_id,
            None,
            main_target,
            results,
            effect_blobs,
            [],
            sim.total_dealt_hp_damage,
            tool_number,
            action_type=1,
        )
        sim.action_no += 1
        sim.actions.append(blob)
        return blob
    if kind == "auto" or skill_type is None:
        if actor["side"] == 0 and int(actor.get("burst_gauge", 0) or 0) >= burst_max(actor):
            skill_type = 3
        elif sim.request_count % 3 == 2:
            skill_type = 2
        else:
            skill_type = 1
    skill_id = 0
    wait = 0
    if actor["side"] == 0:
        extra_turn = bool(actor.pop("extra_turn", False))
        skill_id = actor["skills"].get(skill_type or 1, 0) or actor["skills"].get(1, 0)
        if skill_type == 1:
            skill_id = effective_skill1(sim.game_dir, actor) or skill_id
        skills = battle_table(sim.game_dir, "skill")
        skill = skills.get(str(skill_id), {})
        burst_fired = False
        if skill_type == 3 and skill_id:
            if int(actor.get("burst_gauge", 0) or 0) < burst_max(actor) and panel not in BURST_PANELS:
                skill_id = actor["skills"].get(1, 0)
                skill_type = 1
            else:
                burst_fired = True
        skill_info = combat_map(sim.game_dir).get("skills", {}).get(str(skill_id), {})
        lamp_max = max(int(skill_info.get("lamp_max", 0) or 0), 1)
        if skill_info.get("transform") and (actor.get("lamp_lit") or {}).get(skill_id, 0) >= lamp_max:
            actor["transformed"] = True
        target_member = sim.members.get(main_target) if isinstance(main_target, int) else None
        if kind in ("skill", "auto"):
            fire_triggers(sim, "pre_attack", actor, {"skill_id": skill_id, "target_member": target_member})
        override = None
        if skill_type == 2 and extra_turn and actor.get("extra_skill"):
            override = actor["extra_skill"]
        if override is not None:
            results, blobs, skill_id, wait = resolve_ally_action(
                sim, actor, 2, main_target, turn, panel, skill_id_override=override
            )
        else:
            results, blobs, skill_id, wait = resolve_ally_action(sim, actor, skill_type or 1, main_target, turn, panel)
        if skill_info.get("transform"):
            lit = actor.setdefault("lamp_lit", {})
            if lit.get(skill_id, 0) < lamp_max:
                lit[skill_id] = lit.get(skill_id, 0) + 1
        if skill_info.get("range_move"):
            set_member_range(sim, actor, skill_info["range_move"])
        gain_down = sum_slot_mods(actor.get("mods", []),
                                      {"burst_gain_down"}, mod_context(sim, actor, None, None)) / 10000
        gain_factor = max(1.0 - gain_down, 0.0)
        if skill_type == 1:
            actor["burst_gauge"] = min(int(actor.get("burst_gauge", 0) or 0) + int(BURST_GAIN_SKILL1 * gain_factor), burst_max(actor))
        elif skill_type == 2:
            actor["burst_gauge"] = min(int(actor.get("burst_gauge", 0) or 0) + int(BURST_GAIN_SKILL2 * gain_factor), burst_max(actor))
        if kind in ("skill", "auto"):
            resolved = battle_table(sim.game_dir, "skill").get(str(skill_id), {})
            fire_action_triggers(sim, actor, skill_id, results, target_member, panel,
                                 is_aoe=resolved.get("target") in (4, 5))
            if burst_fired:
                burst_ctx = {"skill_id": skill_id, "target_member": target_member,
                             "panel_cat": panel_cat(sim.game_dir, panel)}
                for member in sim.alive_allies():
                    fire_triggers(sim, "party_burst", member, burst_ctx)
            if not actor.get("extra_turn"):
                grant_extra_turn(sim, actor, skill_id, results)
    else:
        results, blobs, skill_id, wait = resolve_enemy_action(sim, actor, turn, panel)
        actor["next_enemy_skill"] = None
        actor["strong_next"] = False
    apply_panel_acquisition(sim, actor, panel)
    frm = next((i for i, (mid, _) in enumerate(sim.order) if mid == actor["id"]), 0)
    turn, frm, to = move_actor_back(sim, actor["id"], wait)
    timeline_wait = max(0, effective_wait(eff_speed(actor), wait))
    blob = build_action(
        sim, sim.action_no + 1, actor, skill_id, skill_type, main_target,
        results, blobs,
        [{"member": actor["id"], "turn": turn, "reason": 0, "frm": frm, "to": to, "wait": timeline_wait}],
        sim.total_dealt_hp_damage,
    )
    sim.action_no += 1
    sim.actions.append(blob)
    sim.total_turn += 1
    rebuild_order(sim)
    return blob


def do_cannon_action(sim: BattleSim, actor: dict, cannon_number: int) -> bytes:
    cannon = next(
        (
            item
            for item in sim.cannons
            if int(item.get("number", 0)) == cannon_number
            and int(item.get("uses", 0)) > 0
        ),
        None,
    )
    if cannon is None:
        raise ValueError(f"cannon number={cannon_number} is unavailable")
    cannon["uses"] -= 1
    turn = next((t for mid, t in sim.order if mid == actor["id"]), sim.turn)
    cannon_actor = pooled_item_actor(sim, actor)
    cannon_actor["cannon_pooled"] = True
    results, effect_blobs, skill_id, _ = resolve_ally_action(
        sim,
        cannon_actor,
        1,
        None,
        turn,
        panel_for_turn(sim.game_dir, sim.battle_id, turn),
        skill_id_override=int(cannon.get("skill_id", 0) or 0),
    )
    main_target = results[0].get("target") if results else None
    cannon_member = sim.members.get(main_target) if isinstance(main_target, int) else None
    cannon_skill = battle_table(sim.game_dir, "skill").get(str(skill_id), {})
    fire_action_triggers(sim, actor, skill_id, results, cannon_member,
                         panel_for_turn(sim.game_dir, sim.battle_id, turn),
                         is_cannon=True, is_aoe=cannon_skill.get("target") in (4, 5))
    blob = build_action(
        sim,
        sim.action_no + 1,
        actor,
        skill_id,
        None,
        main_target,
        results,
        effect_blobs,
        [],
        sim.total_dealt_hp_damage,
        action_type=3,
        cannon_number=cannon_number,
    )
    sim.action_no += 1
    sim.actions.append(blob)
    return blob


def mix_skill_for_tools(game_dir: Path, tool_a: dict, tool_b: dict) -> tuple[int, float]:
    """Item-mix (skill id, damage multiplier) for two tools.

    The mixed damage slot is 2*sqrt(x*y)/100 from the source skill powers;
    slot values at or above 600 use the superior rank-2 form when present.
    """
    skills = battle_table(game_dir, "skill")
    tool_attrs = combat_map(game_dir).get("tools", {})
    attrs: set[int] = set()
    powers = []
    for tool in (tool_a, tool_b):
        skill = skills.get(str(tool.get("skill_id", 0)), {})
        powers.append(max(int(skill.get("power", 0) or 0), 0))
        for attr in (tool_attrs.get(str(tool.get("tool_id", 0)), {}) or {}).get("attrs", []):
            if attr in (5, 6, 7, 8):
                attrs.add(int(attr))
        for attr in skill.get("attrs") or []:
            mapped = {4: 8, 5: 5, 6: 6, 7: 7}.get(int(attr))
            if mapped is not None:
                attrs.add(mapped)
    if not attrs:
        return 0, 0.0
    mult = 2 * (max(powers[0], 0) * max(powers[1], 0)) ** 0.5 / 100
    entries = combat_map(game_dir).get("mix", [])
    pair = sorted(attrs)[:2]
    while len(pair) < 2:
        pair = pair + pair[-1:]
    rank = 2 if mult * 100 >= 600 else 1
    for entry in entries:
        if entry.get("attrs") == pair and int(entry.get("rank", 1) or 1) == rank:
            return int(entry.get("skill_id", 0) or 0), mult
    for entry in entries:
        if entry.get("attrs") == pair and int(entry.get("rank", 1) or 1) == 1:
            return int(entry.get("skill_id", 0) or 0), mult
    return 0, mult


def do_mix_action(sim: BattleSim, actor: dict, tool_numbers: list[int]) -> bytes:
    """Resolve one item-mix free action (request field 9 mix command).

    Mix damage uses only the mixer's own stats with the mixed skill; the
    source items' traits carry over. Superior forms and field effects stay
    unmodeled (see COMBAT_CHECKLIST.md).
    """
    if len(tool_numbers) < 2:
        raise ValueError("item mix needs two battle tool numbers")
    tools = []
    for number in tool_numbers[:2]:
        tool = next((t for t in sim.tools if t["number"] == number and t["uses"] > 0), None)
        if tool is None:
            raise ValueError(f"battle tool number={number} is unavailable")
        tools.append(tool)
    skill_id, mix_mult = mix_skill_for_tools(sim.game_dir, tools[0], tools[1])
    if not skill_id:
        raise ValueError("no item-mix skill for the selected tools")
    for tool in tools:
        tool["uses"] -= 1
    mixer = dict(actor)
    mixer["buffs"] = []
    carried = []
    for tool in tools:
        carried.extend(tool.get("traits", []))
    battle_tool_traits = prog_table(sim.game_dir, "battle_tool_trait")
    mixer["mods"] = list(actor.get("mods", [])) + trait_mods(
        sim.game_dir, battle_tool_traits, carried
    )
    mixer["mods"].append({"code": "skill_damage", "value": int((mix_mult - 1) * 10000),
                          "conds": [], "direction": 1})
    mixer["mixer"] = True
    mixer["mix_skill_power"] = 100
    turn = next((t for mid, t in sim.order if mid == actor["id"]), sim.turn)
    results, effect_blobs, skill_id, _ = resolve_ally_action(
        sim, mixer, 1, None, turn,
        panel_for_turn(sim.game_dir, sim.battle_id, turn),
        skill_id_override=skill_id,
    )
    main_target = results[0].get("target") if results else None
    mix_member = sim.members.get(main_target) if isinstance(main_target, int) else None
    mix_skill = battle_table(sim.game_dir, "skill").get(str(skill_id), {})
    fire_action_triggers(sim, actor, skill_id, results, mix_member,
                         panel_for_turn(sim.game_dir, sim.battle_id, turn),
                         is_item=True, is_aoe=mix_skill.get("target") in (4, 5))
    blob = build_action(
        sim, sim.action_no + 1, actor, skill_id, None, main_target,
        results, effect_blobs, [], sim.total_dealt_hp_damage,
        tool_number=tools[0]["number"], action_type=1,
    )
    sim.action_no += 1
    sim.actions.append(blob)
    return blob


def do_active_action(sim: BattleSim, actor: dict, active_type: int, main_target: int | None) -> bytes:
    """Resolve one free active-skill action (no timeline advance).

    Captured Totori actives (skill 14002908, limit 2) ride a mode-7
    request carrying field 8 {1=type, 2=target, 3={1=rest}} and never
    combine with free tools/cannons. Rest counts decrement per use and
    exhausted skills stop being emitted in members and setups.
    """
    if actor["side"] != 0:
        raise ValueError("active skills are ally-only")
    active_id = (actor.get("active_skills") or {}).get(active_type, 0)
    if not active_id:
        raise ValueError(f"active skill type={active_type} is unavailable")
    rest = int((actor.get("active_rest") or {}).get(active_type, 0) or 0)
    if rest <= 0:
        raise ValueError(f"active skill type={active_type} is exhausted")
    actor["active_rest"][active_type] = rest - 1
    turn = next((t for mid, t in sim.order if mid == actor["id"]), sim.turn)
    results, effect_blobs, skill_id, _ = resolve_ally_action(
        sim,
        actor,
        1,
        main_target,
        turn,
        panel_for_turn(sim.game_dir, sim.battle_id, turn),
        skill_id_override=active_id,
    )
    if main_target is None and results:
        main_target = results[0].get("target")
    active_member = sim.members.get(main_target) if isinstance(main_target, int) else None
    active_skill = battle_table(sim.game_dir, "skill").get(str(skill_id), {})
    fire_action_triggers(sim, actor, skill_id, results, active_member,
                         panel_for_turn(sim.game_dir, sim.battle_id, turn),
                         is_aoe=active_skill.get("target") in (4, 5))
    blob = build_action(
        sim,
        sim.action_no + 1,
        actor,
        skill_id,
        None,
        main_target,
        results,
        effect_blobs,
        [],
        sim.total_dealt_hp_damage,
        active_skill_type=active_type,
    )
    sim.action_no += 1
    sim.actions.append(blob)
    return blob


def head_actor(sim: BattleSim) -> dict | None:
    """First living member in timeline order, any side."""
    for member_id, _ in sim.order:
        member = sim.members.get(member_id)
        if member is not None and member["alive"]:
            return member
    return None


def advance_round(sim: BattleSim, actor: dict, kind: str, skill_type: int | None, main_target: int | None, tool_number: int | None) -> None:
    """Resolve one player turn: the commanded action, then each enemy whose
    timeline turn falls before the next player turn.

    Captured rounds pair every action with its own setup in the same
    response (setup N precedes action N); free tool/cannon actions carry no
    setups and advance neither order nor enemies. Tool rounds are resolved
    by the caller, never here.
    """
    sim.previous_state = snapshot_state(sim)
    do_action(sim, actor, kind, skill_type, main_target, tool_number)
    if check_battle_end(sim) != 0:
        return
    if actor.get("extra_turn") and actor.get("alive"):
        # Granted extra turn acts immediately: move the actor to the head
        # of the order and offer its setup (with the extra skill in the
        # skill-2 slot) instead of advancing enemies.
        sim.order = [(mid, t) for mid, t in sim.order if mid != actor["id"]]
        sim.order.insert(0, (actor["id"], sim.turn))
        sim.turn += 1
        sim.setup_no += 1
        sim.setups.append(build_setup(sim, actor, sim.setup_no))
        return
    guard = 0
    while guard < 32:
        guard += 1
        head = head_actor(sim)
        if head is None or head["side"] == 0:
            break
        sim.setup_no += 1
        sim.setups.append(
            build_setup(sim, head, sim.setup_no, include_tool_selections=False)
        )
        do_action(sim, head, "auto", None, None, None)
        if check_battle_end(sim) != 0:
            return
    nxt = sim.current_actor()
    if nxt is None or sim.status != 0:
        return
    sim.setup_no += 1
    sim.setups.append(build_setup(sim, nxt, sim.setup_no))


def prime_battle_start(sim: BattleSim) -> int:
    """Resolve enemies placed before the first ally, then hand control over."""
    enemy_actions = 0
    opening_foes: list[int] = []
    for member_id, _ in sim.order:
        member = sim.members.get(member_id)
        if member is None or not member["alive"]:
            continue
        if member["side"] == 0:
            break
        opening_foes.append(member_id)

    for member_id in opening_foes:
        actor = sim.members.get(member_id)
        if actor is None or not actor["alive"] or sim.status != 0:
            continue
        sim.setup_no += 1
        sim.setups.append(
            build_setup(sim, actor, sim.setup_no, include_tool_selections=False)
        )
        turn = next((t for mid, t in sim.order if mid == actor["id"]), sim.turn)
        panel = panel_for_turn(sim.game_dir, sim.battle_id, turn)
        ally_hp_before = {
            member["id"]: member["hp"] for member in sim.alive_allies()
        }
        received_before = sim.received
        deaths_before = sim.deaths
        results, effect_blobs, skill_id, wait = resolve_enemy_action(
            sim, actor, turn, panel
        )
        opening_received = 0
        for result in results:
            target = sim.members.get(result.get("target"))
            if target is None or target["side"] != 0 or result.get("heal") is not None:
                continue
            initial_hp = ally_hp_before.get(target["id"], target["hp"])
            requested_damage = max(int(result.get("damage", 0)), 0)
            actual_damage = min(requested_damage, max(initial_hp - 1, 0))
            if actual_damage < requested_damage:
                sim.opening_damage_capped = True
            result["damage"] = actual_damage
            result["critical_damage"] = (
                actual_damage
                if result.get("critical")
                else max(int(actual_damage * CRIT_MULT), 0)
            )
            result["killed"] = False
            target["hp"] = initial_hp - actual_damage
            target["alive"] = True
            opening_received += actual_damage
        if sim.opening_damage_capped:
            sim.received = received_before + opening_received
            sim.deaths = deaths_before
        actor["next_enemy_skill"] = None
        actor["strong_next"] = False
        frm = next((i for i, (mid, _) in enumerate(sim.order) if mid == actor["id"]), 0)
        moved_turn, frm, to = move_actor_back(sim, actor["id"], wait)
        timeline_wait = max(0, effective_wait(eff_speed(actor), wait))
        sim.action_no += 1
        sim.actions.append(
            build_action(
                sim,
                sim.action_no,
                actor,
                skill_id,
                None,
                None,
                results,
                effect_blobs,
                [{"member": actor["id"], "turn": moved_turn, "reason": 0, "frm": frm, "to": to, "wait": timeline_wait}],
                sim.total_dealt_hp_damage,
            )
        )
        sim.total_turn += 1
        enemy_actions += 1
        rebuild_order(sim)
        if check_battle_end(sim) != 0:
            return enemy_actions

    if sim.status == 0:
        actor = sim.current_actor()
        if actor is None:
            sim.status = 2
            return enemy_actions
        # A successful battle start presents the player at the head of the
        # timeline after any opening enemy actions.
        actor_index = next(
            (i for i, (member_id, _) in enumerate(sim.order) if member_id == actor["id"]),
            None,
        )
        if actor_index is not None and actor_index:
            sim.order.insert(0, sim.order.pop(actor_index))
        sim.setup_no += 1
        sim.setups.append(
            build_setup(sim, actor, sim.setup_no, include_tool_selections=False)
        )
    return enemy_actions


def next_setup(sim: BattleSim) -> None:
    actor = sim.current_actor()
    if actor is None or sim.status != 0:
        return
    sim.setup_no = sim.action_no + 1
    sim.setups.append(build_setup(sim, actor, sim.setup_no))


def quest_score_rank(quest: dict, score: int) -> tuple[int, list[int]]:
    best = 1
    reward_ids: list[int] = []
    for entry in quest.get("ranks", []):
        try:
            if score >= int(entry.get("score") or 0) and int(entry.get("rank") or 1) >= best:
                best = int(entry.get("rank") or 1)
                reward_ids = [int(v) for v in entry.get("rewards") or []]
        except (TypeError, ValueError):
            continue
    return best, reward_ids


def roll_drops(game_dir: Path, rng: random.Random, drop_ids: list[int]) -> list[tuple[int, int, int]]:
    tables = battle_table(game_dir, "drop_reward_set")
    out: list[tuple[int, int, int]] = []
    for drop_id in drop_ids:
        for pool in tables.get(str(drop_id), []):
            if rng.randint(0, 99) >= int(pool.get("rate") or 0):
                continue
            for reward in pool.get("rewards") or []:
                lo, hi = int(reward.get("min") or 0), int(reward.get("max") or 0)
                qty = rng.randint(min(lo, hi), max(lo, hi)) if hi else lo
                if qty > 0:
                    out.append((int(reward["type"]), int(reward["id"]), qty))
    return out


def compute_finish(sim: BattleSim) -> tuple[bytes, bytes]:
    """Build (quest_result, changed_resources) for a won battle."""
    game_dir = sim.game_dir
    quest = sim.quest
    turns = sim.request_count + 1
    turn_score = max(SCORE_TURN_BASE - SCORE_TURN_PER_TURN * turns, 0)
    dmg_score = round(sim.max_dealt * SCORE_MAX_DMG_FACTOR)
    recv_score = max(SCORE_RECEIVED_BASE - sim.received * SCORE_RECEIVED_PER_HP, 0)
    dead_score = max(SCORE_DEAD_BASE - sim.deaths * SCORE_DEAD_PER_ALLY, 0)
    total_score = turn_score + dmg_score + recv_score + dead_score
    rank, rank_reward_sets = quest_score_rank(quest, total_score)
    reward_tables = battle_table(game_dir, "reward_set")
    rewards: list[tuple[int, int, int]] = []
    bonus: set[tuple[int, int]] = set()
    for set_id in rank_reward_sets[:1]:
        for entry in reward_tables.get(str(set_id), []):
            key = (int(entry["type"]), int(entry["id"]))
            rewards.append((key[0], key[1], int(entry["qty"])))
            if key[0] != 3:
                # Captured rank-set item rewards carry is_bonus/bonus_rate;
                # Cole, drops, and first-clear rewards stay bare.
                bonus.add(key)
    for rtype, rid, qty in roll_drops(game_dir, sim.rng, quest.get("drops", [])):
        rewards.append((rtype, rid, qty))
    quest_result = bytearray()
    for rtype, rid, qty in rewards:
        blob = bytearray(write_field(1, 0, rtype) + write_field(2, 0, rid) + write_field(3, 0, qty))
        if (rtype, rid) in bonus:
            blob.extend(write_field(8, 0, 1) + write_field(12, 0, 100))
        quest_result.extend(write_field(1, 2, bytes(blob)))
    first_clear: list[tuple[int, int, int]] = []
    quest_states = profile_quest_states(sim.profile_plaintext)
    prior = quest_states.get(sim.ref_id, {}).get("clear", 0)
    if sim.kind == "quest" and prior == 0 and quest.get("first") is not None:
        for entry in reward_tables.get(str(quest["first"]), []):
            first_clear.append((int(entry["type"]), int(entry["id"]), int(entry["qty"])))
        for rtype, rid, qty in first_clear:
            quest_result.extend(
                write_field(
                    2, 2, write_field(1, 0, rtype) + write_field(2, 0, rid) + write_field(3, 0, qty)
                )
            )
    score_detail = (
        write_field(1, 0, turns)
        + write_field(2, 0, turn_score)
        + write_field(3, 0, sim.max_dealt)
        + write_field(4, 0, dmg_score)
        + write_field(7, 0, sim.received)
        + write_field(8, 0, recv_score)
        + write_field(9, 0, sim.deaths)
        + write_field(10, 0, dead_score)
        + write_field(11, 0, total_score)
    )
    quest_result.extend(write_field(3, 2, score_detail))
    quest_result.extend(
        write_field(4, 2, write_field(1, 0, total_score) + write_field(2, 0, rank))
    )
    mission_ids = list(quest.get("missions", []) or [])
    # Captured results omit an empty mission_result; only send it with content.
    if mission_ids:
        quest_result.extend(
            write_field(
                5, 2,
                b"".join(write_field(2, 0, mid) for mid in mission_ids),
            )
        )
    sim.finish_bundle = {
        "rewards": rewards,
        "first_clear": first_clear,
        "rank": rank,
        "score": total_score,
        "missions": mission_ids,
        "turns": turns,
        "score_detail": score_detail,
    }
    return bytes(quest_result), build_finish_changed(sim)


def profile_quest_states(profile_plaintext: bytes) -> dict[int, dict]:
    out: dict[int, dict] = {}
    try:
        resources = profile_resources(profile_plaintext)
    except (ValueError, StopIteration):
        return out
    for number, wire, value in read_wire_fields(resources):
        if number != 22 or wire != 2:
            continue
        record = bytes(value)
        out[varint_field(record, 1, -1)] = {
            "clear": varint_field(record, 2, 0),
            "missions": [
                int(v) for n, w, v in read_wire_fields(record) if n == 4 and w == 0
            ],
            "rank": varint_field(record, 7, 0),
            "min_turns": varint_field(record, 8, 0),
        }
    return out


def build_finish_changed(sim: "BattleSim") -> bytes:
    bundle = sim.finish_bundle
    game_dir = sim.game_dir
    resources = profile_resources(sim.profile_plaintext)
    out = bytearray()
    if sim.kind == "quest":
        states = profile_quest_states(sim.profile_plaintext)
        prior = states.get(sim.ref_id, {"clear": 0, "missions": [], "rank": 0, "min_turns": 0})
        merged_missions = sorted(set(prior.get("missions", [])) | set(bundle["missions"]))
        improved = not prior.get("min_turns") or bundle["turns"] < prior["min_turns"]
        record = bytearray(write_field(1, 0, sim.ref_id))
        record.extend(write_field(2, 0, prior.get("clear", 0) + 1))
        record.extend(b"".join(write_field(4, 0, mid) for mid in merged_missions))
        # Captured quest states carry the run's high-score detail; an
        # unknown min_total_turn shape is worse than a fresh one, so only
        # persist min turns on first clear or improvement.
        record.extend(write_field(6, 2, bundle["score_detail"]))
        record.extend(write_field(7, 0, max(prior.get("rank", 0), bundle["rank"])))
        if improved:
            record.extend(write_field(8, 0, bundle["turns"]))
        elif prior.get("min_turns"):
            record.extend(write_field(8, 0, prior["min_turns"]))
        out.extend(write_field(22, 2, bytes(record)))
    grants: dict[tuple[int, int], int] = {}
    for rtype, rid, qty in bundle["rewards"] + bundle["first_clear"]:
        grants[(rtype, rid)] = grants.get((rtype, rid), 0) + qty
    cole_gain = grants.pop((3, 1), 0)
    if cole_gain:
        # Echo the full stored Status record with only Cole and its
        # timestamp updated. A minimal record drops rank/exp/stamina fields
        # the client needs for post-battle rank recomputation.
        status = next(
            (bytes(v) for n, w, v in read_wire_fields(resources) if n == 6 and w == 2),
            b"",
        )
        merged = bytearray()
        seen_cole = False
        seen_stamp = False
        for number, wire, value in read_wire_fields(status):
            if number == 3 and wire == 0 and not seen_cole:
                merged.extend(write_field(3, 0, int(value) + cole_gain))
                seen_cole = True
            elif number == 7 and wire == 2 and not seen_stamp:
                merged.extend(write_field(7, 2, write_timestamp_message()))
                seen_stamp = True
            else:
                merged.extend(write_field(number, wire, value))
        if not seen_cole:
            merged.extend(write_field(3, 0, cole_gain))
        if not seen_stamp:
            merged.extend(write_field(7, 2, write_timestamp_message()))
        out.extend(write_field(6, 2, bytes(merged)))
    for (rtype, rid), qty in sorted(grants.items()):
        if rtype != 5:
            continue
        current = next(
            (
                bytes(v)
                for n, w, v in read_wire_fields(resources)
                if n == 3 and w == 2 and varint_field(bytes(v), 1, -1) == rid
            ),
            b"",
        )
        have = varint_field(current, 2, 0)
        life = varint_field(current, 3, have)
        out.extend(
            write_field(
                3, 2, write_field(1, 0, rid) + write_field(2, 0, have + qty) + write_field(3, 0, life + qty)
            )
        )
    for member in sim.members.values():
        if member["side"] != 0:
            continue
        current = next(
            (
                bytes(v)
                for n, w, v in read_wire_fields(resources)
                if n == 2 and w == 2 and varint_field(bytes(v), 1, -1) == member["character_id"]
            ),
            b"",
        )
        if not current:
            continue
        new_exp = capped_quest_exp(
            game_dir, varint_field(current, 12, 0), quest_exp_gain(sim)
        )
        if new_exp is None:
            continue
        merged = bytearray()
        replaced = False
        for number, wire, value in read_wire_fields(current):
            if number == 12 and wire == 0:
                merged.extend(write_field(12, 0, new_exp))
                replaced = True
            else:
                merged.extend(write_field(number, wire, value))
        if not replaced:
            merged.extend(write_field(12, 0, new_exp))
        out.extend(write_field(2, 2, bytes(merged)))
    return bytes(out)


def quest_exp_gain(sim: "BattleSim") -> int:
    return int(sim.quest.get("exp", 0) or 0)


def character_level_cap_exp(game_dir: Path) -> int | None:
    """Highest character EXP threshold, or None when the table is missing."""
    try:
        table = prog_table(game_dir, "character_level")
    except (OSError, ValueError):
        return None
    best: int | None = None
    for row in table.values():
        try:
            exp = int(row["exp"])
        except (KeyError, TypeError, ValueError):
            continue
        if best is None or exp > best:
            best = exp
    return best


def capped_quest_exp(game_dir: Path, current_exp: int, gain: int) -> int | None:
    """Apply a quest EXP gain capped at max level. Returns None (omit the
    update, matching captures) when already capped or when nothing changes."""
    if gain <= 0:
        return None
    cap = character_level_cap_exp(game_dir)
    if cap is None:
        return current_exp + gain
    if current_exp >= cap:
        return None
    return min(current_exp + gain, cap)


def is_quest_battle_start_request(data: bytes) -> bool:
    # Live clients append extra fields beyond the reference schema (field 4
    # plus a repeated field 1 observed 2026-09-26). Require only a quest_id
    # varint; unknown fields are ignored. Quest lookup downstream rejects
    # anything that is not a real quest battle start.
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    return any(number == 1 and wire == 0 for number, wire, value in fields)


def is_battle_attack_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    kinds = set()
    mode = 0
    cannon_numbers = []
    for number, wire, value in fields:
        if number in (2, 3, 4, 6, 7, 8, 9) and wire == 2:
            try:
                read_wire_fields(bytes(value))
            except ValueError:
                return False
            if number != 6:
                kinds.add(number)
        elif number == 10 and wire == 2:
            try:
                command = read_wire_fields(bytes(value))
            except ValueError:
                return False
            if not command or any(n != 1 or w != 0 for n, w, _ in command):
                return False
            cannon_numbers.extend(int(v) for _, _, v in command)
        elif number == 1 and wire == 0:
            mode = int(value)
        else:
            return False
    return bool(
        kinds & {2, 3, 8, 9}
        or (mode == CANNON_ATTACK_MODE and cannon_numbers and all(n > 0 for n in cannon_numbers))
        or (mode == 5 and 7 in kinds)
        or (mode == 3 and 4 in kinds)
    )


def is_battle_skip_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    seen = set()
    for number, wire, value in fields:
        if number in (1, 2, 5) and wire == 0:
            seen.add(number)
        else:
            return False
    return 1 in seen


def is_exploration_battle_start_request(data: bytes) -> bool:
    # Same liberality as quest battle starts: live clients may append
    # fields beyond the reference schema. Area/gacha lookup downstream
    # rejects anything that is not a real battle start.
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    return any(number == 1 and wire == 0 for number, wire, value in fields)


def is_gacha_battle_start_request(data: bytes) -> bool:
    return is_exploration_battle_start_request(data)


def is_empty_request(data: bytes) -> bool:
    return data == b""


def parse_battle_start_refs(plaintext: bytes) -> tuple[int, int]:
    """Return (quest_id, party_number) from a start request.

    Live clients repeat field 1; the first occurrence wins as quest_id.
    """
    quest_id = 0
    party_number = 1
    for number, wire, value in read_wire_fields(plaintext):
        if wire != 0:
            continue
        if number == 1 and not quest_id:
            quest_id = int(value)
        elif number == 2:
            party_number = int(value)
    if not quest_id:
        raise ValueError("battle start request has no quest_id")
    return quest_id, party_number

def load_party(game_dir: Path, profile_plaintext: bytes, party_number: int) -> tuple[list[dict], list[dict], int]:
    """Return (members, tools, leader_position) for battle party type 1."""
    resources = profile_resources(profile_plaintext)
    party = None
    for number, wire, value in read_wire_fields(resources):
        if number != 9 or wire != 2:
            continue
        record = bytes(value)
        if varint_field(record, 5, -1) == 1 and varint_field(record, 1, -1) == party_number:
            party = record
            break
    if party is None:
        raise ValueError(f"no battle party number={party_number}")
    leader_position = varint_field(party, 6, 1)
    member_records: dict[tuple[int, int, int], bytes] = {}
    for number, wire, value in read_wire_fields(resources):
        if number != 24 or wire != 2:
            continue
        record = bytes(value)
        key = (varint_field(record, 1, -1), varint_field(record, 2, -1), varint_field(record, 3, -1))
        if key[0] == 1 and key[1] == party_number:
            member_records[key] = record
    char_master = prog_table(game_dir, "character")
    growth_master = battle_table(game_dir, "character_growth")
    rarity_master = prog_table(game_dir, "character_common_rarity")
    memoria_master = prog_table(game_dir, "memoria")
    equipment_master = prog_table(game_dir, "equipment_tool")
    equipment_trait_master = prog_table(game_dir, "equipment_tool_trait")
    battle_tool_master = prog_table(game_dir, "battle_tool")
    char_records: dict[int, bytes] = {}
    for number, wire, value in read_wire_fields(resources):
        if number != 2 or wire != 2:
            continue
        record = bytes(value)
        char_records[varint_field(record, 1, -1)] = record
    tools: dict[int, bytes] = {}
    for number, wire, value in read_wire_fields(resources):
        if number != 11 or wire != 2:
            continue
        record = bytes(value)
        tools[varint_field(record, 1, -1)] = record
    equipment_records: dict[int, bytes] = {}
    for number, wire, value in read_wire_fields(resources):
        if number != 4 or wire != 2:
            continue
        record = bytes(value)
        equipment_records[varint_field(record, 1, -1)] = record
    memoria_records: dict[int, bytes] = {}
    for number, wire, value in read_wire_fields(resources):
        if number != 29 or wire != 2:
            continue
        record = bytes(value)
        memoria_records[varint_field(record, 1, -1)] = record
    members = []
    for position in range(1, 6):
        record = member_records.get((1, party_number, position))
        if record is None:
            continue
        character_id = None
        for number, wire, value in read_wire_fields(record):
            if number == 4 and wire == 2:
                inner = read_wire_fields(bytes(value))
                character_id = next((int(v) for n, w, v in inner if n == 1), None)
        if not character_id or character_id not in char_records:
            continue
        char_record = char_records[character_id]
        master = char_master.get(str(character_id), {})
        stats = ally_battle_stats(game_dir, char_record, master, growth_master, rarity_master)
        equipment = []
        equipment_buffs: list[dict] = []
        equipment_abilities: list[int] = []
        for slot, party_field, character_field in ((1, 5, 3), (2, 6, 4), (3, 7, 5)):
            entity_id = wrapped_varint_field(record, party_field)
            if entity_id is None:
                entity_id = wrapped_varint_field(char_record, character_field)
            if entity_id is None:
                continue
            equipment_record = equipment_records.get(entity_id)
            if equipment_record is None:
                continue
            tool_id = varint_field(equipment_record, 2, 0)
            equipment_row = equipment_master.get(str(tool_id), {})
            traits = []
            for field_number, field_wire, field_value in read_wire_fields(equipment_record):
                if field_number != 5 or field_wire != 2:
                    continue
                trait = bytes(field_value)
                trait_id = varint_field(trait, 1, 0)
                rank = max(varint_field(trait, 2, 1), 1)
                traits.append((trait_id, rank))
                trait_row = equipment_trait_master.get(str(trait_id), {})
                trait_abilities = trait_row.get("ability_ids") or []
                if trait_abilities:
                    equipment_abilities.append(
                        int(trait_abilities[min(rank, len(trait_abilities)) - 1])
                    )
            equipment_buffs.extend(equipment_row.get("status_buffs") or [])
            equipment_abilities.extend(int(value) for value in equipment_row.get("ability_ids") or [])
            equipment.append(
                {
                    "slot": slot,
                    "entity_id": entity_id,
                    "tool_id": tool_id,
                    "traits": traits,
                    "master": equipment_row,
                }
            )
        stats["stats"] = add_equipment_status_buffs(stats["stats"], equipment_buffs)
        abilities = []
        memoria_entity_id = wrapped_varint_field(record, 8)
        if memoria_entity_id is None:
            memoria_entity_id = wrapped_varint_field(char_record, 28)
        memoria_record = memoria_records.get(memoria_entity_id, b"") if memoria_entity_id is not None else b""
        memoria_id = varint_field(memoria_record, 2, -1) if memoria_record else -1
        memoria_row = memoria_master.get(str(memoria_id), {})
        if memoria_record and memoria_row:
            stats["stats"], abilities = add_memoria_status_buffs(
                game_dir, stats["stats"], memoria_record, memoria_row
            )
        members.append(
            {
                "record": char_record,
                "master": master,
                "character_id": character_id,
                "stats": stats["stats"],
                "level": stats["level"],
                "role": master.get("role"),
                "attrs": character_elements(master),
                "tags": master.get("tag_ids") or [],
                "series": master.get("series_id"),
                "hp": stats["stats"]["hp"],
                "leader": position == leader_position,
                "abilities": abilities,
                "memoria_ability_ids": list(abilities),
                "memoria_limit_break": varint_field(memoria_record, 3, 0) if memoria_record else 0,
                "character_ability_ids": list(master.get("ability_ids") or []),
                "equipment": equipment,
                "equipment_abilities": equipment_abilities,
                "equipment_trait_rows": equipment_trait_master,
                "memoria_entity_id": memoria_entity_id,
                "memoria_id": memoria_id if memoria_record else None,
            }
        )
    if not members:
        raise ValueError(f"battle party number={party_number} has no members")
    tool_entries = []
    for number, wire, value in read_wire_fields(party):
        if number != 4:
            continue
        if wire == 0:
            tool_entries.append(int(value))
        elif wire == 2:
            offset = 0
            raw = bytes(value)
            while offset < len(raw):
                entity_id, offset = read_varint(raw, offset)
                tool_entries.append(entity_id)
    tool_blobs = []
    for index, entity_id in enumerate(tool_entries[:5], 1):
        record = tools.get(entity_id)
        if record is None:
            continue
        tool_id = varint_field(record, 2, 0)
        traits = []
        for number, wire, value in read_wire_fields(record):
            if number != 5 or wire != 2:
                continue
            inner = read_wire_fields(bytes(value))
            trait_id = next((int(v) for n, w, v in inner if n == 1), 0)
            rank = next((int(v) for n, w, v in inner if n == 2), 0)
            traits.append((trait_id, rank))
        tool_row = battle_tool_master.get(str(tool_id), {})
        tool_blobs.append(
            {
                "number": index,
                "entity": entity_id,
                "tool_id": tool_id,
                "skill_id": int(tool_row.get("skill_id") or 0),
                "traits": traits,
                "uses": int(tool_row.get("usage_count") or 0),
            }
        )
    return members, tool_blobs, leader_position


def selected_ship_party(profile_plaintext: bytes) -> tuple[bytes | None, int]:
    resources = profile_resources(profile_plaintext)
    parties = [
        bytes(value)
        for number, wire, value in read_wire_fields(resources)
        if number == 67 and wire == 2
    ]
    parties.sort(key=lambda record: varint_field(record, 1, 1))
    ship_party = next(
        (
            record
            for record in parties
            if packed_varint_field(record, 2)
            or wrapped_varint_field(record, 3) is not None
            or packed_varint_field(record, 4)
            or packed_varint_field(record, 5)
        ),
        None,
    )
    ship_exp = 0
    ship_records = [
        bytes(value)
        for number, wire, value in read_wire_fields(resources)
        if number == 66 and wire == 2
    ]
    if ship_records:
        ship_exp = varint_field(ship_records[0], 2, 0)
    return ship_party, ship_exp


def ship_support_apply_rate(game_dir: Path, profile_plaintext: bytes) -> int:
    _, ship_exp = selected_ship_party(profile_plaintext)
    if not ship_exp:
        return 10000
    levels = prog_table(game_dir, "ship_level")
    level = max(
        (
            row
            for row in levels.values()
            if int(row.get("exp", 0) or 0) <= ship_exp
        ),
        key=lambda row: int(row.get("exp", 0) or 0),
        default={},
    )
    return int(level.get("support_ability_apply_rate", 10000) or 10000)


def load_cannons(game_dir: Path, profile_plaintext: bytes) -> list[dict]:
    """Resolve selected ship-party cannon tools into their captured battle form."""
    ship_party, _ = selected_ship_party(profile_plaintext)
    if ship_party is None:
        return []
    resources = profile_resources(profile_plaintext)

    owned_tools = {
        varint_field(bytes(value), 1, -1): bytes(value)
        for number, wire, value in read_wire_fields(resources)
        if number == 68 and wire == 2
    }
    ship_tool_master = prog_table(game_dir, "ship_tool")
    level_master = prog_table(game_dir, "ship_tool_level")
    cannons = []
    for slot, entity_id in enumerate(packed_varint_field(ship_party, 5), 1):
        record = owned_tools.get(entity_id)
        if record is None:
            continue
        tool_id = varint_field(record, 2, 0)
        tool_exp = varint_field(record, 3, 0)
        tool_level = max(
            (
                int(key)
                for key, row in level_master.items()
                if int(row.get("exp", 0) or 0) <= tool_exp
            ),
            default=1,
        )
        master = ship_tool_master.get(str(tool_id), {})
        skill_ids = master.get("skill_ids") or []
        usage_counts = master.get("usage_counts") or []
        index = min(max(tool_level - 1, 0), len(skill_ids) - 1) if skill_ids else -1
        if index < 0:
            continue
        cannons.append(
            {
                "number": slot,
                "tool_id": tool_id,
                "skill_id": int(skill_ids[index]),
                "uses": int(usage_counts[index]) if index < len(usage_counts) else 0,
            }
        )
    return cannons


def apply_subspace_support_stats(
    game_dir: Path, profile_plaintext: bytes, members: list[dict]
) -> None:
    """Apply approximate ship-party character and Memoria support from profile."""
    ship_party, _ = selected_ship_party(profile_plaintext)
    if ship_party is None or not members:
        return
    resources = profile_resources(profile_plaintext)
    support_character_ids = packed_varint_field(ship_party, 2)
    support_memoria_entities = []
    main_memoria_entity = wrapped_varint_field(ship_party, 3)
    if main_memoria_entity is not None:
        support_memoria_entities.append(main_memoria_entity)
    support_memoria_entities.extend(packed_varint_field(ship_party, 4))

    character_records = {
        varint_field(bytes(value), 1, -1): bytes(value)
        for number, wire, value in read_wire_fields(resources)
        if number == 2 and wire == 2
    }
    memoria_records = {
        varint_field(bytes(value), 1, -1): bytes(value)
        for number, wire, value in read_wire_fields(resources)
        if number == 29 and wire == 2
    }
    equipment_records = {
        varint_field(bytes(value), 1, -1): bytes(value)
        for number, wire, value in read_wire_fields(resources)
        if number == 4 and wire == 2
    }
    character_master = prog_table(game_dir, "character")
    growth_master = battle_table(game_dir, "character_growth")
    rarity_master = prog_table(game_dir, "character_common_rarity")
    equipment_master = prog_table(game_dir, "equipment_tool")
    memoria_master = prog_table(game_dir, "memoria")
    support_totals = {stat: 0 for stat in STATUS_TYPE_TO_STAT.values()}
    for character_id in support_character_ids:
        record = character_records.get(character_id)
        master = character_master.get(str(character_id), {})
        if not record or not master:
            continue
        support_stats = ally_battle_stats(
            game_dir, record, master, growth_master, rarity_master
        )["stats"]
        support_equipment_buffs = []
        for field_number in (3, 4, 5):
            entity_id = wrapped_varint_field(record, field_number)
            equipment = equipment_records.get(entity_id) if entity_id is not None else None
            if equipment is None:
                continue
            tool_id = varint_field(equipment, 2, 0)
            support_equipment_buffs.extend(
                equipment_master.get(str(tool_id), {}).get("status_buffs") or []
            )
        support_stats = add_equipment_status_buffs(
            support_stats, support_equipment_buffs
        )
        personal_memoria_id = wrapped_varint_field(record, 28)
        personal_memoria = (
            memoria_records.get(personal_memoria_id)
            if personal_memoria_id is not None
            else None
        )
        if personal_memoria:
            memoria_id = varint_field(personal_memoria, 2, -1)
            memoria_row = memoria_master.get(str(memoria_id), {})
            if memoria_row:
                support_stats, _ = add_memoria_status_buffs(
                    game_dir, support_stats, personal_memoria, memoria_row
                )
        for stat in support_totals:
            support_totals[stat] += int(support_stats.get(stat, 0))

    # Captures show this rate on the owning ship-level row; applying half of
    # it to pooled support stats is an estimate, while equipped Memoria values
    # are read directly from the selected ship-party entity references.
    stat_scale = ship_support_apply_rate(game_dir, profile_plaintext) // 2
    for member in members:
        for stat, value in support_totals.items():
            if stat == "speed":
                continue
            member["stats"][stat] = int(member["stats"].get(stat, 0)) + value * stat_scale // 10000
        support_rate = ship_support_apply_rate(game_dir, profile_plaintext) // 4
        for entity_id in support_memoria_entities:
            record = memoria_records.get(entity_id)
            if not record:
                continue
            memoria_id = varint_field(record, 2, -1)
            master = memoria_master.get(str(memoria_id), {})
            if master:
                member["stats"], _ = add_memoria_status_buffs(
                    game_dir, member["stats"], record, master, support_rate
                )
        member["hp"] = member["stats"]["hp"]


def build_tool_blob(tool: dict) -> bytes:
    out = bytearray(write_field(1, 0, tool["number"]))
    out.extend(write_field(2, 0, tool.get("tool_id", 0)))
    for trait_id, rank in tool.get("traits", []):
        out.extend(
            write_field(
                5, 2, write_field(1, 0, trait_id) + write_field(2, 0, rank)
            )
        )
    if tool.get("uses", 0):
        out.extend(write_field(4, 0, tool["uses"]))
    return bytes(out)


def build_cannon_blob(cannon: dict) -> bytes:
    out = bytearray(
        write_field(1, 0, cannon["number"])
        + write_field(2, 0, cannon["tool_id"])
        + write_field(3, 0, cannon["skill_id"])
    )
    if cannon.get("uses", 0):
        out.extend(write_field(4, 0, cannon["uses"]))
    return bytes(out)


def fixed_party_members(game_dir: Path, fixed_party_id: int) -> tuple[list[dict], list[dict], int]:
    table = battle_table(game_dir, "fixed_party")
    spec = table.get(str(fixed_party_id))
    if spec is None:
        raise ValueError(f"unknown fixed_party_id={fixed_party_id}")
    char_master = prog_table(game_dir, "character")
    growth_master = battle_table(game_dir, "character_growth")
    rarity_master = prog_table(game_dir, "character_common_rarity")
    members = []
    for position, entry in enumerate(spec.get("members") or [], 1):
        master = char_master.get(str(entry["id"]), {})
        record = (
            write_field(1, 0, entry["id"])
            + write_field(8, 0, 5)
            + write_field(9, 0, 5)
            + write_field(11, 0, entry.get("rarity") or 1)
        )
        stats = ally_battle_stats(game_dir, record, master, growth_master, rarity_master)
        members.append(
            {
                "record": record,
                "master": master,
                "character_id": int(entry["id"]),
                "stats": stats["stats"],
                "hp": stats["stats"]["hp"],
                "leader": position == int(spec.get("leader") or 1),
                "abilities": [],
            }
        )
    if not members:
        raise ValueError(f"fixed party {fixed_party_id} has no members")
    return members, [], int(spec.get("leader") or 1)


def start_battle_state(
    game_dir: Path,
    profile_plaintext: bytes,
    kind: str,
    ref_id: int,
    party_number: int,
    previous_formation: bytes | None = None,
) -> tuple[bytes, bytes | None, str]:
    """Start a battle. Returns (response_plaintext, persist_plaintext|None, log)."""
    global _ACTIVE
    quest: dict = {}
    battle_id = 0
    exp_gain = 0
    cole_gain = 0
    if kind == "quest":
        quests = battle_table(game_dir, "quest")
        quest = quests.get(str(ref_id), {})
        if not quest:
            raise ValueError(f"unknown quest_id={ref_id}")
        battle_id = int(quest["battle"])
        members, tools, _ = load_party(game_dir, profile_plaintext, party_number)
    elif kind == "exploration":
        areas = battle_table(game_dir, "exploration_area")
        options = areas.get(str(ref_id))
        if not options:
            raise ValueError(f"no battles for area_id={ref_id}")
        total = sum(int(o.get("weight") or 1) for o in options)
        pick = random.Random().uniform(0, total)
        chosen = options[-1]
        for option in options:
            pick -= int(option.get("weight") or 1)
            if pick <= 0:
                chosen = option
                break
        battle_id = int(chosen["battle"])
        exp_gain = int(chosen.get("exp") or 0)
        cole_gain = int(chosen.get("cole") or 0)
        quest = {"exp": exp_gain, "drops": [], "missions": [], "ranks": []}
        members, tools, _ = load_party(game_dir, profile_plaintext, party_number)
    elif kind == "gacha":
        table = battle_table(game_dir, "gacha_battle")
        spec = table.get(str(ref_id))
        if spec is None or not spec.get("battle"):
            raise ValueError(f"unknown gacha_battle_id={ref_id}")
        battle_id = int(spec["battle"])
        quest = {"exp": 0, "drops": [], "missions": [], "ranks": []}
        if spec.get("fixed_party") is not None:
            members, tools, _ = fixed_party_members(game_dir, int(spec["fixed_party"]))
        else:
            members, tools, _ = load_party(game_dir, profile_plaintext, party_number)
    else:
        raise ValueError(f"unknown battle kind={kind}")
    if kind in ("quest", "exploration"):
        apply_subspace_support_stats(game_dir, profile_plaintext, members)
    battles = battle_table(game_dir, "battle")
    battle = battles.get(str(battle_id))
    if battle is None:
        raise ValueError(f"unknown battle_id={battle_id}")
    waves = battle.get("waves") or []
    if not waves:
        raise ValueError(f"battle_id={battle_id} has no waves")
    sim = BattleSim(
        game_dir, kind, ref_id, party_number, members, battle_id,
        [int(w) for w in waves], list(battle.get("panels") or []),
        battle.get("countdown"), quest,
        profile_plaintext=profile_plaintext,
    )
    sim.tools = tools
    sim.profile_plaintext = profile_plaintext
    sim.cannons = load_cannons(game_dir, profile_plaintext)
    ship_memoria = build_ship_main_memoria_blob(game_dir, profile_plaintext)
    if ship_memoria is not None:
        for member in sim.members.values():
            if member["side"] == 0:
                member["ship_memoria"] = ship_memoria
    sim.start_state = build_battle_start_state(sim)
    if previous_formation is not None:
        sim.previous_formation = previous_formation
    else:
        sim.previous_formation = default_formation(sim)
    sim.wave_starts.append(
        write_field(1, 0, sim.request_count + 1) + write_field(2, 2, build_state(sim))
    )
    _ACTIVE = {"sim": sim, "kind": kind, "ref_id": ref_id}
    sim.setup_no = 0
    pre_opening_state = deepcopy(sim.__dict__)
    opening_enemy_actions = prime_battle_start(sim)
    opening_enemy_fallback = False
    if sim.status == 2:
        # Enemy opening damage is estimated and can be wildly high for weak
        # profiles. Preserve a playable start rather than returning a defeat
        # before the client ever receives a player setup.
        sim.__dict__.clear()
        sim.__dict__.update(pre_opening_state)
        sim.status = 0
        actor = sim.current_actor()
        if actor is None:
            raise ValueError("battle has no living player member")
        actor_index = next(
            (i for i, (member_id, _) in enumerate(sim.order) if member_id == actor["id"]),
            None,
        )
        if actor_index is not None and actor_index:
            sim.order.insert(0, sim.order.pop(actor_index))
        sim.wave_starts = [
            write_field(1, 0, sim.request_count + 1) + write_field(2, 2, build_state(sim))
        ]
        sim.setup_no = 1
        sim.setups = [
            build_setup(sim, actor, sim.setup_no, include_tool_selections=False)
        ]
        opening_enemy_actions = 0
        opening_enemy_fallback = True
    history = build_history(sim, include_prev=False, include_formation=previous_formation is not None)
    sim.sent_waves, sim.sent_setups, sim.sent_actions = (
        len(sim.wave_starts), len(sim.setups), len(sim.actions),
    )
    quest_blob = bytearray()
    if kind == "quest":
        quest_blob.extend(write_field(1, 0, ref_id))
    quest_blob.extend(write_field(3, 2, sim.start_txid.encode("ascii")))
    quest_blob.extend(write_field(4, 2, write_field(1, 0, party_number)))
    response = bytearray(write_field(1, 2, history))
    start_changed_resources = build_start_changed_resources(profile_plaintext)
    if start_changed_resources:
        response.extend(write_field(2, 2, start_changed_resources))
    response.extend(write_field(3, 2, bytes(quest_blob)))
    persist = None
    stamina_cost = int(quest.get("stamina", 0) or 0) if kind == "quest" else 0
    if stamina_cost:
        resources = profile_resources(profile_plaintext)
        status = next(
            (bytes(v) for n, w, v in read_wire_fields(resources) if n == 6 and w == 2), b""
        )
        stamina = varint_field(status, 6, 0) - stamina_cost
        persist = write_field(
            1, 2,
            write_field(
                6, 2,
                write_field(6, 0, max(stamina, 0)) + write_field(7, 2, write_timestamp_message()),
            ),
        )
    return (
        bytes(response),
        persist,
        f"LOCAL-BATTLE-START kind={kind} ref={ref_id} battle={battle_id} members={len(members)} party={party_number} opening_enemy_actions={opening_enemy_actions} opening_enemy_damage_capped={int(sim.opening_damage_capped)} opening_enemy_fallback={int(opening_enemy_fallback)}",
    )


def attack_battle(
    game_dir: Path, profile_plaintext: bytes, request_plaintext: bytes
) -> tuple[bytes, bytes | None, str]:
    """Resolve one attack round. Returns (response_plaintext, None, log)."""
    global _ACTIVE
    if _ACTIVE is None:
        raise ValueError("no active battle")
    sim: BattleSim = _ACTIVE["sim"]
    sim.game_dir = game_dir
    sim.profile_plaintext = profile_plaintext
    skill_type: int | None = None
    main_target: int | None = None
    active_skill_type: int | None = None
    active_target: int | None = None
    tool_numbers: list[int] = []
    mix_numbers: list[int] = []
    cannon_numbers: list[int] = []
    mode = 0
    formation = None
    for number, wire, value in read_wire_fields(request_plaintext):
        if number == 2 and wire == 2:
            command = read_wire_fields(bytes(value))
            skill_type = next((int(v) for n, w, v in command if n == 1), None)
            main_target = next((int(v) for n, w, v in command if n == 2), None)
        elif number == 8 and wire == 2:
            command = read_wire_fields(bytes(value))
            active_skill_type = next((int(v) for n, w, v in command if n == 1), None)
            active_target = next((int(v) for n, w, v in command if n == 2), None)
        elif number == 3 and wire == 2:
            for n, w, v in read_wire_fields(bytes(value)):
                if n in (1, 3) and w == 0:
                    tool_numbers.append(int(v))
                elif n in (1, 3) and w == 2:
                    raw, offset = bytes(v), 0
                    while offset < len(raw):
                        tool_id, offset = read_varint(raw, offset)
                        tool_numbers.append(tool_id)
        elif number == 9 and wire == 2:
            for n, w, v in read_wire_fields(bytes(value)):
                if n == 3 and w == 0:
                    mix_numbers.append(int(v))
                elif n == 3 and w == 2:
                    raw, offset = bytes(v), 0
                    while offset < len(raw):
                        tool_id, offset = read_varint(raw, offset)
                        mix_numbers.append(tool_id)
        elif number == 10 and wire == 2:
            command = read_wire_fields(bytes(value))
            cannon_numbers.extend(
                int(v) for n, w, v in command if n == 1 and w == 0
            )
        elif number == 6 and wire == 2:
            formation = bytes(value)
        elif number == 1 and wire == 0:
            mode = int(value)
        elif number == 7 and wire == 2:
            auto_type = next(
                (int(v) for n, w, v in read_wire_fields(bytes(value)) if n == 2), 0
            )
            sim.auto = sim.auto or auto_type != 0
        elif number == 4 and wire == 2:
            sim.auto = False
    if formation is not None:
        sim.previous_formation = formation
    else:
        sim.previous_formation = sim.previous_formation or default_formation(sim)
    sim.request_count += 1
    actor = sim.current_actor()
    if actor is None:
        raise ValueError("no living actor")
    free_action = bool(tool_numbers or mix_numbers or cannon_numbers or active_skill_type)
    if free_action and sim.command_actor_id is not None:
        # Free actions never advance the timeline, so consecutive free
        # commands keep belonging to the same actor even when a turn swap
        # moved another member to the head of the order.
        held = sim.members.get(sim.command_actor_id)
        if held is not None and held.get("alive") and held["side"] == 0:
            actor = held
    if tool_numbers:
        sim.previous_state = snapshot_state(sim)
        sim.party_gauge = 0
        for tool_number in tool_numbers:
            do_action(sim, actor, "tool", None, main_target, tool_number)
            if check_battle_end(sim) != 0:
                break
        fire_triggers(sim, "item_use", actor, {})
        if sim.status == 0:
            sim.total_turn += 1
            next_setup(sim)
    elif cannon_numbers:
        sim.previous_state = snapshot_state(sim)
        for cannon_number in cannon_numbers:
            do_cannon_action(sim, actor, cannon_number)
        if sim.status == 0:
            sim.total_turn += 1
            next_setup(sim)
    elif mix_numbers:
        sim.previous_state = snapshot_state(sim)
        do_mix_action(sim, actor, mix_numbers)
        fire_triggers(sim, "item_use", actor, {})
        if sim.status == 0:
            sim.total_turn += 1
            next_setup(sim)
    elif active_skill_type:
        sim.previous_state = snapshot_state(sim)
        do_active_action(
            sim,
            actor,
            active_skill_type,
            active_target if active_target is not None else main_target,
        )
        if sim.status == 0:
            sim.total_turn += 1
            next_setup(sim)
    elif mode != 0 or sim.auto or skill_type in (None, 0):
        sim.command_actor_id = None
        sim.party_gauge = min(sim.party_gauge + GAUGE_PER_REQUEST, GAUGE_MAX)
        advance_round(sim, actor, "auto", None, main_target, None)
    else:
        sim.command_actor_id = None
        sim.party_gauge = min(sim.party_gauge + GAUGE_PER_REQUEST, GAUGE_MAX)
        advance_round(sim, actor, "skill", skill_type, main_target, None)
    if free_action and sim.status == 0:
        sim.command_actor_id = actor["id"]
    since = (sim.sent_waves, sim.sent_setups, sim.sent_actions)
    response = write_field(1, 2, build_history(sim, include_prev=True, since=since))
    new_waves = len(sim.wave_starts) - since[0]
    new_setups = len(sim.setups) - since[1]
    new_actions = len(sim.actions) - since[2]
    sim.sent_waves, sim.sent_setups, sim.sent_actions = (
        len(sim.wave_starts), len(sim.setups), len(sim.actions),
    )
    return (
        response,
        None,
        f"LOCAL-BATTLE-ATTACK status={sim.status} actions={sim.action_no} turn={sim.request_count + 1} new_waves={new_waves} new_setups={new_setups} new_actions={new_actions} active={active_skill_type}",
    )


def finish_battle(game_dir: Path, profile_plaintext: bytes) -> tuple[bytes, bytes | None, str]:
    """Finish a won battle. Returns (response_plaintext, persist_plaintext, log)."""
    global _ACTIVE
    if _ACTIVE is None:
        raise ValueError("no active battle")
    sim: BattleSim = _ACTIVE["sim"]
    sim.game_dir = game_dir
    sim.profile_plaintext = profile_plaintext
    if sim.status != 1:
        raise ValueError(f"battle not won (status={sim.status})")
    quest_result, changed = compute_finish(sim)
    response = bytearray(write_field(1, 2, quest_result))
    if sim.kind == "exploration":
        response.extend(write_field(3, 2, b""))
    if sim.kind == "gacha":
        table = battle_table(game_dir, "gacha_battle")
        spec = table.get(str(sim.ref_id), {})
        clears = gacha_battle_clears(game_dir)
        first: list[tuple[int, int, int]] = []
        if sim.ref_id not in clears:
            for entry in spec.get("rewards") or []:
                first.append((int(entry["type"]), int(entry["id"]), int(entry["qty"])))
            clears.append(sim.ref_id)
            save_gacha_battle_clears(game_dir, clears)
        result = bytearray()
        for rtype, rid, qty in first:
            result.extend(
                write_field(
                    1, 2, write_field(1, 0, rtype) + write_field(2, 0, rid) + write_field(3, 0, qty)
                )
            )
        response.extend(write_field(4, 2, bytes(result)))
    response.extend(write_field(2, 2, changed))
    persist = write_field(1, 2, changed)
    clear_battle()
    return (
        bytes(response),
        persist,
        f"LOCAL-BATTLE-FINISH kind={sim.kind} ref={sim.ref_id} rank={sim.finish_bundle.get('rank')} score={sim.finish_bundle.get('score')}",
    )


def retire_battle() -> tuple[bytes, bytes | None, str]:
    clear_battle()
    return write_field(1, 2, b""), None, "LOCAL-BATTLE-RETIRE status=200"


def resume_battle() -> tuple[bytes, bytes | None, str]:
    if _ACTIVE is None:
        raise ValueError("no active battle")
    sim: BattleSim = _ACTIVE["sim"]
    response = write_field(1, 2, build_history(sim, include_prev=True))
    response += write_field(2, 2, build_context(sim))
    sim.sent_waves, sim.sent_setups, sim.sent_actions = (
        len(sim.wave_starts), len(sim.setups), len(sim.actions),
    )
    return response, None, "LOCAL-BATTLE-RESUME status=200"


def skip_battle(
    game_dir: Path, profile_plaintext: bytes, quest_id: int, party_number: int, skip_count: int
) -> tuple[bytes, bytes | None, str]:
    """Skip a quest battle with per-clear piece/Cole rewards and drop rolls."""
    quests = battle_table(game_dir, "quest")
    quest = quests.get(str(quest_id))
    if quest is None:
        raise ValueError(f"unknown quest_id={quest_id}")
    if skip_count <= 0:
        raise ValueError("invalid skip_count")
    members, _, _ = load_party(game_dir, profile_plaintext, party_number)
    rng = random.Random()
    per_clear: list[tuple[int, int, int]] = []
    for member in members:
        per_clear.append((8, member["character_id"], 6))
    per_clear.append((3, 1, 2400))
    for drop_id in quest.get("drops", []):
        for rtype, rid, qty in roll_drops(game_dir, rng, [drop_id]):
            per_clear.append((rtype, rid, qty))
    totals: dict[tuple[int, int], int] = {}
    for _ in range(skip_count):
        for rtype, rid, qty in per_clear:
            totals[(rtype, rid)] = totals.get((rtype, rid), 0) + qty
    exp_gain = int(quest.get("exp", 0) or 0) * skip_count
    result = bytearray()
    for _ in range(skip_count):
        one = bytearray()
        for rtype, rid, qty in per_clear:
            one.extend(
                write_field(
                    1, 2, write_field(1, 0, rtype) + write_field(2, 0, rid) + write_field(3, 0, qty)
                )
            )
        result.extend(write_field(1, 2, bytes(one)))
    for (rtype, rid), qty in sorted(totals.items()):
        result.extend(
            write_field(
                2, 2, write_field(1, 0, rtype) + write_field(2, 0, rid) + write_field(3, 0, qty)
            )
        )
    result.extend(write_field(3, 2, write_field(1, 0, 0) + write_field(2, 0, 0)))
    resources = profile_resources(profile_plaintext)
    changed = bytearray()
    states = profile_quest_states(profile_plaintext)
    prior = states.get(quest_id, {"clear": 0, "missions": [], "rank": 0, "min_turns": 0})
    changed.extend(
        write_field(
            22, 2,
            write_field(1, 0, quest_id)
            + write_field(2, 0, prior.get("clear", 0) + skip_count),
        )
    )
    for member in members:
        current = next(
            (
                bytes(v)
                for n, w, v in read_wire_fields(resources)
                if n == 2 and w == 2 and varint_field(bytes(v), 1, -1) == member["character_id"]
            ),
            b"",
        )
        if not current:
            continue
        merged = bytearray()
        replaced = False
        for number, wire, value in read_wire_fields(current):
            if number == 12 and wire == 0:
                merged.extend(write_field(12, 0, int(value) + exp_gain))
                replaced = True
            else:
                merged.extend(write_field(number, wire, value))
        if not replaced:
            merged.extend(write_field(12, 0, exp_gain))
        changed.extend(write_field(2, 2, bytes(merged)))
    for (rtype, rid), qty in sorted(totals.items()):
        if rtype == 3 and rid == 1:
            status = next(
                (bytes(v) for n, w, v in read_wire_fields(resources) if n == 6 and w == 2), b""
            )
            changed.extend(
                write_field(
                    6, 2,
                    write_field(3, 0, varint_field(status, 3, 0) + qty)
                    + write_field(7, 2, write_timestamp_message()),
                )
            )
        elif rtype == 5:
            current = next(
                (
                    bytes(v)
                    for n, w, v in read_wire_fields(resources)
                    if n == 3 and w == 2 and varint_field(bytes(v), 1, -1) == rid
                ),
                b"",
            )
            have = varint_field(current, 2, 0)
            life = varint_field(current, 3, have)
            changed.extend(write_field(3, 2, write_field(1, 0, rid) + write_field(2, 0, have + qty) + write_field(3, 0, life + qty)))
        elif rtype == 8:
            current = next(
                (
                    bytes(v)
                    for n, w, v in read_wire_fields(resources)
                    if n == 8 and w == 2 and varint_field(bytes(v), 1, -1) == rid
                ),
                b"",
            )
            have = varint_field(current, 2, 0)
            changed.extend(write_field(8, 2, write_field(1, 0, rid) + write_field(2, 0, have + qty)))
    stamina_cost = int(quest.get("stamina", 0) or 0) * skip_count
    if stamina_cost:
        status = next(
            (bytes(v) for n, w, v in read_wire_fields(resources) if n == 6 and w == 2), b""
        )
        changed.extend(
            write_field(
                6, 2,
                write_field(6, 0, max(varint_field(status, 6, 0) - stamina_cost, 0))
                + write_field(7, 2, write_timestamp_message()),
            )
        )
    persist = write_field(1, 2, bytes(changed))
    return (
        bytes(result),
        persist,
        f"LOCAL-BATTLE-SKIP quest={quest_id} count={skip_count}",
    )


def gacha_battle_clears(game_dir: Path) -> list[int]:
    try:
        data = json.loads((game_dir / "gacha-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    clears = data.get("gacha_battle_clears", []) if isinstance(data, dict) else []
    return [int(v) for v in clears] if isinstance(clears, list) else []


def save_gacha_battle_clears(game_dir: Path, clears: list[int]) -> None:
    path = game_dir / "gacha-state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data["gacha_battle_clears"] = sorted(set(int(v) for v in clears))
    try:
        path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    except OSError:
        pass
