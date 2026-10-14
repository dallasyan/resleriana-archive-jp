"""Build the skill removal-effect map from captured battle histories.

Reads private Japanese capture sessions in place and writes only skill,
effect, and state-change master IDs plus aggregate counts into the
battle-master directory. No payloads, profiles, session tokens, or session
names leave the capture roots.

Captured BattleEffectResult entries carry explicit ``removed_state_changes``
lists: skills cleanse specific states (battle-start markers such as 920002,
enemy-inflicted debuffs such as 1220341, or their own refreshable buffs)
before their grants land. The runtime applies these removals before
combat-map grants so immunity/cleanse ordering matches the wire.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_panel_schedules import iter_session_dirs, endpoint_of
from JapaneseCombat.capture_data import (  # noqa: E402
    CaptureRecord,
    decode_record,
    load_contract_database,
)
from JapaneseCombat.snapshot_bridge import repeated  # noqa: E402


def side_of(state: dict, member_id) -> int:
    for member in repeated((state or {}).get("members")):
        try:
            if int(member.get("member_id", 0) or 0) == int(member_id or 0):
                return 0 if "ally" in member else 1
        except (TypeError, ValueError):
            continue
    return -1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path,
                        help="capture roots followed by the battle-master output dir")
    args = parser.parse_args()
    *roots, out_dir = args.inputs
    out_dir.mkdir(parents=True, exist_ok=True)

    database = load_contract_database()
    # (skill, effect, phase, side, state) -> count
    votes: dict[tuple, int] = defaultdict(int)
    n_attacks = 0
    n_sessions = 0
    for root in roots:
        for sess in iter_session_dirs(root):
            n_sessions += 1
            for txt in sorted(sess.glob("0*.txt")):
                url = endpoint_of(txt)
                if "/battle/attack" not in url or "start" in url.rsplit("/", 1)[-1]:
                    continue
                try:
                    number = int(txt.name.split(".")[0])
                except ValueError:
                    continue
                try:
                    _, resp = decode_record(
                        CaptureRecord(number, "/battle/attack",
                                      sess / ("%04d-request.bin" % number),
                                      sess / ("%04d-response.bin" % number)),
                        database)
                except Exception:
                    continue
                n_attacks += 1
                for act in repeated((resp.get("history") or {}).get("actions")):
                    skill = act.get("skill_id")
                    if skill is None:
                        continue
                    try:
                        skill = int(skill)
                    except (TypeError, ValueError):
                        continue
                    action_state = act.get("state") or {}
                    for key, phase in (("before_skill_effect_results", "before_skill"),
                                       ("effect_results", "effect")):
                        for res in repeated(act.get(key)):
                            removed = res.get("removed_state_changes")
                            if removed is None:
                                continue
                            try:
                                effect_id = int(res.get("effect_id", 0) or 0)
                            except (TypeError, ValueError):
                                continue
                            if not effect_id:
                                continue
                            tgt = res.get("effect_target_id")
                            if isinstance(tgt, dict):
                                tgt = tgt.get("value", tgt.get("target_id"))
                            tside = side_of(action_state, tgt)
                            for change in repeated(removed):
                                try:
                                    state_id = int(change.get("state_change_id", 0) or 0)
                                except (TypeError, ValueError):
                                    continue
                                if state_id:
                                    votes[(skill, effect_id, phase, tside, state_id)] += 1
    grouped: dict[tuple, dict[tuple, set]] = defaultdict(lambda: defaultdict(set))
    for (skill, effect_id, phase, side, state_id) in votes:
        grouped[skill][(effect_id, phase, side)].add(state_id)
    removals = {}
    for skill in sorted(grouped):
        entries = []
        for (effect_id, phase, side) in sorted(grouped[skill]):
            entries.append({
                "effect_id": effect_id,
                "phase": phase,
                "side": side,
                "states": sorted(grouped[skill][(effect_id, phase, side)]),
            })
        # before_skill entries first, matching wire application order.
        entries.sort(key=lambda e: (0 if e["phase"] == "before_skill" else 1,
                                    e["effect_id"]))
        removals[str(skill)] = entries
    payload = {
        "removals": removals,
        "meta": {
            "attacks": n_attacks,
            "sessions": n_sessions,
            "skills": len(removals),
        },
    }
    (out_dir / "skill_effect_map.json").write_text(
        json.dumps(payload, indent=1), encoding="utf-8")
    print("attacks=%d sessions=%d skills_with_removals=%d" % (
        n_attacks, n_sessions, len(removals)))
    for skill, entries in sorted(removals.items(), key=lambda kv: int(kv[0])):
        for entry in entries:
            print("skill %s effect %d phase %s side %d states %s" % (
                skill, entry["effect_id"], entry["phase"], entry["side"],
                entry["states"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
