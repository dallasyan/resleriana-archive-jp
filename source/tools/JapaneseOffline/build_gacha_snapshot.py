"""Build a sanitized gacha snapshot asset for offline generated handlers.

Reads the /gacha/list response from a private capture session plus the
Japanese master tables, and writes a shareable JSON asset containing only
public banner/rate data. Personal data is excluded:

- wishlist states are dropped (synthesized empty at runtime),
- per-button execution counts are dropped (tracked in a runtime sidecar),
- changed_resources must contain only the gacha notification submessage.

Card-pool membership and per-card rates come from the captured rate sets;
rarity labels come from the master gacha_rate/gacha_deck tables.

Usage:
    python build_gacha_snapshot.py <session-dir> <jp-master-dir> <output.json>
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import decrypt_japanese_capture as decrypt_tool


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def wishlist_rule(mixed_wish_list: dict | None) -> dict | None:
    if not mixed_wish_list:
        return None
    return {
        "characters": [int(v) for v in mixed_wish_list.get("pickup_character_ids") or []],
        "memorias": [int(v) for v in mixed_wish_list.get("pickup_memoria_ids") or []],
        "select": int(mixed_wish_list.get("select_count") or 0),
    }


def decode_row(payload: bytes, rate_master: dict, deck_master: dict) -> dict:
    fields = decrypt_tool.read_wire_fields(payload)
    rate_id = next(int(v) for n, w, v in fields if n == 1)
    deck_id = int(rate_master[rate_id]["gacha_deck_id"])
    return {
        "rate_id": int(rate_id),
        "percent": next(bytes(v).decode("ascii") for n, w, v in fields if n == 2),
        "rarity": int(deck_master[deck_id]["rarity"]),
        "cards": [
            [int(v) for _, _, v in decrypt_tool.read_wire_fields(bytes(c))]
            for n, w, c in fields
            if n == 3
        ],
    }


def decode_rows(payload: bytes, rate_master: dict, deck_master: dict) -> list[dict]:
    return [
        decode_row(bytes(value), rate_master, deck_master)
        for number, wire, value in decrypt_tool.read_wire_fields(payload)
        if number == 2
    ]


def find_list_response(session: Path) -> bytes:
    for metadata_path in sorted(session.glob("[0-9][0-9][0-9][0-9].txt")):
        text = metadata_path.read_text(encoding="utf-8", errors="replace")
        if "URL=https://game.resleriana.jp/gacha/list" not in text:
            continue
        response_path = metadata_path.with_name(f"{metadata_path.stem}-response.bin")
        plaintext, _ = decrypt_tool.decrypt_payload(response_path.read_bytes())
        decrypt_tool.read_wire_fields(plaintext)
        return plaintext
    raise ValueError(f"session {session} has no /gacha/list response")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("master", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    plaintext = find_list_response(args.session)
    top = decrypt_tool.read_wire_fields(plaintext)

    gacha_ids: list[int] = []
    rate_set_protos: dict[int, bytes] = {}
    mixed_protos: list[bytes] = []
    wishlist_banner_ids: list[int] = []
    notifications: bytes | None = None
    for number, wire, value in top:
        payload = bytes(value)
        if number == 1:
            fields = dict(
                (n, v) for n, w, v in decrypt_tool.read_wire_fields(payload) if w == 0
            )
            gacha_ids.append(int(fields[1]))
        elif number == 2:
            rate_id = next(
                int(v) for n, w, v in decrypt_tool.read_wire_fields(payload) if n == 1
            )
            rate_set_protos[rate_id] = payload
        elif number == 3:
            inner = decrypt_tool.read_wire_fields(payload)
            if any(n != 5 for n, _, _ in inner):
                raise ValueError("list changed_resources holds personal data; refusing")
            notifications = payload
        elif number == 4:
            wishlist_banner_ids.append(
                next(
                    int(v)
                    for n, w, v in decrypt_tool.read_wire_fields(payload)
                    if n == 1
                )
            )
        elif number == 5:
            mixed_protos.append(payload)

    if notifications is None:
        raise ValueError("list response has no notification payload")

    master = args.master
    gacha_master = {
        row["id"]: row
        for row in json.loads((master / "gacha.json").read_text(encoding="utf-8-sig"))
    }
    button_master = {
        row["id"]: row
        for row in json.loads(
            (master / "gacha_button.json").read_text(encoding="utf-8-sig")
        )
    }
    rate_master = {
        row["id"]: row
        for row in json.loads(
            (master / "gacha_rate.json").read_text(encoding="utf-8-sig")
        )
    }
    deck_master = {
        row["id"]: row
        for row in json.loads(
            (master / "gacha_deck.json").read_text(encoding="utf-8-sig")
        )
    }

    banners = []
    for gacha_id in gacha_ids:
        entry = gacha_master.get(gacha_id)
        if entry is None:
            raise ValueError(f"master data has no gacha {gacha_id}")
        buttons = []
        for group in entry.get("gacha_button_groups") or []:
            for button in group.get("gacha_buttons") or []:
                spec = button_master.get(button["id"])
                if spec is None:
                    raise ValueError(f"master data has no gacha button {button['id']}")
                cost = spec.get("cost") or {}
                buttons.append(
                    {
                        "id": int(spec["id"]),
                        "button_type": int(button["gacha_button_type"]),
                        "draws": int(spec["draw_count"]),
                        "cost_type": cost.get("type"),
                        "cost_id": cost.get("id"),
                        "cost_qty": cost.get("quantity"),
                        "medal_qty": int(spec.get("medal_quantity") or 0),
                        "add_medal": int(spec.get("additional_medal") or 0),
                        "is_daily": bool(spec.get("is_daily")),
                        "limit": spec.get("limit_count"),
                    }
                )
        banners.append(
            {
                "gacha_id": int(gacha_id),
                "rate_set_id": int(entry["gacha_rate_set_id"]),
                "ticket_id": entry.get("ticket_id"),
                "medal_id": entry.get("medal_id"),
                "bonuses": entry.get("bonuses_per_draw") or [],
                "wishlist": wishlist_rule(entry.get("mixed_wish_list")),
                "buttons": buttons,
            }
        )

    rate_sets = {}
    for rate_set_id, proto in rate_set_protos.items():
        rows = decode_rows(proto, rate_master, deck_master)
        summaries = []
        for number, wire, value in decrypt_tool.read_wire_fields(proto):
            payload = bytes(value)
            if number == 2:
                continue
            elif number == 3:
                fields = decrypt_tool.read_wire_fields(payload)
                summaries.append(
                    {
                        "card_type": next(int(v) for n, w, v in fields if n == 1),
                        "rarity": next(int(v) for n, w, v in fields if n == 2),
                        "percent": next(
                            bytes(v).decode("ascii") for n, w, v in fields if n == 3
                        ),
                    }
                )
        rate_sets[str(rate_set_id)] = {"rows": rows, "summaries": summaries}

    workspace_master = (
        Path(__file__).resolve().parent.parent.parent
        / "tools"
        / "JapaneseToolkit"
        / "share"
        / "game-root"
        / "progression-master"
        / "character.json"
    )
    char_rarity = {
        int(row["id"]): int(row["initial_rarity"])
        for row in json.loads(workspace_master.read_text(encoding="utf-8-sig"))
        if "initial_rarity" in row
    }
    mixed_rows = {}
    mixed_dynamic = {}
    for proto in mixed_protos:
        fields = decrypt_tool.read_wire_fields(proto)
        gacha_id = next(int(v) for n, w, v in fields if n == 1)
        mixed_rows[str(gacha_id)] = [
            decode_row(bytes(value), rate_master, deck_master)
            for number, wire, value in fields
            if number == 5
        ]
        dynamic_cards: dict[str, list[int]] = {"4": [], "17": []}
        dynamic_rates: dict[str, list[float]] = {}
        for number, wire, value in fields:
            if number != 4:
                continue
            entry = decrypt_tool.read_wire_fields(bytes(value))
            cards = [
                [int(v) for _, _, v in decrypt_tool.read_wire_fields(bytes(c))]
                for n, w, c in entry
                if n == 2
            ]
            card_type = cards[0][0] if cards else 0
            for card in cards:
                dynamic_cards.setdefault(str(card[0]), []).append(int(card[1]))
            for n, w, c in entry:
                if n != 3:
                    continue
                rate = decrypt_tool.read_wire_fields(bytes(c))
                counts = {q: int(v) for q, _, v in rate if q in (1, 2)}
                percent = next(
                    bytes(v).decode("ascii") for q, _, v in rate if q == 3
                )
                dynamic_rates.setdefault(
                    f"{counts.get(1, 0)},{counts.get(2, 0)}", [0.0, 0.0]
                )[0 if card_type == 4 else 1] = float(percent)
        rarity_map = {}
        for card_id in set(dynamic_cards.get("4", [])):
            if card_id not in char_rarity:
                raise ValueError(f"no master rarity for dynamic character {card_id}")
            rarity_map[str(card_id)] = char_rarity[card_id]
        mixed_dynamic[str(gacha_id)] = {
            "char_cards": sorted(set(dynamic_cards.get("4", []))),
            "mem_cards": sorted(set(dynamic_cards.get("17", []))),
            "rates": dynamic_rates,
            "rarity": rarity_map,
        }

    for banner in banners:
        rules = banner.get("wishlist")
        if not rules:
            continue
        dynamic = mixed_dynamic.get(str(banner["gacha_id"]), {})
        rarity_map = dynamic.setdefault("rarity", {})
        for card_id in rules.get("characters") or []:
            if str(card_id) not in rarity_map:
                if int(card_id) not in char_rarity:
                    raise ValueError(
                        f"no master rarity for pickup character {card_id}"
                    )
                rarity_map[str(card_id)] = char_rarity[int(card_id)]

    snapshot = {
        "banners": banners,
        "rate_sets": rate_sets,
        "rate_set_protos": {str(k): b64(v) for k, v in rate_set_protos.items()},
        "mixed_protos": [b64(proto) for proto in mixed_protos],
        "mixed_rows": mixed_rows,
        "mixed_dynamic": mixed_dynamic,
        "wishlist_banner_ids": wishlist_banner_ids,
        "notifications_b64": b64(notifications),
    }
    args.output.write_text(json.dumps(snapshot, separators=(",", ":")), encoding="utf-8")
    print(f"WROTE {args.output} banners={len(banners)} rate_sets={len(rate_sets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
