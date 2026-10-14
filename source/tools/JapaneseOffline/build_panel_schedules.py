"""Build the captured per-battle timeline panel schedule table.

Reads private Japanese capture sessions in place and writes only battle,
turn, and panel master IDs plus observation counts to
``panel_schedules.json`` in the battle-master directory. No payloads,
profiles, session tokens, or account data are written.

Each session directory uses request/response ``NNNN.bin`` pairs with a
``NNNN.txt`` sidecar carrying the endpoint URL. Battles are grouped as
``/quest/battle/start`` through ``/battle/finish`` (or ``/battle/retire``);
every ``/battle/attack`` response contributes its setup forecast windows
(``timeline_panels`` turn/panel pairs). Per (battle, turn) cells resolve by
majority vote; ties prefer a panel over empty, then the smallest panel id,
so output is deterministic.

Usage:
    python tools/JapaneseOffline/build_panel_schedules.py
        <capture-root> [<capture-root> ...] <battle-master-dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT / "tools"))
sys.path.insert(0, str(WORKSPACE_ROOT / "tools" / "JapaneseOffline"))
sys.path.insert(0, str(WORKSPACE_ROOT / "tools" / "JapaneseProfileEditor"))

from JapaneseCombat.capture_data import (  # noqa: E402
    CaptureRecord,
    decode_record,
    load_contract_database,
    repeated,
)


def panel_value(raw) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = raw.get("value")
        if raw is None:
            return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def iter_session_dirs(root: Path):
    """Yield directories holding NNNN.txt sidecars (session layout)."""
    if not root.is_dir():
        return
    if list(root.glob("0*.txt")):
        yield root
        return
    for child in sorted(root.iterdir()):
        if child.is_dir():
            yield from iter_session_dirs(child)


def endpoint_of(txt: Path) -> str:
    try:
        for line in txt.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("URL="):
                return line[4:]
    except OSError:
        pass
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path,
                        help="capture roots followed by the battle-master output dir")
    args = parser.parse_args()
    *roots, out_dir = args.inputs
    out_dir.mkdir(parents=True, exist_ok=True)

    database = load_contract_database()
    votes: dict[int, dict[int, Counter]] = defaultdict(lambda: defaultdict(Counter))
    instances: dict[int, set] = defaultdict(set)
    n_starts = 0
    n_attacks = 0
    for root in roots:
        for sess in iter_session_dirs(root):
            current: int | None = None
            instance: tuple | None = None
            for txt in sorted(sess.glob("0*.txt")):
                url = endpoint_of(txt)
                if not url:
                    continue
                try:
                    number = int(txt.name.split(".")[0])
                except ValueError:
                    continue
                if "/quest/battle/start" in url:
                    try:
                        _, resp = decode_record(
                            CaptureRecord(number, "/quest/battle/start",
                                          sess / ("%04d-request.bin" % number),
                                          sess / ("%04d-response.bin" % number)),
                            database)
                    except Exception:
                        current = None
                        continue
                    n_starts += 1
                    history = resp.get("history") or {}
                    start = history.get("start") or {}
                    state = start.get("state") or {} if isinstance(start, dict) else {}
                    if state.get("battle_id") is None:
                        current = None
                        continue
                    current = int(state["battle_id"])
                    instance = (sess.name, number)
                    instances[current].add(instance)
                elif "/battle/attack" in url and current is not None:
                    try:
                        _, resp = decode_record(
                            CaptureRecord(number, "/battle/attack",
                                          sess / ("%04d-request.bin" % number),
                                          sess / ("%04d-response.bin" % number)),
                            database)
                    except Exception:
                        continue
                    n_attacks += 1
                    history = resp.get("history") or {}
                    for setup in repeated(history.get("action_setups")):
                        st = setup.get("state") or {}
                        for panel in repeated(st.get("timeline_panels")):
                            try:
                                turn = int(panel.get("turn", 0) or 0)
                            except (TypeError, ValueError):
                                continue
                            votes[current][turn][panel_value(panel.get("panel_id"))] += 1
                elif "/battle/finish" in url or "/battle/retire" in url:
                    current = None

    table = {}
    disputed = 0
    for battle_id in sorted(votes):
        turns = {}
        total_votes = 0
        for turn in sorted(votes[battle_id]):
            counter = votes[battle_id][turn]
            total_votes += sum(counter.values())
            # Majority wins; ties prefer a panel over empty, then smallest id.
            best = sorted(counter.items(),
                          key=lambda item: (-item[1], item[0] is None, item[0] or 0))[0]
            if len(counter) > 1:
                disputed += 1
            turns[str(turn)] = best[0]
        table[str(battle_id)] = {
            "max_turn": max(votes[battle_id]) if votes[battle_id] else 0,
            "observations": total_votes,
            "instances": len(instances.get(battle_id, ())),
            "turns": turns,
        }

    out_path = out_dir / "panel_schedules.json"
    out_path.write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8")

    dist = Counter()
    for battle_turns in votes.values():
        for counter in battle_turns.values():
            for panel_id, count in counter.items():
                dist[panel_id] += count
    print("starts: %d attacks: %d battles: %d disputed_cells: %d" % (
        n_starts, n_attacks, len(table), disputed))
    print("distribution: %s" % {
        ("empty" if key is None else key): dist[key] for key in sorted(
            dist, key=lambda k: (-dist[k], k is None, k or 0))})
    print("wrote %s" % out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
