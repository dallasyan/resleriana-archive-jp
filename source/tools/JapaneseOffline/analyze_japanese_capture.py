#!/usr/bin/env python3
"""Decode selected Japanese API captures into named protobuf JSON."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from Crypto.Cipher import AES
from google.protobuf import json_format, message_factory
from google.protobuf.message import DecodeError


def find_editor_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        for name in ("JapaneseProfileEditor", "profile-editor"):
            candidate = parent / name
            if (candidate / "profile_editor.py").is_file():
                return candidate
    raise FileNotFoundError("could not locate profile_editor.py")


EDITOR_DIR = find_editor_dir()
sys.path.insert(0, str(EDITOR_DIR))

import profile_editor


ENDPOINT_TYPES = {
    "/exploration/start": ("blend.api.ExplorationStartRequest", "blend.api.ChangedResourcesResponse"),
    "/exploration/update_party": ("blend.api.ExplorationUpdatePartyRequest", "blend.api.ChangedResourcesResponse"),
    "/exploration/explore": ("blend.api.ExplorationExploreRequest", "blend.api.ExplorationExploreResponse"),
    "/exploration/battle_start": ("blend.api.ExplorationBattleStartRequest", "blend.api.BattleStartResponse"),
    "/exploration/finish": ("blend.api.ExplorationFinishRequest", "blend.api.ExplorationFinishResponse"),
    "/exploration/retire": ("blend.api.ExplorationRetireRequest", "blend.api.ChangedResourcesResponse"),
    "/exploration/skip": ("blend.api.ExplorationSkipRequest", "blend.api.ExplorationSkipResponse"),
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
}


def metadata_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def infer_game_root(session: Path) -> Path:
    resolved = session.resolve()
    if resolved.parent.name == "japanese-capture":
        return resolved.parent.parent
    return resolved.parent


def material_paths(session: Path, game_root: Path, explicit: list[Path]) -> list[Path]:
    candidates = list(explicit)
    candidates.extend((game_root / name for name in ("aes-material.json",)))
    candidates.append(session / "aes-material.json")
    candidates.extend((game_root / "japanese-capture").rglob("aes-material.json"))

    result: list[Path] = []
    for path in candidates:
        path = path.resolve()
        if path.is_file() and path not in result:
            result.append(path)
    return result


def load_candidates(paths: list[Path]) -> tuple[list[bytes], list[bytes]]:
    keys: list[bytes] = []
    ivs: list[bytes] = []
    for path in paths:
        try:
            path_keys, path_ivs = profile_editor.load_material(path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        for key in path_keys:
            if key not in keys:
                keys.append(key)
        for iv in path_ivs:
            if iv not in ivs:
                ivs.append(iv)
    if not keys or not ivs:
        raise ValueError("no usable AES material was found")
    return keys, ivs


def decrypt_request(
    data: bytes,
    message_class,
    keys: list[bytes],
    ivs: list[bytes],
) -> tuple[Any, bytes, bytes]:
    if not data:
        message = message_class()
        return message, b"", b""
    if len(data) < 17 or (len(data) - 1) % AES.block_size:
        raise ValueError("request is not a marker followed by AES blocks")
    last_error: Exception | None = None
    for key in keys:
        for iv in ivs:
            try:
                padded = AES.new(key, AES.MODE_CBC, iv).decrypt(data[1:])
                plaintext = profile_editor.pkcs7_unpad(padded)
                message = message_class()
                message.ParseFromString(plaintext)
                return message, key, iv
            except (DecodeError, ValueError, TypeError) as error:
                last_error = error
    raise ValueError(f"request could not be decrypted: {last_error}")


def decrypt_response(
    data: bytes,
    message_class,
    keys: list[bytes],
    ivs: list[bytes],
) -> tuple[Any, int, bytes, bytes]:
    if len(data) < 17 or (len(data) - 1) % AES.block_size:
        raise ValueError("response is not a marker followed by AES blocks")
    last_error: Exception | None = None
    for key in keys:
        for iv in ivs:
            try:
                padded = AES.new(key, AES.MODE_CBC, iv).decrypt(data[1:])
                compressed = profile_editor.pkcs7_unpad(padded)
                plaintext = gzip.decompress(compressed)
                message = message_class()
                message.ParseFromString(plaintext)
                return message, data[0], key, iv
            except (DecodeError, OSError, EOFError, ValueError, TypeError) as error:
                last_error = error
    raise ValueError(f"response could not be decrypted: {last_error}")


def message_class(pool, name: str):
    return message_factory.GetMessageClass(pool.FindMessageTypeByName(name))


def message_json(message: Any) -> dict[str, Any]:
    return json_format.MessageToDict(
        message,
        preserving_proto_field_name=True,
        use_integers_for_enums=False,
    )


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
    game_root = (args.game_root or infer_game_root(session)).resolve()
    descriptor_path = args.descriptor.resolve()
    pool = profile_editor.load_descriptor_pool(descriptor_path)
    keys, ivs = load_candidates(material_paths(session, game_root, args.material))
    endpoints = set(args.endpoint)
    records = set(args.record)
    results: list[dict[str, Any]] = []

    for number, metadata_path, values in selected_records(session, endpoints, records):
        endpoint = values["URL"].split("game.resleriana.jp", 1)[-1].split("?", 1)[0]
        request_name, response_name = ENDPOINT_TYPES[endpoint]
        request_class = message_class(pool, request_name)
        response_class = message_class(pool, response_name)
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
            request, request_key, request_iv = decrypt_request(request_data, request_class, keys, ivs)
            result["request"] = message_json(request)
            result["request_crypto"] = {
                "key_fingerprint": fingerprint(request_key),
                "iv_fingerprint": fingerprint(request_iv),
            }
        except (OSError, ValueError, TypeError) as error:
            result["request_error"] = f"{type(error).__name__}: {error}"
        try:
            response, marker, response_key, response_iv = decrypt_response(
                response_path.read_bytes(),
                response_class,
                keys,
                ivs,
            )
            result["response"] = message_json(response)
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
    parser.add_argument("--game-root", type=Path, help="game root containing japanese-capture")
    parser.add_argument(
        "--descriptor",
        type=Path,
        default=EDITOR_DIR / "profile-descriptors.pb",
        help="protobuf descriptor set",
    )
    parser.add_argument("--material", type=Path, action="append", default=[], help="additional AES material file")
    parser.add_argument("--endpoint", action="append", default=[], help="only analyze this endpoint; repeatable")
    parser.add_argument("--record", type=int, action="append", default=[], help="only analyze this record; repeatable")
    parser.add_argument("--list", action="store_true", help="list captured battle/exploration endpoints and counts")
    parser.add_argument("--output", type=Path, help="write JSON to this path instead of stdout")
    args = parser.parse_args()

    if args.list:
        counts = Counter(result["endpoint"] for result in analyze(args))
        output: Any = dict(sorted(counts.items()))
    else:
        output = analyze(args)
    text = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
