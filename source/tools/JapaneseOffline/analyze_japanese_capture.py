#!/usr/bin/env python3
"""Decode selected Japanese API captures into named protobuf JSON."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from Crypto.Cipher import AES

import contract_codec


ENDPOINT_TYPES = {
    "/dish/order": ("blend.api.DishOrderRequest", "blend.api.DishOrderResponse"),
    "/expedition/start": ("blend.api.ExpeditionStartRequest", "blend.api.ExpeditionStartResponse"),
    "/expedition/reward_receive": (
        "google.protobuf.Empty",
        "blend.api.ExpeditionRewardReceiveResponse",
    ),
    "/exploration/start": ("blend.api.ExplorationStartRequest", "blend.api.ChangedResourcesResponse"),
    "/exploration/update_party": ("blend.api.ExplorationUpdatePartyRequest", "blend.api.ChangedResourcesResponse"),
    "/exploration/explore": ("blend.api.ExplorationExploreRequest", "blend.api.ExplorationExploreResponse"),
    "/exploration/battle_start": ("blend.api.ExplorationBattleStartRequest", "blend.api.BattleStartResponse"),
    "/exploration/finish": ("blend.api.ExplorationFinishRequest", "blend.api.ExplorationFinishResponse"),
    "/exploration/retire": ("blend.api.ExplorationRetireRequest", "blend.api.ChangedResourcesResponse"),
    "/exploration/skip": ("blend.api.ExplorationSkipRequest", "blend.api.ExplorationSkipResponse"),
    "/login_bonus/receive": ("google.protobuf.Empty", "blend.api.LoginBonusReceiveResponse"),
    "/mail/list": ("google.protobuf.Empty", "blend.api.MailListResponse"),
    "/mail/open": ("blend.api.MailOpenRequest", "blend.api.MailOpenResponse"),
    "/party/bulk_update": ("blend.api.PartyBulkUpdateRequest", "blend.api.ChangedResourcesResponse"),
    "/party/battle_tools_set": ("blend.api.PartyBattleToolsSetRequest", "blend.api.ChangedResourcesResponse"),
    "/character/equip": ("blend.api.CharacterEquipRequest", "blend.api.ChangedResourcesResponse"),
    "/character/memoria_set": ("blend.api.CharacterMemoriaSetRequest", "blend.api.ChangedResourcesResponse"),
    "/battle/attack": ("blend.api.BattleAttackRequest", "blend.api.BattleAttackResponse"),
    "/battle/resume": ("google.protobuf.Empty", "blend.api.BattleResumeResponse"),
    "/battle/retire": ("google.protobuf.Empty", "blend.api.ChangedResourcesResponse"),
    "/battle/finish": ("google.protobuf.Empty", "blend.api.BattleFinishResponse"),
    "/quest/battle/start": ("blend.api.QuestBattleStartRequest", "blend.api.BattleStartResponse"),
    "/quest/battle/total_battle_start": (
        "blend.api.QuestBattleTotalBattleStartRequest",
        "blend.api.BattleStartResponse",
    ),
    "/quest/battle/solo_raid_battle_start": (
        "blend.api.QuestBattleSoloRaidBattleStartRequest",
        "blend.api.BattleStartResponse",
    ),
    "/quest/battle/rental_party_start": (
        "blend.api.QuestBattleRentalPartyStartRequest",
        "blend.api.BattleStartResponse",
    ),
    "/quest/battle/skip": ("blend.api.QuestBattleSkipRequest", "blend.api.QuestBattleSkipResponse"),
    "/gacha/battle_start": ("blend.api.GachaBattleStartRequest", "blend.api.BattleStartResponse"),
    "/profile/update_name": ("blend.api.ProfileUpdateNameRequest", "blend.api.ChangedResourcesResponse"),
    "/profile/update_memo": ("blend.api.ProfileUpdateMemoRequest", "blend.api.ChangedResourcesResponse"),
    "/profile/update_favorite_character": (
        "blend.api.ProfileUpdateFavoriteCharacterRequest",
        "blend.api.ChangedResourcesResponse",
    ),
    "/profile/update_favorite_party": (
        "blend.api.ProfileUpdateFavoritePartyRequest",
        "blend.api.ChangedResourcesResponse",
    ),
    "/profile/update_favorite_battle_tools": (
        "blend.api.ProfileUpdateFavoriteBattleToolsRequest",
        "blend.api.ChangedResourcesResponse",
    ),
    "/profile/update_chara_home_favorite_character_list": (
        "blend.api.ProfileUpdateCharaHomeFavoriteCharacterListRequest",
        "blend.api.ChangedResourcesResponse",
    ),
    "/profile/update_selected_home_id": (
        "blend.api.ProfileUpdateSelectedHomeIdRequest",
        "blend.api.ChangedResourcesResponse",
    ),
    "/recipe/favorite": ("blend.api.RecipeFavoriteRequest", "blend.api.ChangedResourcesResponse"),
    "/synthesis/bulk_execute": (
        "blend.api.SynthesisBulkExecuteRequest",
        "blend.api.SynthesisExecuteResponse",
    ),
    "/synthesis/combination_ranking": (
        "blend.api.SynthesisCombinationRankingRequest",
        "blend.api.SynthesisCombinationRankingResponse",
    ),
    "/synthesis/execute_easy": (
        "blend.api.SynthesisExecuteEasyRequest",
        "blend.api.SynthesisExecuteEasyResponse",
    ),
    "/synthesis/execute_rental": (
        "blend.api.SynthesisExecuteRentalRequest",
        "blend.api.SynthesisExecuteResponse",
    ),
    "/quest/street/start": (
        "blend.api.QuestStreetStartRequest",
        "blend.api.ChangedResourcesResponse",
    ),
    "/quest/street/talk": (
        "blend.api.QuestStreetTalkRequest",
        "blend.api.ChangedResourcesResponse",
    ),
}


JAPANESE_AES_IV = bytes.fromhex("65a99b89a634fca3193c5212e5219378")


def rotate_key(key: bytes, count: int) -> bytes:
    value = int.from_bytes(key, "big")
    value = ((value << count) & ((1 << 128) - 1)) | (value >> (128 - count))
    return value.to_bytes(16, "big")


JAPANESE_AES_KEYS = tuple(
    rotate_key(seed, rotation)
    for seed in (
        bytes.fromhex("487a9961c947f7d92ed6b79fc0545fea"),
        bytes.fromhex("ea5f54c09fb7d62ed9f747c961997a48"),
    )
    for rotation in range(128)
)


def metadata_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("empty padded payload")
    padding = data[-1]
    if not 0 < padding <= AES.block_size or data[-padding:] != bytes([padding]) * padding:
        raise ValueError("invalid PKCS#7 padding")
    return data[:-padding]


def decrypt_request(data: bytes) -> tuple[bytes, bytes, bytes]:
    if not data:
        return b"", b"", b""
    if len(data) < 17 or (len(data) - 1) % AES.block_size:
        raise ValueError("request is not a marker followed by AES blocks")
    marker = data[0]
    key = JAPANESE_AES_KEYS[marker]
    padded = AES.new(key, AES.MODE_CBC, JAPANESE_AES_IV).decrypt(data[1:])
    return pkcs7_unpad(padded), key, JAPANESE_AES_IV


def decrypt_response(
    data: bytes,
) -> tuple[bytes, int, bytes, bytes]:
    if len(data) < 17 or (len(data) - 1) % AES.block_size:
        raise ValueError("response is not a marker followed by AES blocks")
    marker = data[0]
    key = JAPANESE_AES_KEYS[marker]
    padded = AES.new(key, AES.MODE_CBC, JAPANESE_AES_IV).decrypt(data[1:])
    compressed = pkcs7_unpad(padded)
    try:
        plaintext = gzip.decompress(compressed)
    except (OSError, EOFError):
        plaintext = compressed
    return plaintext, marker, key, JAPANESE_AES_IV


def decode_message(contract_db, name: str, data: bytes) -> dict[str, Any]:
    if name == "google.protobuf.Empty" and not data:
        return {"$message": name}
    return contract_codec.decode_message(contract_db, name, data)


def fingerprint(value: bytes) -> str | None:
    return hashlib.sha256(value).hexdigest()[:12] if value else None


def selected_records(session: Path, endpoints: set[str], records: set[int]) -> list[tuple[int, Path, dict[str, str]]]:
    selected = []
    for metadata_path in sorted(session.glob("[0-9][0-9][0-9][0-9].txt")):
        values = metadata_values(metadata_path)
        endpoint = metadata_path and values.get("URL", "").split("game.resleriana.jp", 1)[-1]
        if "?" in endpoint:
            endpoint = endpoint.split("?", 1)[0]
        if endpoint not in ENDPOINT_TYPES:
            continue
        number = int(metadata_path.stem)
        if endpoints and endpoint not in endpoints:
            continue
        if records and number not in records:
            continue
        selected.append((number, metadata_path, values))
    return selected


def analyze(args: argparse.Namespace) -> list[dict[str, Any]]:
    session = args.session.resolve()
    contract_db = contract_codec.parse_fields_txt(args.contract_fields.resolve())
    endpoints = set(args.endpoint)
    records = set(args.record)
    results: list[dict[str, Any]] = []

    for number, metadata_path, values in selected_records(session, endpoints, records):
        endpoint = values["URL"].split("game.resleriana.jp", 1)[-1].split("?", 1)[0]
        request_name, response_name = ENDPOINT_TYPES[endpoint]
        request_path = session / f"{number:04d}-request.bin"
        response_path = session / f"{number:04d}-response.bin"
        result: dict[str, Any] = {
            "record": number,
            "endpoint": endpoint,
            "status": int(values.get("STATUS", "0")),
            "request_type": request_name,
            "response_type": response_name,
            "request_bytes": request_path.stat().st_size if request_path.exists() else 0,
            "response_bytes": response_path.stat().st_size if response_path.exists() else 0,
        }
        try:
            request_data = request_path.read_bytes() if request_path.exists() else b""
            request, request_key, request_iv = decrypt_request(request_data)
            result["request"] = decode_message(contract_db, request_name, request)
            result["request_crypto"] = {
                "key_fingerprint": fingerprint(request_key),
                "iv_fingerprint": fingerprint(request_iv),
            }
        except (OSError, ValueError, TypeError) as error:
            result["request_error"] = f"{type(error).__name__}: {error}"
        try:
            response, marker, response_key, response_iv = decrypt_response(
                response_path.read_bytes(),
            )
            result["response"] = decode_message(contract_db, response_name, response)
            result["response_crypto"] = {
                "marker": marker,
                "key_fingerprint": fingerprint(response_key),
                "iv_fingerprint": fingerprint(response_iv),
            }
        except (OSError, ValueError, TypeError) as error:
            result["response_error"] = f"{type(error).__name__}: {error}"
        results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path, help="capture session directory")
    parser.add_argument(
        "--contract-fields",
        type=Path,
        default=Path("C:/Program Files (x86)/Steam/steamapps/common/AtelierResleriana/contract-dump/fields.txt"),
        help="client contract-dump fields.txt",
    )
    parser.add_argument("--endpoint", action="append", default=[], help="only analyze this endpoint; repeatable")
    parser.add_argument("--record", type=int, action="append", default=[], help="only analyze this record; repeatable")
    parser.add_argument("--list", action="store_true", help="list captured endpoints and counts")
    parser.add_argument("--output", type=Path, help="write JSON to this path instead of stdout")
    args = parser.parse_args()

    if args.list:
        counts = Counter(result["endpoint"] for result in analyze(args))
        output: Any = dict(sorted(counts.items()))
    else:
        output = analyze(args)
    # Keep stdout portable across Windows consoles that do not use UTF-8.
    text = json.dumps(output, ensure_ascii=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
