"""Generate per-item combat checklists from masters and the combat map.

Reads resleriana-db JP masters plus the derived combat_map.json and writes
one markdown file per category under COMBAT_CHECKLISTS/. Each row carries
the Japanese name, an English name from the official Global localization
(--localization, AtelierResleriana-master Localization data) with fallback
to local mechanics/community mappings, and an Implemented / Partial /
Missing / Unsure verdict with a short note.

Usage:
    python build_granular_checklists.py <resleriana-db-jp-master-dir> <share-game-root> <output-dir> [--localization <MasterDataLocalizationData.json>]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def load(master: Path, name: str):
    return json.loads((master / f"{name}.json").read_text(encoding="utf-8-sig"))


def load_table(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {str(v["id"]): v for v in raw if isinstance(v, dict) and "id" in v}
    return {str(k): v for k, v in raw.items()}


EN_ATTRS = {"slash": "Slash", "impact": "Blunt", "piercing": "Pierce",
            "wind": "Wind", "fire": "Fire", "ice": "Ice", "lightning": "Lightning"}
EN_ROLES = {1: "Attacker", 2: "Breaker", 3: "Defender", 4: "Supporter"}
EN_AILMENTS = {"poison": "Poison", "venom": "Venom", "burn": "Burn",
               "paralysis": "Paralysis", "sleep": "Sleep", "frozen": "Frozen",
               "stun": "Stun", "darkness": "Darkness", "taunt": "Taunt"}
EN_PANELS = {"12": "Enhance", "13": "Weaken", "14": "Burst", "17": "Burst",
             "15": "Paralysis", "18": "Paralysis", "19": "Paralysis",
             "16": "Darkness", "20": "Darkness", "21": "Darkness",
             "22": "Enhance", "24": "Enhance+", "26": "Weaken+",
             "30": "Critical", "33": "Guard Strength", "36": "Guard-Weaken",
             "39": "Break Boost", "42": "HP Heal", "45": "Burn",
             "46": "Paralysis+", "51": "Lifebuoy", "52": "Straw",
               "63": "Martellato", "67": "Crimson Bullet"}


def esc(text) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def write_table(out: Path, title: str, legend: str, headers: list[str], rows: list[list]) -> None:
    lines = ["# " + title, "", legend, "",
             "| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(esc(cell) for cell in row) + " |")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


def load_localization(path: Path | None) -> dict[str, dict[str, str]]:
    """Official Global English names keyed per master table.

    Returns {table: {id: name}}. Missing file or tables degrade to {},
    leaving the mechanics/community fallbacks in place.
    """
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    tables = {}
    for table, rows in (data.get("en") or {}).items():
        names: dict[str, str] = {}
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("id") is not None and row.get("name"):
                    names[str(row["id"])] = row["name"]
        elif isinstance(rows, dict):
            for key, row in rows.items():
                if isinstance(row, dict) and row.get("name"):
                    names[str(row.get("id", key))] = row["name"]
        if names:
            tables[str(table)] = names
    return tables


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("gameroot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--localization", type=Path, default=None,
                        help="MasterDataLocalizationData.json for official English names")
    parser.add_argument("--machine", type=Path, default=None,
                        help="machine-translated master dir (newer IDs)")
    parser.add_argument("--share-dir", type=Path, default=None,
                        help="share tree receiving sanitized checklist copies")
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    loc = load_localization(args.localization)

    machine: dict[str, dict[str, str]] = {}
    if args.machine is not None:
        try:
            for path in sorted(args.machine.glob("*.json")):
                rows = json.loads(path.read_text(encoding="utf-8"))
                names: dict[str, str] = {}
                entries = rows if isinstance(rows, list) else rows.values()
                for row in entries:
                    if isinstance(row, dict) and row.get("id") is not None and row.get("name"):
                        names[str(row["id"])] = row["name"]
                if names:
                    machine[path.stem] = names
        except (OSError, ValueError):
            pass

    def en(table: str, item_id, fallback: str = "") -> str:
        name = loc.get(table, {}).get(str(item_id))
        if name:
            return name
        return machine.get(table, {}).get(str(item_id), fallback)
    cmap = json.loads((args.gameroot / "battle-master" / "combat_map.json").read_text(encoding="utf-8"))
    slim_skill = load_table(args.gameroot / "battle-master" / "skill.json")
    characters = load(args.master, "character")
    skills = {str(r.get("id")): r for r in load(args.master, "skill")}
    abilities = {str(r.get("id")): r for r in load(args.master, "ability")}
    enemies = {str(r.get("id")): r for r in load(args.master, "enemy")}
    states = cmap.get("states", {})
    effects = cmap.get("effects", {})
    panels = cmap.get("panels", {})
    behaviors = cmap.get("skill_behavior", {})
    ability_parsed = cmap.get("ability_parsed", {})
    cmap_skills = cmap.get("skills", {})

    legend_status = ("Status: Implemented = resolves fully in the sim; Partial = resolves "
                     "generically with some effects records-only; Missing = not implemented; "
                     "Unsure = needs capture confirmation. EN is filled only where a local "
                     "mapping exists; blank EN means untranslated proper noun. "
                     "Notes name the specific missing effect/ability IDs and the open "
                     "value, duration, condition, or target questions for mapped parts.")

    # Runtime paths mirrored from battle_japanese.py so notes can distinguish
    # implemented codes from ignored ones. Keep these sets aligned with the
    # simulator when combat behavior changes.
    SLOT_MOD_CODES = {
        "skill_damage", "dealt_damage", "skill_power", "taken_damage",
        "crit_rate", "crit_damage", "break_damage", "taken_break",
        "taken_crit_damage", "penetration", "item_damage", "cannon_damage",
        "item_crit", "cannon_crit", "burst_damage", "drain", "excess_crit",
    }
    START_STAT_CODES = {"stat_up", "stat_down"}
    SPECIAL_MOD_CODES = {
        "potency_given_plus", "potency_given_minus", "potency_received",
        "ailment_rate", "burst_gain_down", "burst_stocks", "pioneer", "aggro",
        "resist_up", "ailment_immune",
    }
    # ailment_resist as a battle-long mod is ignored: the sim only reads
    # resist_up buffs for resistance and ailment_immune mods for immunity.
    IGNORED_MOD_CODES = {"ailment_resist"}
    TRIGGER_EXEC_OPS = {"lamp_light", "lamp_scaled", "range_swap"}
    TRIGGER_ACTION_OPS = {"panel_skill", "extra_attack"}
    # Trigger buff payloads executed immediately rather than granted.
    TRIGGER_EXEC_BUFF_CODES = {
        "heal", "item_gauge", "burst_gauge", "cleanse", "turn_swap",
        "turn_erase", "delay_turn", "hasten_turn", "field", "revive",
        "panel_generate", "panel_convert", "panel_enhance", "extra_attack",
        "transform", "lamp", "pioneer", "drain", "accuracy_down", "resist_down",
    }
    TRIGGER_GRANT_CODES = {
        "skill_damage", "skill_power", "crit_rate", "crit_damage",
        "break_damage", "taken_break", "penetration", "taken_damage",
        "dealt_damage", "stat_up", "stat_down", "heal_given", "heal_received",
        "burst_damage", "resist_up", "ailment_resist", "panel_null",
        "ailment", "ailment_dot", "regen", "barrier", "evade", "reflect",
        "cover", "null_damage", "counter", "break_power",
    }
    SKILL_GRANT_CODES = {
        "skill_damage", "dealt_damage", "skill_power", "crit_rate",
        "crit_damage", "break_damage", "taken_break", "taken_crit_damage",
        "penetration", "taken_damage", "burst_damage", "heal_given",
        "heal_received", "ailment", "resist_up", "resist_down",
        "target_debuff",
    }
    KNOWN_COND_NAMES = {
        "role", "attr", "target_state", "target_broken", "hp_above",
        "hp_below", "crit", "ko", "boss", "weak_hit", "scope", "skill_ids",
        "panel", "tag_count", "gauge_above",
    }
    KNOWN_TRIGGER_EVENTS = {
        "heal_received", "skill_use", "post_attack", "weak_hit", "crit",
        "ko", "break_hit", "target_ailment_hit", "attacked", "panel_gain",
        "turn_start", "pre_attack", "party_burst", "item_use",
        "battle_start", "wave_start",
    }

    def fmt_ids(ids, cap=8):
        ids = [str(x) for x in ids if x is not None and str(x) != ""]
        if not ids:
            return ""
        shown = ", ".join(ids[:cap])
        if len(ids) > cap:
            shown += " +%d more" % (len(ids) - cap)
        return shown

    def cond_names(conds):
        names = []
        for cond in conds or []:
            name = cond.get("cond") if isinstance(cond, dict) else None
            if name and name not in names:
                names.append(name)
        return names

    def unsure_flags(parsed):
        """Open value/duration/condition/target questions for one parsed map."""
        flags = []
        if int(parsed.get("rate", 100) or 100) != 100:
            flags.append("rate %s" % parsed.get("rate"))
        if int(parsed.get("cap", 0) or 0):
            flags.append("cap %s" % parsed.get("cap"))
        if parsed.get("fixed"):
            flags.append("fixed-value handling")
        if int(parsed.get("dur_actions", 0) or 0) or int(parsed.get("dur_hits", 0) or 0):
            flags.append("durations")
        if parsed.get("perm"):
            flags.append("permanence")
        if parsed.get("placeholder"):
            flags.append("placeholder value mapping")
        if int(parsed.get("text_value", 0) or 0):
            flags.append("explicit text value")
        unknown_conds = [c for c in cond_names(parsed.get("conds")) if c not in KNOWN_COND_NAMES]
        if unknown_conds:
            flags.append("unmodeled conditions: %s" % ",".join(unknown_conds))
        elif cond_names(parsed.get("conds")):
            flags.append("conditions: %s" % ",".join(cond_names(parsed.get("conds"))))
        target = parsed.get("target")
        if target and target not in ("self", "context", "skill_target"):
            flags.append("target: %s" % target)
        return flags

    def mod_handled(mod) -> bool:
        code = mod.get("code")
        return code in SLOT_MOD_CODES or code in START_STAT_CODES or code in SPECIAL_MOD_CODES

    def trigger_handled(trig) -> bool:
        op = trig.get("op")
        if op in TRIGGER_EXEC_OPS or op in TRIGGER_ACTION_OPS or op == "lamp_bonus":
            return True
        if op == "buff":
            code = (trig.get("buff", {}) or {}).get("code")
            return code in TRIGGER_EXEC_BUFF_CODES or code in TRIGGER_GRANT_CODES
        return False

    def mod_gaps(mods):
        """Classify battle-long mods into handled notes and gaps."""
        handled = []
        missing = []
        unsure = []
        for mod in mods or []:
            code = mod.get("code")
            label = "%s%s" % (code, ":%s" % mod.get("stat") if mod.get("stat") else "")
            if mod_handled(mod):
                handled.append(label)
                if code == "resist_up":
                    unsure.append("%s resist_up buff amounts ignored downstream" % label)
                if code == "burst_stocks":
                    unsure.append("%s start-stock values need capture confirmation" % label)
            elif code in IGNORED_MOD_CODES:
                missing.append("%s mod ignored (only buffs/immunity read)" % label)
            else:
                missing.append("%s mod ignored" % label)
            for flag in unsure_flags(mod):
                unsure.append("%s %s" % (label, flag))
        return handled, missing, unsure

    def trigger_gaps(triggers):
        """Classify ability triggers into handled notes and gaps."""
        handled = []
        missing = []
        unsure = []
        for trig in triggers or []:
            op = trig.get("op")
            event = trig.get("event")
            label = "%s@%s" % (op, event)
            if op in TRIGGER_EXEC_OPS or op in TRIGGER_ACTION_OPS:
                handled.append(label)
            elif op == "lamp_bonus":
                handled.append("%s (passive lamp data)" % label)
            elif op == "buff":
                buff = trig.get("buff", {}) or {}
                code = buff.get("code")
                if code in TRIGGER_EXEC_BUFF_CODES:
                    handled.append("%s executes %s" % (label, code))
                elif code in TRIGGER_GRANT_CODES:
                    handled.append("%s grants %s" % (label, code))
                else:
                    missing.append("%s buff %s ignored" % (label, code))
            elif not trigger_handled(trig):
                missing.append("%s op ignored" % label)
            if event not in KNOWN_TRIGGER_EVENTS and event is not None:
                unsure.append("%s event never fired" % label)
            for flag in unsure_flags(trig.get("buff", {}) if isinstance(trig.get("buff"), dict) else {}):
                unsure.append("%s %s" % (label, flag))
            for cond in cond_names(trig.get("conds")):
                if cond not in KNOWN_COND_NAMES:
                    unsure.append("%s unmodeled condition %s" % (label, cond))
            if int(trig.get("uses_max", 0) or 0):
                unsure.append("%s use cap %s" % (label, trig.get("uses_max")))
        return handled, missing, unsure

    def join_note(implemented, missing, unsure, cap_items=6, cap_chars=420):
        """Compact implemented/missing/unsure note for one checklist row."""
        parts = []
        if implemented:
            shown = implemented[:cap_items]
            text = "done: %s" % "; ".join(shown)
            if len(implemented) > cap_items:
                text += " +%d more" % (len(implemented) - cap_items)
            parts.append(text)
        if missing:
            shown = missing[:cap_items]
            text = "missing: %s" % "; ".join(shown)
            if len(missing) > cap_items:
                text += " +%d more" % (len(missing) - cap_items)
            parts.append(text)
        if unsure:
            seen = []
            for item in unsure:
                if item not in seen:
                    seen.append(item)
            shown = seen[:cap_items]
            text = "unsure: %s" % "; ".join(shown)
            if len(seen) > cap_items:
                text += " +%d more" % (len(seen) - cap_items)
            parts.append(text)
        note = "; ".join(parts) if parts else "no parsed combat parts"
        if len(note) > cap_chars:
            note = note[:cap_chars].rstrip() + "…"
        return note

    # Full means every effect mapped, every parsed mod/trigger handled by
    # the sim, AND any description parsed; anything less is Partial so
    # missing parts stay visible per item.
    def ability_full(aid: str) -> bool:
        parsed = ability_parsed.get(str(aid), {})
        fx = (abilities.get(str(aid)) or {}).get("effects") or []
        fx_mapped = sum(1 for e in fx if effects.get(str(e.get("id")), {}).get("code") != "unmapped")
        if fx_mapped != len(fx):
            return False
        if any(not mod_handled(m) for m in parsed.get("mods", [])):
            return False
        if any(not trigger_handled(t) for t in parsed.get("triggers", [])):
            return False
        desc = ((abilities.get(str(aid)) or {}).get("description") or "").strip()
        if desc and not parsed.get("mods") and not parsed.get("triggers"):
            return False
        return True

    def abilities_covered(abil) -> tuple[int, int]:
        return (sum(1 for a in abil if ability_full(str(a))), len(abil))

    # -- characters ---------------------------------------------------------
    rows = []
    for row in characters if isinstance(characters, list) else characters.values():
        cid = str(row.get("id"))
        normal = bool(row.get("normal1_skill_ids")) and bool(row.get("normal2_skill_ids"))
        burst = row.get("burst_skill_ids") or []
        burst_ok = bool(burst) and all(str(b) in slim_skill for b in burst)
        actives = [a for a in (row.get("active1_skill_id"), row.get("active2_skill_id"),
                               row.get("active3_skill_id")) if a]
        actives_ok = all(str(a) in slim_skill and (slim_skill[str(a)].get("limit") or 0) > 0 for a in actives)
        extra = row.get("extra_skill_ids") or []
        extra_ok = all(str(e) in slim_skill for e in extra)
        ab = row.get("ability_ids") or []
        ab_mapped = sum(1 for a in ab if ability_full(str(a)))
        ab_missing = [str(a) for a in ab if not ability_full(str(a))]
        leader = row.get("leader_skill") or {}
        leader_ok = bool(leader.get("abilities"))
        done = []
        if normal:
            done.append("normal skills")
        if burst_ok:
            done.append("burst %s" % fmt_ids(burst))
        if actives and actives_ok:
            done.append("actives %s" % fmt_ids(actives))
        if extra and extra_ok:
            done.append("extra %s" % fmt_ids(extra))
        if ab_mapped:
            done.append("%d/%d abilities fully implemented" % (ab_mapped, len(ab)))
        missing = []
        if not normal:
            missing.append("no normal skill tables")
        if burst and not burst_ok:
            missing.append("burst %s absent from skill map" % fmt_ids(burst))
        if actives and not actives_ok:
            missing.append("actives %s missing skill/limit rows" % fmt_ids(actives))
        if extra and not extra_ok:
            missing.append("extra %s absent from skill map" % fmt_ids(extra))
        if ab_missing:
            missing.append("abilities not fully implemented %s" % fmt_ids(ab_missing))
        if not leader_ok:
            missing.append("no leader skill")
        unsure = []
        if leader_ok:
            unsure.append("leader condition values estimated")
        if normal and burst_ok and (not actives or actives_ok) and (not extra or extra_ok) and not ab_missing:
            status = "Implemented"
        elif normal:
            status = "Partial"
        else:
            status = "Missing"
        note = join_note(done, missing, unsure)
        rows.append([cid, row.get("name") or "", en("character", cid),
                     EN_ROLES.get(row.get("role"), ""), status, note])
    rows.sort(key=lambda r: int(r[0]))
    write_table(out / "characters.md", "Characters (216)",
                legend_status, ["id", "ja", "en", "role", "status", "note"], rows)

    # -- skills (ally prefixes) ----------------------------------------------
    # Skill effect ids resolve through apply_skill_effects: state-table ids
    # grant visible buffs (except special/dummy/counter_state), parsed grant
    # codes become hidden slot buffs, timeline/gauge/field/cleanse codes
    # execute immediately, and everything else is records-only.
    SKILL_EXEC_CODES = {
        "turn_swap", "turn_erase", "delay_turn", "hasten_turn",
        "item_gauge", "burst_gauge", "break_gauge_heal", "field",
        "cleanse", "dispel",
    }
    # Skill-summary behavior codes and their sim paths.
    BEHAVIOR_DAMAGE_CODES = {
        "atk_crit_damage", "atk_crit_rate", "atk_penetration",
        "weak_break_up", "weak_dealt_up", "scaling_damage",
    }
    BEHAVIOR_POST_CODES = {
        "post_heal_self", "post_heal_allies", "post_break_up_self",
        "post_taken_up_target", "pre_resist_down_target", "item_gauge",
        "turn_swap", "cleanse_self_pre", "extra_turn_grant",
    }
    rows = []
    for sid in sorted([k for k in skills if k[:2] in ("11", "12", "14")], key=int):
        row = skills[sid]
        fx = row.get("effects") or []
        done, missing, unsure = [], [], []
        for e in fx:
            eid = str(e.get("id"))
            parsed = effects.get(eid, {})
            code = parsed.get("code", "unmapped")
            label = "%s:%s" % (eid, code)
            if code == "unmapped":
                missing.append("%s unmapped" % eid)
                continue
            if eid in states:
                kind = (states.get(eid) or {}).get("kind", "special")
                if kind in ("special", "dummy", "counter_state"):
                    missing.append("%s state %s records-only" % (eid, kind))
                else:
                    done.append("%s grants %s buff" % (eid, kind))
                    if kind == "resist_up":
                        unsure.append("%s resist amounts ignored downstream" % eid)
                    if kind == "ailment":
                        unsure.append("%s %s" % (label, "; ".join(unsure_flags(parsed)) or "application roll"))
                    for flag in unsure_flags(parsed):
                        unsure.append("%s %s" % (label, flag))
                continue
            if code in SKILL_GRANT_CODES:
                done.append("%s hidden %s buff" % (eid, code))
                for flag in unsure_flags(parsed):
                    unsure.append("%s %s" % (label, flag))
            elif code in SKILL_EXEC_CODES:
                done.append("%s executes %s" % (eid, code))
                for flag in unsure_flags(parsed):
                    unsure.append("%s %s" % (label, flag))
            else:
                missing.append("%s %s records-only" % (eid, code))
        beh = behaviors.get(sid, [])
        for b in beh:
            code = b.get("code")
            if code in BEHAVIOR_DAMAGE_CODES:
                done.append("behavior %s in damage calc" % code)
                if code == "scaling_damage":
                    unsure.append("behavior scaling_damage thresholds estimated (hp 50%%, foe counts)")
                if code in ("weak_break_up", "weak_dealt_up"):
                    unsure.append("behavior %s weakness determination" % code)
            elif code in BEHAVIOR_POST_CODES:
                if code == "extra_turn_grant":
                    done.append("behavior extra_turn_grant gated on extra_skill, max 5/battle")
                    unsure.append("behavior extra_turn_grant cond %s" % b.get("cond"))
                else:
                    done.append("behavior %s post-attack" % code)
            elif code == "burst_gauge":
                missing.append("behavior burst_gauge ignored by post-attack handler")
            else:
                missing.append("behavior %s ignored" % code)
        info = cmap_skills.get(sid, {})
        flags = ",".join(f for f, on in (
            ("lamp%d" % info.get("lamp_max", 0), info.get("lamp_max")),
            ("transform", info.get("transform")),
            ("range", info.get("range_move") or info.get("dest")),
            ("timeline", info.get("timeline"))) if on)
        if flags:
            done.append("flags: " + flags)
        effect_kind = {1: "damage", 2: "heal", 3: "records-only"}.get(
            row.get("skill_effect_type"), "type%s" % row.get("skill_effect_type"))
        done.append("skill effect path: %s" % effect_kind)
        if not fx and not beh:
            status = "Implemented"
        elif not missing:
            status = "Implemented"
        elif done:
            status = "Partial"
        else:
            status = "Partial"
        note = join_note(done, missing, unsure)
        rows.append([sid, row.get("name") or "", en("skill", sid),
                     "%s/%s" % (row.get("power"), row.get("break_power")),
                     "t%s/e%s" % (row.get("skill_target_type"), row.get("skill_effect_type")),
                     status, note])
    write_table(out / "skills.md", "Ally skills (11/12/14)",
                legend_status, ["id", "ja", "en", "power/break", "target/effect", "status", "note"], rows)

    # -- abilities ------------------------------------------------------------
    # ability_full is defined once above (strict: every effect mapped and
    # every parsed mod/trigger handled by the sim) and shared by all
    # sections so verdicts stay consistent.
    def ability_covered(aid: str) -> tuple[bool, str]:
        parsed = ability_parsed.get(str(aid), {})
        mods, trigs = parsed.get("mods", []), parsed.get("triggers", [])
        fx = (abilities.get(str(aid)) or {}).get("effects") or []
        fx_ids = [str(e.get("id")) for e in fx]
        fx_unmapped = [i for i in fx_ids if effects.get(i, {}).get("code") == "unmapped"]
        fx_mapped = len(fx_ids) - len(fx_unmapped)
        done, missing, unsure = mod_gaps(mods)
        t_done, t_missing, t_unsure = trigger_gaps(trigs)
        done.extend(t_done)
        missing.extend(t_missing)
        unsure.extend(t_unsure)
        if fx_mapped:
            done.append("%d/%d description effects mapped" % (fx_mapped, len(fx_ids)))
        if fx_unmapped:
            missing.append("unmapped effect ids %s" % fmt_ids(fx_unmapped))
        desc = ((abilities.get(str(aid)) or {}).get("description") or "").strip()
        if desc and not mods and not trigs:
            missing.append("description text unparsed")
        note = join_note(done, missing, unsure)
        covered = bool(done)
        return covered, note

    rows = []
    for aid in sorted(abilities, key=int):
        row = abilities[aid]
        desc = (row.get("description") or "")[:140]
        covered, note = ability_covered(aid)
        if ability_full(aid):
            status = "Implemented"
        elif covered:
            status = "Partial"
        else:
            status = "Missing"
        rows.append([aid, desc, en("ability", aid), status, note])
    write_table(out / "abilities.md", "Abilities (7131)",
                legend_status + " Description truncated to 140 chars.",
                ["id", "ja", "en", "status", "note"], rows)

    # -- enemies ---------------------------------------------------------------
    rows = []
    for eid in sorted(enemies, key=int):
        row = enemies[eid]
        status = row.get("status") or {}
        ok_stats = all(k in status for k in ("hp", "attack", "defense"))
        ok_res = bool(row.get("resistance"))
        ok_ai = bool(row.get("enemy_ai_id"))
        burst = row.get("burst_skill_id")
        burst_ok = (not burst) or (str(burst) in slim_skill)
        extra = row.get("extra_skill_ids") or []
        extra_ok = all(str(e) in slim_skill for e in extra)
        done, missing, unsure = [], [], []
        if ok_stats:
            done.append("base stats present")
            unsure.append("level scaling linear-growth estimated")
        else:
            missing.append("stats")
        if ok_res:
            done.append("resistances present")
        else:
            missing.append("res")
        if ok_ai:
            done.append("ai %s cycles in order, burst every 5 turns" % row.get("enemy_ai_id"))
            unsure.append("ai sequencing vs telegraphs unconfirmed")
        else:
            missing.append("ai")
        if burst and burst_ok:
            done.append("burst %s in skill map" % burst)
        elif burst:
            missing.append("burst %s absent from skill map" % burst)
        if extra and extra_ok:
            done.append("extra %s in skill map" % fmt_ids(extra))
        elif extra:
            missing.append("extra %s absent from skill map" % fmt_ids(extra))
        if row.get("break_gauge_coefficient") not in (None, 0):
            unsure.append("break coefficient %s estimated" % row.get("break_gauge_coefficient"))
        if row.get("hp_loop_type") not in (None, 0, 1):
            unsure.append("hp loop type %s unconfirmed" % row.get("hp_loop_type"))
        status_label = "Implemented" if not missing else "Partial"
        rows.append([eid, row.get("name") or "", en("enemy", eid),
                     "lv-scaled" if ok_stats else "no-stats",
                     "burst" if burst else "no-burst",
                     status_label, join_note(done, missing, unsure)])
    write_table(out / "enemies.md", "Enemies",
                legend_status, ["id", "ja", "en", "stats", "burst", "status", "note"], rows)

    # -- battle items ------------------------------------------------------------
    battle_tools = load(args.master, "battle_tool")
    battle_traits = {str(r.get("id")): r for r in load(args.master, "battle_tool_trait")}
    rows = []
    tool_rows = battle_tools if isinstance(battle_tools, list) else battle_tools.values()
    for row in tool_rows:
        tid = str(row.get("id"))
        skill_ok = str(row.get("skill_id")) in slim_skill
        traits = [str(t) for t in (row.get("trait_filter_ids") or [])]
        trait_unmapped = [t for t in traits
                          if not any(effects.get(str(e.get("id")), {}).get("code") != "unmapped"
                                     for e in (battle_traits.get(t, {}).get("effects") or []))]
        done, missing, unsure = [], [], []
        if skill_ok:
            done.append("skill %s pooled item damage/heal" % row.get("skill_id"))
        else:
            missing.append("skill %s absent from skill map" % row.get("skill_id"))
        if traits:
            done.append("%d/%d traits parsed" % (len(traits) - len(trait_unmapped), len(traits)))
        if trait_unmapped:
            missing.append("unmapped traits %s" % fmt_ids(trait_unmapped))
        unsure.append("usage count x%s per battle estimated" % row.get("usage_count"))
        unsure.append("mix pairings use mixer-only stats")
        rows.append([tid, row.get("name") or "", en("battle_tool", tid),
                     str(row.get("skill_id")), "x%s" % row.get("usage_count"),
                     "Implemented" if skill_ok and not trait_unmapped else ("Partial" if skill_ok else "Missing"),
                     join_note(done, missing, unsure)])
    rows.sort(key=lambda r: int(r[0]))
    write_table(out / "battle_items.md", "Battle items",
                legend_status, ["id", "ja", "en", "skill", "uses", "status", "note"], rows)

    # -- equipment ------------------------------------------------------------------
    equipment = load(args.master, "equipment_tool")
    rows = []
    eq_rows = equipment if isinstance(equipment, list) else equipment.values()
    for row in eq_rows:
        eid = str(row.get("id"))
        buffs = row.get("status_buffs") or []
        abil = [str(a) for a in (row.get("ability_ids") or [])]
        ab_missing = [a for a in abil if not ability_full(a)]
        done, missing, unsure = [], [], []
        if buffs:
            done.append("%d start stat buffs" % len(buffs))
        if abil and not ab_missing:
            done.append("%d/%d abilities parsed" % (len(abil), len(abil)))
        elif ab_missing:
            done.append("%d/%d abilities parsed" % (len(abil) - len(ab_missing), len(abil)))
            missing.append("abilities not fully implemented %s" % fmt_ids(ab_missing))
        if not buffs and not abil:
            missing.append("no usable buffs/abilities")
        if buffs:
            unsure.append("flat start stats, growth scaling unconfirmed")
        if buffs and (not abil or not ab_missing):
            status = "Implemented"
        elif buffs or (abil and len(ab_missing) != len(abil)):
            status = "Partial"
        else:
            status = "Missing"
        note = join_note(done, missing, unsure)
        rows.append([eid, row.get("name") or "", en("equipment_tool", eid), status, note])
    rows.sort(key=lambda r: int(r[0]))
    write_table(out / "equipment.md", "Equipment",
                legend_status, ["id", "ja", "en", "status", "note"], rows)

    # -- memoria ---------------------------------------------------------------------
    memoria = load(args.master, "memoria")
    rows = []
    mem_rows = memoria if isinstance(memoria, list) else memoria.values()
    for row in mem_rows:
        mid = str(row.get("id"))
        buffs = row.get("status_buffs") or []
        abil = [str(a) for a in (row.get("ability_ids") or [])]
        ab_missing = [a for a in abil if not ability_full(a)]
        done, missing, unsure = [], [], []
        if buffs:
            done.append("growth+%d start stat buffs" % len(buffs))
        if abil and not ab_missing:
            done.append("%d/%d abilities parsed" % (len(abil), len(abil)))
        elif ab_missing:
            done.append("%d/%d abilities parsed" % (len(abil) - len(ab_missing), len(abil)))
            missing.append("abilities not fully implemented %s" % fmt_ids(ab_missing))
        if not buffs and not abil:
            missing.append("no usable buffs/abilities")
        if buffs:
            unsure.append("limit-break growth scaling unconfirmed")
        if buffs and (not abil or not ab_missing):
            status = "Implemented"
        elif buffs or (abil and len(ab_missing) != len(abil)):
            status = "Partial"
        else:
            status = "Missing"
        note = join_note(done, missing, unsure)
        rows.append([mid, row.get("name") or "", en("memoria", mid), "r%s" % row.get("rarity"), status, note])
    rows.sort(key=lambda r: int(r[0]))
    write_table(out / "memoria.md", "Memoria",
                legend_status, ["id", "ja", "en", "rarity", "status", "note"], rows)

    # -- traits ------------------------------------------------------------------------
    def trait_ability_covered(aid) -> bool:
        covered, _ = ability_covered(str(aid))
        return covered

    rows = []
    for label, tname in (("battle", "battle_tool_trait"), ("equipment", "equipment_tool_trait")):
        traits = load(args.master, tname)
        trows = traits if isinstance(traits, list) else traits.values()
        for row in trows:
            fx = row.get("effects") or []
            fx_ids = [str(e.get("id")) for e in fx]
            fx_unmapped = [i for i in fx_ids if effects.get(i, {}).get("code") == "unmapped"]
            abil = [str(a) for a in (row.get("ability_ids") or [])]
            ab_missing = [a for a in abil if not trait_ability_covered(a)]
            done, missing, unsure = [], [], []
            fx_got = len(fx_ids) - len(fx_unmapped)
            if fx_ids and fx_got:
                done.append("%d/%d trait effects mapped" % (fx_got, len(fx_ids)))
            if fx_unmapped:
                missing.append("unmapped effect ids %s" % fmt_ids(fx_unmapped))
            ab_got = len(abil) - len(ab_missing)
            if abil and ab_got:
                done.append("%d/%d trait abilities parsed" % (ab_got, len(abil)))
            if ab_missing:
                missing.append("unparsed abilities %s" % fmt_ids(ab_missing))
            if not fx_ids and not abil:
                missing.append("no effects or abilities")
            if fx_ids or abil:
                unsure.append("trait filter matching vs item seed unconfirmed")
            total = len(fx_ids) + len(abil)
            got = total - len(fx_unmapped) - len(ab_missing)
            if total and got == total:
                status = "Implemented"
            elif got:
                status = "Partial"
            else:
                status = "Missing"
            note = join_note(done, missing, unsure)
            rows.append(["%s:%s" % (label, row.get("id")), row.get("name") or "",
                         en(tname, row.get("id")), status, note])
    rows.sort()
    write_table(out / "traits.md", "Item and equipment traits",
                legend_status, ["id", "ja", "en", "status", "note"], rows)

    # -- panels --------------------------------------------------------------------------
    # Panel acquisition runs grant_panel_op: slot/taken/stat/heal/ailment
    # codes apply; crit_force and unmapped ops are records-only.
    PANEL_HANDLED_CODES = {
        "skill_damage", "skill_power", "crit_rate", "crit_damage",
        "break_damage", "taken_break", "penetration", "taken_damage",
        "stat_up", "stat_down", "heal", "ailment", "ailment_dot",
    }
    panels = load(args.master, "timeline_panel")
    rows = []
    prows = panels if isinstance(panels, list) else panels.values()
    for row in prows:
        pid = str(row.get("id"))
        ops = panels.get(pid, {}).get("ops", []) if isinstance(panels, dict) else []
        parsed_ops = (cmap.get("panels", {}).get(pid, {}) or {}).get("ops", [])
        done, missing, unsure = [], [], []
        for op in parsed_ops:
            code = op.get("op") or op.get("code")
            if code in PANEL_HANDLED_CODES:
                done.append("%s applies on acquisition" % code)
                if int(op.get("text_value", 0) or 0):
                    unsure.append("%s magnitude text_value %s" % (code, op.get("text_value")))
                if int(op.get("dur_actions", 0) or 0) or int(op.get("dur_hits", 0) or 0):
                    unsure.append("%s durations actions=%s hits=%s" % (
                        code, op.get("dur_actions", 0), op.get("dur_hits", 0)))
                elif code not in ("heal",):
                    unsure.append("%s default 2-action duration" % code)
                if op.get("holder") not in (None, "holder"):
                    unsure.append("%s holder %s targeting" % (code, op.get("holder")))
                if code == "heal" and not int(op.get("text_value", 0) or 0):
                    unsure.append("heal defaults to 25%% max HP")
                if code == "ailment":
                    unsure.append("ailment %s rate %s" % (op.get("ailment"), op.get("rate")))
            elif code in (None, "unmapped", "unmapped_panel"):
                missing.append("unmapped panel op")
            else:
                missing.append("%s panel op records-only" % code)
        if not parsed_ops:
            missing.append("no parsed ops")
        if parsed_ops and not missing:
            status = "Implemented"
        elif done:
            status = "Partial"
        else:
            status = "Missing"
        note = join_note(done, missing, unsure)
        rows.append([pid, row.get("name") or "", en("timeline_panel", pid) or EN_PANELS.get(pid, ""), status, note])
    rows.sort(key=lambda r: int(r[0]))
    write_table(out / "panels.md", "Timeline panels",
                legend_status, ["id", "ja", "en", "status", "note"], rows)

    # -- states ----------------------------------------------------------------------------
    # The state description supplies the semantic slot; the effect/skill row
    # supplies the runtime grant value, target, and application conditions.
    states = load(args.master, "state_change")
    srows = states if isinstance(states, list) else states.values()
    rows = []
    for row in srows:
        sid = str(row.get("id"))
        state_info = cmap.get("states", {}).get(sid, {}) or {}
        kind = state_info.get("kind", "special")
        ailment = state_info.get("ailment", "")
        en_name = en("state_change", sid) or EN_AILMENTS.get(ailment, "")
        done, missing, unsure = [], [], []
        if kind in ("special", "dummy", "counter_state"):
            missing.append("kind=%s has no runtime behavior; effect records only" % kind)
            status = "Partial"
        elif kind == "counter":
            done.append("counter state is detected on hit")
            missing.append("counter damage/targeting is not resolved")
            status = "Partial"
        elif kind in ("pioneer", "panel_null", "range_in", "range_out"):
            done.append("kind=%s granted and serialized" % kind)
            missing.append("state-specific battle behavior is not fully connected")
            status = "Partial"
        elif kind in ("reflect",):
            done.append("reflect state is applied on received hits")
            missing.append("reflect amount/type behavior needs capture validation")
            status = "Partial"
        elif kind in (
            "out", "taken", "stat", "speed", "skill_damage", "skill_power",
            "crit_rate", "crit_damage", "break_up", "break_power", "taken_break",
            "taken_crit_damage", "penetration", "burst_damage", "item_damage",
            "item_crit", "item_heal", "cannon_damage", "cannon_crit",
            "recovery_given", "recovery_received", "resist_down", "resist_up",
            "resist_elem", "ailment", "ailment_immune", "regen", "barrier",
            "evade", "cover", "null_damage", "reactive_heal", "post_skill_heal",
            "cleanse_turn_start",
        ):
            done.append("kind=%s applies its mapped combat slot/trigger" % kind)
            unsure.append("grant value, remaining duration, and potency need capture confirmation")
            if kind == "ailment":
                unsure.append("ailment %s application roll" % (ailment or "unknown"))
            status = "Partial" if unsure else "Implemented"
        else:
            missing.append("kind=%s has no validated runtime handler" % kind)
            status = "Unsure"
        note = join_note(done, missing, unsure)
        rows.append([sid, row.get("name") or "", en_name, status, note])
    rows.sort(key=lambda r: int(r[0]))
    write_table(out / "states.md", "Status effects",
                legend_status, ["id", "ja", "en", "status", "note"], rows)

    loc_tables = len(loc)
    summary = [
        "# Combat checklists",
        "",
        "Per-item validation for every combat record. Generated from resleriana-db "
        "JP masters plus the derived combat_map.json; no capture or profile data.",
        "",
        "English names prefer the official Global localization "
        "(%d tables), then fan machine translations (%d tables), then local "
        "mechanics/community mappings. IDs in none keep a blank EN cell." % (
            loc_tables, len(machine)),
        "",
        "- characters.md: 216 characters, skill tables, bursts, actives, extras, leaders.",
        "- skills.md: ally 11/12/14 skills, behaviors, lamp/transform/range flags.",
        "- abilities.md: 7131 abilities with parsed mods/triggers.",
        "- enemies.md: stats, resistances, AI, bursts.",
        "- battle_items.md: tools, skills, usage counts, trait filters.",
        "- equipment.md: stat buffs and mapped abilities.",
        "- memoria.md: growth buffs and mapped abilities.",
        "- traits.md: battle and equipment trait effect coverage.",
        "- panels.md: exact parsed panel operations.",
        "- states.md: status-effect kinds with English names.",
        "",
        "Unsure items need capture confirmation; see the capture list in the "
        "session summary message.",
        "",
    ]
    (out / "README.md").write_text("\n".join(summary), encoding="utf-8")
    print("wrote %d files" % (len(list(out.glob('*.md')))))
    if args.share_dir is not None:
        write_share_copies(out, args.share_dir)
    return 0


SHARE_REPLACEMENTS = [
    ("dm_lara_criselda_antje/session-20260927-141441-620", "local battle captures"),
    ("session-20260928-123435-331", "local battle captures"),
    ("decrypted-session-20260928-075711-658", "local decrypted captures"),
    ("session_lepl/session_lepl", "local battle captures"),
    ("session_brust/session_brust", "local battle captures"),
    ("session_geron_0916/session_geron", "local battle captures"),
    ("Season2_skills", "local skill captures"),
]
SHARE_PATTERNS = [
    (re.compile(r"C:\\Users\\[^`\s]+"), "<user dir>"),
    (re.compile(r"decrypted-session-[A-Za-z0-9_-]+"), "local decrypted captures"),
    (re.compile(r"(?<![A-Za-z0-9_-])session-[0-9]{8}-[0-9]+-[0-9]+"), "local battle captures"),
]
SHARE_HEADER = (
    "> Share copy (sanitized per AGENTS.md): local capture session paths, "
    "user directories, and profile references removed. Route names, counts, "
    "and master IDs retained. Regenerate from workspace originals.\n\n"
)


def sanitize_share_text(text: str) -> str:
    """Strip private local references for the share package."""
    for old, new in SHARE_REPLACEMENTS:
        text = text.replace(old, new)
    for pattern, new in SHARE_PATTERNS:
        text = pattern.sub(new, text)
    return text


def write_share_copies(out: Path, share_dir: Path) -> None:
    """Write sanitized checklist copies into the share tree."""
    root_checklist = Path("COMBAT_CHECKLIST.md")
    granular_dir = share_dir / "COMBAT_CHECKLISTS"
    granular_dir.mkdir(parents=True, exist_ok=True)
    if root_checklist.is_file():
        (share_dir / "COMBAT_CHECKLIST.md").write_text(
            SHARE_HEADER + sanitize_share_text(root_checklist.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
    for path in sorted(out.glob("*.md")):
        (granular_dir / path.name).write_text(
            SHARE_HEADER + sanitize_share_text(path.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
    print("wrote share copies to %s" % share_dir)


if __name__ == "__main__":
    raise SystemExit(main())
