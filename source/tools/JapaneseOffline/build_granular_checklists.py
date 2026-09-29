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
                     "mapping exists; blank EN means untranslated proper noun.")

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
        ab_mapped = sum(1 for a in ab if ability_parsed.get(str(a), {}).get("mods") or ability_parsed.get(str(a), {}).get("triggers"))
        leader = row.get("leader_skill") or {}
        leader_ok = bool(leader.get("abilities"))
        if normal and burst_ok and (not actives or actives_ok) and (not extra or extra_ok):
            status, note = "Implemented", "skills/burst/active/extra resolve; %d/%d abilities parsed" % (ab_mapped, len(ab))
        elif normal:
            status, note = "Partial", "core skills resolve; burst_ok=%s actives_ok=%s extra_ok=%s abilities=%d/%d" % (
                burst_ok, actives_ok, extra_ok, ab_mapped, len(ab))
        else:
            status, note = "Missing", "no normal skill tables"
            if not leader_ok:
                note += "; no leader skill"
        rows.append([cid, row.get("name") or "", en("character", cid),
                     EN_ROLES.get(row.get("role"), ""), status, note])
    rows.sort(key=lambda r: int(r[0]))
    write_table(out / "characters.md", "Characters (216)",
                legend_status, ["id", "ja", "en", "role", "status", "note"], rows)

    # -- skills (ally prefixes) ----------------------------------------------
    rows = []
    for sid in sorted([k for k in skills if k[:2] in ("11", "12", "14")], key=int):
        row = skills[sid]
        fx = row.get("effects") or []
        mapped_fx = sum(1 for e in fx if effects.get(str(e.get("id")), {}).get("code") != "unmapped")
        state_fx = sum(1 for e in fx if str(e.get("id")) in states)
        beh = sid in behaviors
        info = cmap_skills.get(sid, {})
        flags = ",".join(f for f, on in (
            ("lamp%d" % info.get("lamp_max", 0), info.get("lamp_max")),
            ("transform", info.get("transform")),
            ("range", info.get("range_move") or info.get("dest")),
            ("timeline", info.get("timeline"))) if on)
        if beh and mapped_fx == len(fx):
            status, note = "Implemented", "behavior-mapped" + ("; " + flags if flags else "")
        elif not fx:
            status, note = "Implemented", "no effects" + ("; " + flags if flags else "")
        elif mapped_fx or state_fx or beh:
            status, note = "Partial", "%d/%d effects mapped, %d state ids%s" % (
                mapped_fx, len(fx), state_fx, "; " + flags if flags else "")
        else:
            status, note = "Partial", "records-only effects"
        rows.append([sid, row.get("name") or "", en("skill", sid),
                     "%s/%s" % (row.get("power"), row.get("break_power")),
                     "t%s/e%s" % (row.get("skill_target_type"), row.get("skill_effect_type")),
                     status, note])
    write_table(out / "skills.md", "Ally skills (11/12/14)",
                legend_status, ["id", "ja", "en", "power/break", "target/effect", "status", "note"], rows)

    # -- abilities ------------------------------------------------------------
    def abilities_covered(abil) -> tuple[int, int]:
        return (sum(1 for a in abil if ability_covered(str(a))[0]), len(abil))

    def ability_covered(aid: str) -> tuple[bool, str]:
        parsed = ability_parsed.get(aid, {})
        mods, trigs = parsed.get("mods", []), parsed.get("triggers", [])
        fx = (abilities.get(aid) or {}).get("effects") or []
        fx_mapped = sum(1 for e in fx if effects.get(str(e.get("id")), {}).get("code") != "unmapped")
        parts = []
        if mods:
            parts.append("%d mods" % len(mods))
        if trigs:
            parts.append("%d triggers" % len(trigs))
        if fx_mapped:
            parts.append("%d/%d effect-desc mapped" % (fx_mapped, len(fx)))
        if parts:
            return True, "+".join(parts)
        if fx:
            return False, "unmapped description+effects"
        return False, "no effects"
    rows = []
    for aid in sorted(abilities, key=int):
        row = abilities[aid]
        desc = (row.get("description") or "")[:140]
        covered, note = ability_covered(aid)
        status = "Implemented" if covered else "Missing"
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
        missing = [k for k, ok in (("stats", ok_stats), ("res", ok_res), ("ai", ok_ai)) if not ok]
        status_label = "Implemented" if not missing else "Partial"
        rows.append([eid, row.get("name") or "", en("enemy", eid),
                     "lv-scaled" if ok_stats else "no-stats",
                     "burst" if row.get("burst_skill_id") else "no-burst",
                     status_label, "missing: " + ",".join(missing) if missing else "linear growth estimated"])
    write_table(out / "enemies.md", "Enemies",
                legend_status, ["id", "ja", "en", "stats", "burst", "status", "note"], rows)

    # -- battle items ------------------------------------------------------------
    battle_tools = load(args.master, "battle_tool")
    rows = []
    tool_rows = battle_tools if isinstance(battle_tools, list) else battle_tools.values()
    for row in tool_rows:
        tid = str(row.get("id"))
        skill_ok = str(row.get("skill_id")) in slim_skill
        traits = row.get("trait_filter_ids") or []
        rows.append([tid, row.get("name") or "", en("battle_tool", tid),
                     str(row.get("skill_id")), "x%s" % row.get("usage_count"),
                     "Implemented" if skill_ok else "Missing",
                     "traits: %s" % ",".join(map(str, traits))])
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
        abil = row.get("ability_ids") or []
        ab_mapped = abilities_covered(abil)[0]
        if buffs and (not abil or ab_mapped == len(abil)):
            status, note = "Implemented", "%d stat buffs, %d/%d abilities parsed" % (len(buffs), ab_mapped, len(abil))
        elif buffs or ab_mapped:
            status, note = "Partial", "%d stat buffs, %d/%d abilities parsed" % (len(buffs), ab_mapped, len(abil))
        else:
            status, note = "Missing", "no usable buffs/abilities"
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
        abil = row.get("ability_ids") or []
        ab_mapped = abilities_covered(abil)[0]
        if buffs and (not abil or ab_mapped == len(abil)):
            status, note = "Implemented", "growth+%d buffs, %d/%d abilities parsed" % (len(buffs), ab_mapped, len(abil))
        elif buffs or ab_mapped:
            status, note = "Partial", "%d buffs, %d/%d abilities parsed" % (len(buffs), ab_mapped, len(abil))
        else:
            status, note = "Missing", "no usable buffs/abilities"
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
            mapped = sum(1 for e in fx if effects.get(str(e.get("id")), {}).get("code") != "unmapped")
            abil = row.get("ability_ids") or []
            ab_mapped = sum(1 for a in abil if trait_ability_covered(a))
            total = len(fx) + len(abil)
            got = mapped + ab_mapped
            if total and got == total:
                status, note = "Implemented", "%d/%d parsed" % (got, total)
            elif got:
                status, note = "Partial", "%d/%d parsed" % (got, total)
            else:
                status, note = "Missing", "unmapped"
            rows.append(["%s:%s" % (label, row.get("id")), row.get("name") or "",
                         en(tname, row.get("id")), status, note])
    rows.sort()
    write_table(out / "traits.md", "Item and equipment traits",
                legend_status, ["id", "ja", "en", "status", "note"], rows)

    # -- panels --------------------------------------------------------------------------
    panels = load(args.master, "timeline_panel")
    rows = []
    prows = panels if isinstance(panels, list) else panels.values()
    for row in prows:
        pid = str(row.get("id"))
        ops = panels.get(pid, {}).get("ops", []) if isinstance(panels, dict) else []
        parsed_ops = (cmap.get("panels", {}).get(pid, {}) or {}).get("ops", [])
        unmapped = sum(1 for o in parsed_ops if (o.get("op") or o.get("code")) in (None, "unmapped", "unmapped_panel"))
        if parsed_ops and not unmapped:
            status, note = "Implemented", "%d ops" % len(parsed_ops)
        elif parsed_ops:
            status, note = "Partial", "%d/%d ops parsed" % (len(parsed_ops) - unmapped, len(parsed_ops))
        else:
            status, note = "Missing", "no parsed ops"
        rows.append([pid, row.get("name") or "", en("timeline_panel", pid) or EN_PANELS.get(pid, ""), status, note])
    rows.sort(key=lambda r: int(r[0]))
    write_table(out / "panels.md", "Timeline panels",
                legend_status, ["id", "ja", "en", "status", "note"], rows)

    # -- states ----------------------------------------------------------------------------
    states = load(args.master, "state_change")
    srows = states if isinstance(states, list) else states.values()
    rows = []
    for row in srows:
        sid = str(row.get("id"))
        kind = (cmap.get("states", {}).get(sid, {}) or {}).get("kind", "special")
        ailment = (cmap.get("states", {}).get(sid, {}) or {}).get("ailment", "")
        en_name = en("state_change", sid) or EN_AILMENTS.get(ailment, "")
        if kind in ("out", "taken"):
            status, note = "Implemented", "kind=" + kind
        elif kind in ("ailment", "regen", "barrier", "evade", "reflect", "cover",
                      "null_damage", "resist_up", "panel_null", "range_in", "range_out"):
            status, note = "Implemented", "kind=" + kind
        elif kind in ("counter", "counter_state", "dummy", "special"):
            status, note = "Partial", "kind=" + kind + " (display/counters only)"
        else:
            status, note = "Unsure", "kind=" + kind
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
