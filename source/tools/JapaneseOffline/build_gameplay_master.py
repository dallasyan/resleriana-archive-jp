#!/usr/bin/env python3
"""Build compact Japanese master data for generated non-combat endpoints.

Usage:
    python build_gameplay_master.py <jp-master-dir> <output-json>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(master: Path, name: str) -> list[dict]:
    rows = json.loads((master / f"{name}.json").read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list):
        raise ValueError(f"master table must be a JSON array: {name}")
    return rows


def resource_entry(value: dict) -> dict[str, int]:
    return {
        "type": int(value.get("type") or 0),
        "id": int(value.get("id") or 0),
        "quantity": int(value.get("quantity") or 0),
    }


def build(master: Path) -> dict:
    recipes = {}
    for row in load(master, "recipe"):
        recipes[str(int(row["id"]))] = {
            "id": int(row["id"]),
            "recipe_plan_id": int(row.get("recipe_plan_id") or 0),
            "character_id": int(row.get("character_id") or 0),
            "mana_cost": int(row.get("mana_cost") or 0),
            "costs": [resource_entry(value) for value in row.get("costs") or []],
            "rewards": [
                {
                    "is_target": bool(value.get("is_target")),
                    **resource_entry(value.get("resource") or {}),
                }
                for value in row.get("rewards") or []
            ],
        }

    dishes = {}
    for row in load(master, "dish"):
        dishes[str(int(row["id"]))] = {
            "id": int(row["id"]),
            "start_at": row.get("start_at"),
            "end_at": row.get("end_at"),
            "rewards": [resource_entry(value) for value in row.get("rewards") or []],
        }

    expeditions = {}
    for row in load(master, "expedition"):
        expeditions[str(int(row["id"]))] = {
            "id": int(row["id"]),
            "items": [int(value["id"]) for value in row.get("items") or []],
            "score_battle_quest_ids": [
                int(value) for value in row.get("score_battle_quest_ids") or []
            ],
        }

    recommendations: dict[str, dict[str, int]] = {}
    for row in load(master, "expedition_recommended_character"):
        by_character = recommendations.setdefault(str(int(row["expedition_id"])), {})
        by_character[str(int(row["character_id"]))] = int(row.get("bonus_rate") or 0)

    exploration_areas = {}
    for row in load(master, "exploration_area"):
        area_id = int(row["id"])
        if row.get("gatherings"):
            route_type = "gathering"
        elif row.get("battles"):
            route_type = "battle"
        elif row.get("talks"):
            route_type = "talk"
        else:
            route_type = "unknown"
        exploration_areas[str(area_id)] = {
            "id": area_id,
            "quest_id": int(row.get("quest_id") or 0),
            "number": int(row.get("number") or 0),
            "route_type": route_type,
            "is_event_gathering": bool(row.get("is_event_gathering")),
            "gatherings": [
                {
                    "gathering_type": int(value.get("gathering_type") or 0),
                    "point_count": int(value.get("point_count") or 0),
                    "weight": int(value.get("weight") or 0),
                }
                for value in row.get("gatherings") or []
            ],
        }

    return {
        "recipes": recipes,
        "dishes": dishes,
        "expeditions": expeditions,
        "expedition_recommendations": recommendations,
        "exploration_areas": exploration_areas,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path, help="Japanese master-data directory")
    parser.add_argument("output", type=Path, help="output gameplay-master JSON path")
    args = parser.parse_args()

    data = build(args.master)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"WROTE {args.output} recipes={len(data['recipes'])} dishes={len(data['dishes'])} "
        f"expeditions={len(data['expeditions'])} areas={len(data['exploration_areas'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
