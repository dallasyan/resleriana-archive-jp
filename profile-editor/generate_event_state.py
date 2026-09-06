#!/usr/bin/env python3
"""Generate a profile-state manifest that unlocks historical event stories."""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path


def default_master_root() -> Path:
    packaged_root = Path(__file__).with_name("master")
    if packaged_root.is_dir():
        return packaged_root
    return Path(__file__).resolve().parents[2] / "resleriana-db-main" / "data" / "master" / "jp"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--master-root",
        type=Path,
        default=default_master_root(),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clear-count", type=int, default=1)
    parser.add_argument(
        "--include-revived-events",
        action="store_true",
        help="also mark every event as already revived; normally leave revival state unchanged",
    )
    args = parser.parse_args()

    events = json.loads((args.master_root / "event.json").read_text(encoding="utf-8"))
    episodes = json.loads((args.master_root / "episode.json").read_text(encoding="utf-8"))
    quests = json.loads((args.master_root / "quest.json").read_text(encoding="utf-8"))

    event_ids = sorted({int(event["id"]) for event in events})
    event_episode_ids = {
        int(episode["id"])
        for episode in episodes
        if episode.get("event_id") is not None
    }
    quest_ids = sorted(
        int(quest["id"])
        for quest in quests
        if quest.get("episode_id") in event_episode_ids
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "source": str(args.master_root),
                "revived_events": event_ids if args.include_revived_events else [],
                "quest_states": {str(quest_id): args.clear_count for quest_id in quest_ids},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output}: events={len(event_ids)} event_quests={len(quest_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
