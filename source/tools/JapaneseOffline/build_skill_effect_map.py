"""Build captured skill state-grant and removal mappings.

Reads private Japanese capture sessions in place and writes only skill,
effect, and state-change master IDs plus aggregate counts into the
battle-master directory. No payloads, profiles, session tokens, or session
names leave the capture roots.

Captured BattleEffectResult entries carry explicit ``dealt_state_change``
and ``removed_state_changes`` values. State-grant observations tie a skill's
effect master ID to its actual state-change ID; this corrects same-placeholder
skills where multiple state rows share one displayed value but have different
effect IDs, as well as duplicate state rows selected by the client. Removals
preserve the before-skill/effect phase and target side. Only master IDs and
aggregate counts are written.
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
    skill_rows = json.loads((out_dir / "skill.json").read_text(encoding="utf-8"))
    skill_effect_ids = {}
    for skill_id, row in skill_rows.items():
        if not isinstance(row, dict):
            continue
        effect_ids = set()
        for effect in row.get("effects", []) or []:
            try:
                effect_ids.add(int(effect.get("id", 0) or 0))
            except (AttributeError, TypeError, ValueError):
                continue
        skill_effect_ids[str(skill_id)] = effect_ids
    # (skill, effect, phase, side, state) -> count
    votes: dict[tuple, int] = defaultdict(int)
    # (skill, effect, state, side) -> count for granted states.
    grant_sides: dict[tuple, int] = defaultdict(int)
    # (skill, effect, state) -> count; only effects present in that skill row
    # qualify, avoiding unrelated passive-trigger effect IDs.
    state_grant_votes: dict[tuple, int] = defaultdict(int)
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
                    own_effects = skill_effect_ids.get(str(skill), set())
                    for key, phase in (("before_skill_effect_results", "before_skill"),
                                       ("effect_results", "effect")):
                        for res in repeated(act.get(key)):
                            try:
                                effect_id = int(res.get("effect_id", 0) or 0)
                            except (TypeError, ValueError):
                                effect_id = 0
                            if effect_id in own_effects:
                                tgt = res.get("effect_target_id")
                                if isinstance(tgt, dict):
                                    tgt = tgt.get("value", tgt.get("target_id"))
                                gside = side_of(action_state, tgt)
                                for change in repeated(res.get("dealt_state_change")):
                                    try:
                                        state_id = int(change.get("state_change_id", 0) or 0)
                                    except (AttributeError, TypeError, ValueError):
                                        continue
                                    if state_id:
                                        state_grant_votes[(skill, effect_id, state_id)] += 1
                                        grant_sides[(skill, effect_id, state_id, gside)] += 1
                            removed = res.get("removed_state_changes")
                            if removed is None:
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
    grant_groups: dict[int, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    for (skill, effect_id, state_id), count in state_grant_votes.items():
        sides = {str(side): grant_sides.get((skill, effect_id, state_id, side), 0)
                 for side in (0, 1, -1)
                 if grant_sides.get((skill, effect_id, state_id, side), 0)}
        grant_groups[skill][effect_id].append({"id": state_id, "count": count,
                                               "sides": sides})
    state_grants = {}
    for skill in sorted(grant_groups):
        state_grants[str(skill)] = [
            {"effect_id": effect_id,
             "states": sorted(states, key=lambda entry: (-entry["count"], entry["id"]))}
            for effect_id, states in sorted(grant_groups[skill].items())
        ]
    grant_effect_count = sum(len(effects) for effects in grant_groups.values())
    grant_observation_count = sum(state_grant_votes.values())
    payload = {
        "state_grants": state_grants,
        "removals": removals,
        "meta": {
            "attacks": n_attacks,
            "sessions": n_sessions,
            "skills_with_state_grants": len(state_grants),
            "state_grant_effects": grant_effect_count,
            "state_grant_observations": grant_observation_count,
            "skills_with_removals": len(removals),
        },
    }
    (out_dir / "skill_effect_map.json").write_text(
        json.dumps(payload, indent=1), encoding="utf-8")
    print("attacks=%d sessions=%d grant_skills=%d grant_effects=%d "
          "grant_observations=%d removal_skills=%d" % (
              n_attacks, n_sessions, len(state_grants), grant_effect_count,
              grant_observation_count, len(removals)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
