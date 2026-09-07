#!/usr/bin/env python3
"""Create compact Japanese exploration route data for offline dungeon entry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def route_type(area: dict) -> str:
    if area.get("gatherings"):
        return "gathering"
    if area.get("battles"):
        return "battle"
    if area.get("talks"):
        return "talk"
    raise ValueError(f"exploration area has no route type: {area.get('id')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Japanese exploration_area.json")
    parser.add_argument("output", type=Path, help="compact route output JSON")
    args = parser.parse_args()

    areas = json.loads(args.source.read_text(encoding="utf-8"))
    routes: dict[str, list[dict[str, int | str]]] = {}
    for area in areas:
        quest_id = str(int(area["quest_id"]))
        routes.setdefault(quest_id, []).append(
            {
                "area_id": int(area["id"]),
                "number": int(area.get("number", 0)),
                "route_type": route_type(area),
            }
        )
    for quest_routes in routes.values():
        quest_routes.sort(key=lambda route: (int(route["number"]), int(route["area_id"])))

    args.output.write_text(
        json.dumps(routes, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(routes)} quest routes to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
