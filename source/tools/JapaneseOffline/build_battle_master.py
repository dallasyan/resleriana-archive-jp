"""Build the slim battle-master asset for offline generated battles.

Extracts only the fields the battle simulator needs from the Japanese
master tables. No capture or profile data is included.

Usage:
    python build_battle_master.py <jp-master-dir> <output-dir>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(master: Path, name: str):
    return json.loads((master / f"{name}.json").read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    master: Path = args.master
    out: Path = args.output
    out.mkdir(parents=True, exist_ok=True)

    def write(name: str, data) -> None:
        (out / f"{name}.json").write_text(
            json.dumps(data, separators=(",", ":")), encoding="utf-8"
        )

    quests = {}
    for row in load(master, "quest"):
        if not row.get("battle_id"):
            continue
        score = row.get("score_battle") or {}
        quests[str(row["id"])] = {
            "battle": row["battle_id"],
            "stamina": row.get("stamina") or 0,
            "exp": row.get("character_exp") or 0,
            "drops": row.get("drop_reward_set_ids") or [],
            "first": row.get("first_clear_reward_set_id"),
            "missions": row.get("battle_mission_ids") or [],
            "ranks": [
                {
                    "rank": r.get("rank"),
                    "score": r.get("score") or 0,
                    "rewards": r.get("reward_set_ids") or [],
                    "drops": r.get("drop_reward_set_ids") or [],
                }
                for r in score.get("ranks") or []
            ],
            "member_limit": row.get("party_member_limit_count"),
        }
    write("quest", quests)

    battles = {}
    for row in load(master, "battle"):
        battles[str(row["id"])] = {
            "waves": row.get("wave_ids") or [],
            "panels": row.get("display_timeline_panel_ids") or [],
            "countdown": row.get("countdown_turn"),
        }
    write("battle", battles)

    waves = {}
    for row in load(master, "wave"):
        waves[str(row["id"])] = {
            "enemies": [
                {"id": e["id"], "level": e.get("level") or 1}
                for e in row.get("enemies") or []
            ],
            "field": row.get("field_effect_id"),
        }
    write("wave", waves)

    enemies = {}
    for row in load(master, "enemy"):
        enemies[str(row["id"])] = {
            "base_enemy_id": row.get("base_enemy_id") or row["id"],
            "status": row.get("status") or {},
            "growth": row.get("status_growth") or {},
            "res": row.get("resistance") or {},
            "ai": row.get("enemy_ai_id"),
            "burst": row.get("burst_skill_id"),
            "boss": bool(row.get("is_boss")),
        }
    write("enemy", enemies)

    skills = {}
    for row in load(master, "skill"):
        skills[str(row["id"])] = {
            "power": row.get("power") or 0,
            "break": row.get("break_power") or 0,
            "attrs": row.get("attack_attributes") or [],
            "target": row.get("skill_target_type"),
            "effect": row.get("skill_effect_type"),
            "wait": row.get("wait") or 0,
            "effects": [
                {"id": e["id"], "value": e.get("value") or 0}
                for e in row.get("effects") or []
            ],
            "limit": row.get("limit_count"),
            "lamp": row.get("max_lamp") or 0,
        }
    write("skill", skills)

    panels = {}
    for row in load(master, "timeline_panel"):
        panels[str(row["id"])] = {"type": row.get("type")}
    write("timeline_panel", panels)

    states = {}
    for row in load(master, "state_change"):
        states[str(row["id"])] = {"type": row.get("state_change_type")}
    write("state_change", states)

    drops = {}
    for row in load(master, "drop_reward_set"):
        drops[str(row["id"])] = [
            {
                "rate": r.get("rate") or 0,
                "rewards": [
                    {
                        "type": w["resource_key"]["type"],
                        "id": w["resource_key"]["id"],
                        "min": w.get("min_quantity") or 0,
                        "max": w.get("max_quantity") or w.get("min_quantity") or 0,
                    }
                    for w in r.get("rewards") or []
                ],
            }
            for r in row.get("rewards") or []
        ]
    write("drop_reward_set", drops)

    rewards = {}
    for row in load(master, "reward_set"):
        rewards[str(row["id"])] = [
            {"type": r["type"], "id": r["id"], "qty": r.get("quantity") or 0}
            for r in row.get("rewards") or []
        ]
    write("reward_set", rewards)

    growth = {}
    for row in load(master, "character_growth"):
        growth[str(row["id"])] = row.get("level_coefficients") or {}
    write("character_growth", growth)

    areas = {}
    for row in load(master, "exploration_area"):
        area_battles = [
            {
                "battle": b.get("battle_id"),
                "exp": b.get("character_exp") or 0,
                "cole": b.get("cole") or 0,
                "weight": b.get("weight") or 1,
            }
            for b in row.get("battles") or []
            if b.get("battle_id")
        ]
        if area_battles:
            areas[str(row["id"])] = area_battles
    write("exploration_area", areas)

    gacha_battles = {}
    for row in load(master, "gacha_battle"):
        gacha_battles[str(row["id"])] = {
            "battle": row.get("battle_id"),
            "fixed_party": row.get("fixed_party_id"),
            "rewards": [
                {"type": r["type"], "id": r["id"], "qty": r.get("quantity") or 0}
                for r in row.get("rewards") or []
            ],
        }
    write("gacha_battle", gacha_battles)

    fixed = {}
    for row in load(master, "fixed_party"):
        members = []
        for member in row.get("members") or []:
            char = member.get("character") or {}
            if char.get("id"):
                members.append(
                    {
                        "id": char["id"],
                        "level": char.get("level") or 1,
                        "rarity": char.get("rarity") or 1,
                    }
                )
        fixed[str(row["id"])] = {
            "leader": row.get("leader_position") or 1,
            "members": members,
        }
    write("fixed_party", fixed)

    ai_units: dict[str, list[int]] = {}
    for row in load(master, "enemy_ai_unit"):
        bucket = ai_units.setdefault(str(row.get("enemy_ai_id")), [])
        for skill in row.get("skills") or []:
            if skill.get("id") not in bucket:
                bucket.append(skill["id"])
    write("enemy_ai", ai_units)

    print(
        f"WROTE {out} quests={len(quests)} battles={len(battles)} "
        f"enemies={len(enemies)} skills={len(skills)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
