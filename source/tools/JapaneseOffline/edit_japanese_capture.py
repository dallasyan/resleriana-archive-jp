"""Decrypt, edit, and re-encrypt Japanese network capture sessions."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

from Crypto.Cipher import AES
from google.protobuf import json_format, message_factory

from decrypt_japanese_capture import AES_IV, AES_KEYS, format_fields, read_wire_fields, read_varint


ENDPOINT_TYPES = {
    "/login_bonus/receive": ("google.protobuf.Empty", "blend.api.LoginBonusReceiveResponse"),
    "/recipe/learn": ("blend.api.RecipeLearnRequest", "blend.api.ChangedResourcesResponse"),
    "/illustrated_book/start": ("blend.api.IllustratedBookStartRequest", "blend.api.IllustratedBookStartResponse"),
    "/character/skin_set": ("blend.api.CharacterSkinSetRequest", "blend.api.ChangedResourcesResponse"),
    "/profile/update_selected_home_id": ("blend.api.UpdateSelectedHomeIdRequest", "blend.api.ChangedResourcesResponse"),
    "/chara_home/register": ("blend.api.CharaHomeRegisterRequest", "blend.api.ChangedResourcesResponse"),
    "/exploration/start": ("blend.api.ExplorationStartRequest", "blend.api.ChangedResourcesResponse"),
    "/exploration/update_party": ("blend.api.ExplorationUpdatePartyRequest", "blend.api.ChangedResourcesResponse"),
    "/exploration/explore": ("blend.api.ExplorationExploreRequest", "blend.api.ExplorationExploreResponse"),
    "/exploration/battle_start": ("blend.api.ExplorationBattleStartRequest", "blend.api.BattleStartResponse"),
    "/exploration/finish": ("blend.api.ExplorationFinishRequest", "blend.api.ExplorationFinishResponse"),
    "/exploration/retire": ("blend.api.ExplorationRetireRequest", "blend.api.ChangedResourcesResponse"),
    "/exploration/skip": ("blend.api.ExplorationSkipRequest", "blend.api.ExplorationSkipResponse"),
    "/party/bulk_update": ("blend.api.PartyBulkUpdateRequest", "blend.api.ChangedResourcesResponse"),
    "/party/battle_tools_set": ("blend.api.PartyBattleToolsSetRequest", "blend.api.ChangedResourcesResponse"),
    "/character/enhance": ("blend.api.CharacterEnhanceRequest", "blend.api.ChangedResourcesResponse"),
    "/character/rarity_enhance": ("blend.api.CharacterRarityEnhanceRequest", "blend.api.ChangedResourcesResponse"),
    "/character/growboard_page_release": (
        "blend.api.CharacterGrowboardPageReleaseRequest", "blend.api.ChangedResourcesResponse"
    ),
    "/character/growboard_bulk_release": (
        "blend.api.CharacterGrowboardBulkReleaseRequest", "blend.api.ChangedResourcesResponse"
    ),
    "/character/enhancement_reset": (
        "blend.api.CharacterEnhancementResetRequest", "blend.api.CharacterEnhancementResetResponse"
    ),
    "/character/level_limit_release": (
        "blend.api.CharacterLevelLimitReleaseRequest", "blend.api.ChangedResourcesResponse"
    ),
    "/character/bulk_set": ("blend.api.CharacterBulkSetRequest", "blend.api.ChangedResourcesResponse"),
    "/character/equip": ("blend.api.CharacterEquipRequest", "blend.api.ChangedResourcesResponse"),
    "/character/memoria_set": ("blend.api.CharacterMemoriaSetRequest", "blend.api.ChangedResourcesResponse"),
    "/equipment_preset/equip": ("blend.api.EquipmentPresetEquipRequest", "blend.api.ChangedResourcesResponse"),
    "/equipment_preset/memoria_set": (
        "blend.api.EquipmentPresetMemoriaSetRequest", "blend.api.ChangedResourcesResponse"
    ),
    "/equipment_preset/update_name": (
        "blend.api.EquipmentPresetUpdateNameRequest", "blend.api.ChangedResourcesResponse"
    ),
    "/memoria/enhance": ("blend.api.MemoriaEnhanceRequest", "blend.api.MemoriaEnhanceResponse"),
    "/memoria/limit_break": ("blend.api.MemoriaLimitBreakRequest", "blend.api.MemoriaLimitBreakResponse"),
    "/memoria/lock": ("blend.api.MemoriaLockRequest", "blend.api.ChangedResourcesResponse"),
    "/memoria/sell": ("blend.api.MemoriaSellRequest", "blend.api.MemoriaSellResponse"),
    "/battle/attack": ("blend.api.BattleAttackRequest", "blend.api.BattleAttackResponse"),
    "/battle/resume": ("google.protobuf.Empty", "blend.api.BattleResumeResponse"),
    "/battle/retire": ("google.protobuf.Empty", "blend.api.ChangedResourcesResponse"),
    "/battle/finish": ("google.protobuf.Empty", "blend.api.BattleFinishResponse"),
    "/quest/battle/start": ("blend.api.QuestBattleStartRequest", "blend.api.BattleStartResponse"),
    "/quest/battle/total_battle_start": (
        "blend.api.QuestBattleTotalBattleStartRequest", "blend.api.BattleStartResponse"
    ),
    "/quest/battle/solo_raid_battle_start": (
        "blend.api.QuestBattleSoloRaidBattleStartRequest", "blend.api.BattleStartResponse"
    ),
    "/quest/battle/rental_party_start": (
        "blend.api.QuestBattleRentalPartyStartRequest", "blend.api.BattleStartResponse"
    ),
    "/quest/battle/skip": ("blend.api.QuestBattleSkipRequest", "blend.api.QuestBattleSkipResponse"),
    "/gacha/battle_start": ("blend.api.GachaBattleStartRequest", "blend.api.BattleStartResponse"),
}


def locate_editor() -> Path:
    for parent in Path(__file__).resolve().parents:
        for name in ("JapaneseProfileEditor", "profile-editor"):
            candidate = parent / name
            if (candidate / "profile_editor.py").is_file():
                return candidate
    raise FileNotFoundError("could not locate profile_editor.py")


EDITOR = locate_editor()
sys.path.insert(0, str(EDITOR))
import profile_editor  # noqa: E402


def metadata(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def endpoint_for(session: Path, number: int) -> str | None:
    path = session / f"{number:04d}.txt"
    if not path.exists():
        return None
    url = metadata(path).get("URL", "")
    return url.split("game.resleriana.jp", 1)[-1].split("?", 1)[0] or None


def decrypt(data: bytes) -> tuple[bytes, dict[str, object]]:
    if len(data) < 17 or (len(data) - 1) % AES.block_size:
        raise ValueError("not marker-prefixed AES data")
    marker = data[0]
    padded = AES.new(AES_KEYS[marker], AES.MODE_CBC, AES_IV).decrypt(data[1:])
    padding = padded[-1]
    if not 0 < padding <= AES.block_size or padded[-padding:] != bytes([padding]) * padding:
        raise ValueError("invalid PKCS#7 padding")
    compressed = padded[:-padding]
    try:
        plaintext = gzip.decompress(compressed)
        compressed_flag = True
    except (OSError, EOFError):
        plaintext = compressed
        compressed_flag = False
    return plaintext, {"encrypted": True, "compressed": compressed_flag, "marker": marker}


def encrypt(data: bytes, crypto: dict[str, object]) -> bytes:
    if not crypto.get("encrypted"):
        return data
    marker = int(crypto["marker"])
    payload = gzip.compress(data, mtime=0) if crypto.get("compressed") else data
    padding = AES.block_size - len(payload) % AES.block_size
    padded = payload + bytes([padding]) * padding
    return bytes([marker]) + AES.new(AES_KEYS[marker], AES.MODE_CBC, AES_IV).encrypt(padded)


def message_class(pool, name: str):
    return message_factory.GetMessageClass(pool.FindMessageTypeByName(name))


def json_path(binary_path: Path) -> Path:
    return binary_path.with_suffix(".json")


def crypto_path(binary_path: Path) -> Path:
    return binary_path.with_suffix(binary_path.suffix + ".crypto.json")


def wire_json(data: bytes) -> dict[str, object]:
    result = []
    for number, wire, value in read_wire_fields(data):
        item: dict[str, object] = {"number": number, "wire_type": wire}
        if wire == 0:
            item["value"] = int(value)
        else:
            item["value_hex"] = bytes(value).hex()
            if wire == 2:
                try:
                    item["nested"] = wire_json(bytes(value))
                except ValueError:
                    pass
        result.append(item)
    return {"wire_fields": result}


def write_varint(value: int) -> bytes:
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def write_field(number: int, wire: int, value: object) -> bytes:
    encoded = write_varint((number << 3) | wire)
    if wire == 0:
        return encoded + write_varint(int(value))
    payload = bytes.fromhex(str(value))
    return encoded + (payload if wire in (1, 5) else write_varint(len(payload)) + payload)


def wire_bytes(value: dict[str, object]) -> bytes:
    fields = value.get("wire_fields")
    if not isinstance(fields, list):
        raise ValueError("wire JSON has no wire_fields list")
    return b"".join(
        write_field(int(item["number"]), int(item["wire_type"]), item.get("value", item.get("value_hex", "")))
        for item in fields
    )


def decrypt_folder(source: Path, destination: Path, descriptor: Path) -> None:
    pool = profile_editor.load_descriptor_pool(descriptor)
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.iterdir()):
        if path.is_dir():
            decrypt_folder(path, destination / path.name, descriptor)
            continue
        if path.suffix.lower() != ".bin":
            (destination / path.name).write_bytes(path.read_bytes())
            continue
        output = destination / path.name
        raw = path.read_bytes()
        try:
            plaintext, crypto = decrypt(raw)
        except (IndexError, ValueError):
            output.write_bytes(raw)
            continue
        output.write_bytes(plaintext)
        crypto_path(output).write_text(json.dumps(crypto, indent=2) + "\n", encoding="utf-8")
        try:
            output.with_suffix(output.suffix + ".protobuf.txt").write_text(
                "\n".join(format_fields(plaintext)) + "\n", encoding="utf-8"
            )
        except ValueError:
            pass

        number_text = path.stem.split("-", 1)[0]
        if not number_text.isdigit():
            continue
        endpoint = endpoint_for(source, int(number_text))
        kind = "request" if "request" in path.stem else "response"
        type_pair = ENDPOINT_TYPES.get(endpoint or "")
        if type_pair is None:
            continue
        type_name = type_pair[0] if kind == "request" else type_pair[1]
        try:
            message = message_class(pool, type_name)()
            message.ParseFromString(plaintext)
            json_path(output).write_text(
                json_format.MessageToJson(
                    message,
                    preserving_proto_field_name=True,
                    indent=2,
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass
        try:
            wire_path = output.with_suffix(output.suffix + ".wire.json")
            wire_path.write_text(json.dumps(wire_json(plaintext), indent=2) + "\n", encoding="utf-8")
        except ValueError:
            pass


def encrypt_folder(source: Path, destination: Path, descriptor: Path) -> None:
    pool = profile_editor.load_descriptor_pool(descriptor)
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.iterdir()):
        if path.is_dir():
            encrypt_folder(path, destination / path.name, descriptor)
            continue
        if path.suffix.lower() != ".bin":
            (destination / path.name).write_bytes(path.read_bytes())
            continue
        crypto_file = crypto_path(path)
        crypto = json.loads(crypto_file.read_text(encoding="utf-8")) if crypto_file.exists() else {"encrypted": False}
        plaintext = path.read_bytes()
        number_text = path.stem.split("-", 1)[0]
        endpoint = endpoint_for(source, int(number_text)) if number_text.isdigit() else None
        kind = "request" if "request" in path.stem else "response"
        type_pair = ENDPOINT_TYPES.get(endpoint or "")
        editable = json_path(path)
        if editable.exists() and type_pair is not None:
            type_name = type_pair[0] if kind == "request" else type_pair[1]
            message = message_class(pool, type_name)()
            json_format.Parse(editable.read_text(encoding="utf-8"), message)
            plaintext = message.SerializeToString()
        else:
            wire_editable = path.with_suffix(path.suffix + ".wire.json")
            if wire_editable.exists():
                plaintext = wire_bytes(json.loads(wire_editable.read_text(encoding="utf-8")))
        (destination / path.name).write_bytes(encrypt(plaintext, crypto))
        if editable.exists():
            (destination / editable.name).write_text(editable.read_text(encoding="utf-8"), encoding="utf-8")
        if crypto_file.exists():
            (destination / crypto_file.name).write_text(crypto_file.read_text(encoding="utf-8"), encoding="utf-8")
        wire_editable = path.with_suffix(path.suffix + ".wire.json")
        if wire_editable.exists():
            (destination / wire_editable.name).write_text(wire_editable.read_text(encoding="utf-8"), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("decrypt", "encrypt"))
    parser.add_argument("input", type=Path, help="capture directory")
    parser.add_argument("--output", type=Path, help="output directory")
    parser.add_argument(
        "--descriptor",
        type=Path,
        default=EDITOR / "profile-descriptors.pb",
        help="protobuf descriptor set for editable JSON messages",
    )
    args = parser.parse_args()
    source = args.input.resolve()
    if not source.is_dir():
        parser.error("input must be a capture directory")
    if args.output:
        destination = args.output.resolve()
    else:
        prefix = "decrypted-" if args.command == "decrypt" else "encrypted-"
        name = source.name.removeprefix("decrypted-").removeprefix("encrypted-")
        destination = source.with_name(prefix + name)
    if args.command == "decrypt":
        decrypt_folder(source, destination, args.descriptor)
    else:
        encrypt_folder(source, destination, args.descriptor)
    print(f"WROTE {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
