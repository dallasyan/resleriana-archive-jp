#!/usr/bin/env python3
"""Inspect and edit Atelier Resleriana Japanese profile.bin files."""

from __future__ import annotations

import argparse
import base64
import datetime
import gzip
import json
import os
import re
import shutil
import sys
import zlib
from pathlib import Path
from typing import Any

from Crypto.Cipher import AES
from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory


DEFAULT_KEY = bytes.fromhex("2c332f491d4bea9813f6fac5db3ee8f9")
DEFAULT_IV = bytes.fromhex("65a99b89a634fca3193c5212e5219378")
# Profiles produced by the editor can be shared without the source user's AES material.
SHARE_PROFILE_KEY = bytes.fromhex("5243d4cb0e4a3fbec976b5bcfe02a2ff")
SHARE_PROFILE_IV = bytes.fromhex("65a99b89a634fca3193c5212e5219378")
JAPANESE_AES_IV = SHARE_PROFILE_IV


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
TOP_LEVEL_MESSAGE = "blend.api.UserLogInResponse"
DEFAULT_ANONYMIZED_SESSION_TOKEN = "00000000-0000-4000-8000-000000000000"
MAX_CHARACTER_LEVEL = 100
CHARACTER_STORY_BASE_CONDITION = 2


def default_game_root() -> Path:
    candidates: list[Path] = []
    configured_root = os.environ.get("JAPANESE_GAME_DIR")
    if configured_root:
        candidates.append(Path(configured_root))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)
    candidates.append(Path.cwd())
    source_root = Path(__file__).resolve().parent
    candidates.extend((source_root / "game-root", source_root.parent / "game-root"))

    for root in candidates:
        if (root / "profile.bin").is_file():
            return root
    for root in candidates:
        if (root / "AtelierResleriana.exe").is_file():
            return root
    return candidates[0] if candidates else Path.cwd()


def default_profile_path() -> Path:
    return default_game_root() / "profile.bin"


def default_observer_material_path(profile_path: Path) -> Path | None:
    capture_roots = (profile_path.parent / "japanese-capture",)
    observers = sorted(
        (
            directory / "aes-material.json"
            for capture_root in capture_roots
            for directory in capture_root.glob("native-observer-*")
            if directory.is_dir() and (directory / "aes-material.json").is_file()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if observers:
        return observers[0]
    root_material = profile_path.parent / "aes-material.json"
    return root_material if root_material.is_file() else None


def parse_hex(value: str, name: str) -> bytes:
    try:
        result = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError(f"{name} must be hexadecimal") from error
    if len(result) not in (16, 24, 32) if name == "key" else len(result) != 16:
        expected = "16, 24, or 32" if name == "key" else "16"
        raise ValueError(f"{name} must be {expected} bytes")
    return result


def parse_player_id(value: str) -> str:
    if not value or any(character not in "0123456789'" for character in value):
        raise argparse.ArgumentTypeError("player ID must contain only decimal digits and optional apostrophes")
    digits = value.replace("'", "")
    if not digits:
        raise argparse.ArgumentTypeError("player ID must contain at least one digit")
    numeric_id = int(digits, 10)
    if numeric_id > 9_223_372_036_854_775_807:
        raise argparse.ArgumentTypeError("player ID must fit in a signed 64-bit integer")
    return value


def load_material(path: Path) -> tuple[list[bytes], list[bytes]]:
    material = json.loads(path.read_text(encoding="utf-8"))
    key_values = material.get("key_candidates") or ([material["key"]] if material.get("key") else [])
    iv_values = material.get("iv_candidates") or ([material["iv"]] if material.get("iv") else [])
    keys = [parse_hex(value, "key") for value in key_values]
    ivs = [parse_hex(value, "iv") for value in iv_values]
    if not keys or not ivs:
        raise ValueError(f"key material file has no usable key/IV candidates: {path}")
    for key in (SHARE_PROFILE_KEY, DEFAULT_KEY):
        if key not in keys:
            keys.append(key)
    for iv in (SHARE_PROFILE_IV, DEFAULT_IV):
        if iv not in ivs:
            ivs.append(iv)
    return keys, ivs


def pkcs7_unpad(data: bytes) -> bytes:
    if not data or len(data) % AES.block_size:
        raise ValueError("AES plaintext is not block aligned")
    padding = data[-1]
    if padding < 1 or padding > AES.block_size or data[-padding:] != bytes([padding]) * padding:
        raise ValueError("invalid PKCS#7 padding")
    return data[:-padding]


def pkcs7_pad(data: bytes) -> bytes:
    padding = AES.block_size - (len(data) % AES.block_size)
    return data + bytes([padding]) * padding


def decrypt_profile(data: bytes, key: bytes, iv: bytes) -> tuple[bytes, int]:
    if len(data) < 17 or (len(data) - 1) % AES.block_size:
        raise ValueError("profile is not a one-byte marker followed by AES blocks")
    marker = data[0]
    padded_gzip = AES.new(key, AES.MODE_CBC, iv).decrypt(data[1:])
    compressed = pkcs7_unpad(padded_gzip)
    try:
        return gzip.decompress(compressed), marker
    except (OSError, EOFError, zlib.error) as error:
        raise ValueError("AES plaintext is not a valid gzip stream") from error


def decrypt_with_candidates(data: bytes, keys: list[bytes], ivs: list[bytes]):
    marker = data[0] if data else -1
    if 0 <= marker < len(JAPANESE_AES_KEYS):
        try:
            return (*decrypt_profile(data, JAPANESE_AES_KEYS[marker], JAPANESE_AES_IV), JAPANESE_AES_KEYS[marker], JAPANESE_AES_IV)
        except ValueError:
            pass
    last_error = None
    for key in keys:
        for iv in ivs:
            try:
                protobuf_data, marker = decrypt_profile(data, key, iv)
                return protobuf_data, marker, key, iv
            except ValueError as error:
                last_error = error
    raise ValueError(f"none of the supplied key/IV candidates decrypt the profile: {last_error}")


def encrypt_profile(protobuf_data: bytes, key: bytes, iv: bytes, marker: int) -> bytes:
    compressed = gzip.compress(protobuf_data, mtime=0)
    response_key = JAPANESE_AES_KEYS[marker]
    ciphertext = AES.new(response_key, AES.MODE_CBC, JAPANESE_AES_IV).encrypt(pkcs7_pad(compressed))
    return bytes([marker]) + ciphertext


def load_descriptor_pool(path: Path) -> descriptor_pool.DescriptorPool:
    descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes())
    pool = descriptor_pool.DescriptorPool()
    remaining = {file.name: file for file in descriptor_set.file}
    while remaining:
        progress = False
        for name, file in list(remaining.items()):
            try:
                pool.Add(file)
            except (descriptor_pool.Error, TypeError):
                continue
            del remaining[name]
            progress = True
        if not progress:
            raise ValueError(f"could not load descriptor dependencies: {', '.join(remaining)}")
    return pool


def parse_message(data: bytes, pool: descriptor_pool.DescriptorPool):
    descriptor = pool.FindMessageTypeByName(TOP_LEVEL_MESSAGE)
    message = message_factory.GetMessageClass(descriptor)()
    message.ParseFromString(data)
    return message


def scalar_text(field, value: Any) -> str:
    if field.type == field.TYPE_BYTES:
        return f"base64:{base64.b64encode(value).decode('ascii')}"
    if field.type == field.TYPE_STRING:
        return json.dumps(value, ensure_ascii=False)
    if field.type == field.TYPE_ENUM:
        return field.enum_type.values_by_number[value].name
    return str(value)


def print_message(message, prefix: str = "", depth: int = 0, max_depth: int = 2) -> None:
    for field, value in message.ListFields():
        path = f"{prefix}.{field.name}" if prefix else field.name
        if field.is_repeated:
            print(f"{path}[{len(value)}]")
            if depth < max_depth and field.message_type:
                for index, child in enumerate(value[:3]):
                    print_message(child, f"{path}[{index}]", depth + 1, max_depth)
        elif field.message_type:
            print(f"{path} <{field.message_type.full_name}> bytes={value.ByteSize()}")
            if depth < max_depth:
                print_message(value, path, depth + 1, max_depth)
        else:
            print(f"{path} = {scalar_text(field, value)}")


def resolve_path(message, path: str):
    current = message
    parts = path.split(".")
    for part in parts[:-1]:
        match = re.fullmatch(r"([A-Za-z_]\w*)(?:\[(\d+)\])?", part)
        if not match:
            raise ValueError(f"invalid field path component: {part}")
        name, index = match.groups()
        field = current.DESCRIPTOR.fields_by_name.get(name)
        if field is None or not field.message_type:
            raise ValueError(f"{name} is not a message field")
        value = getattr(current, name)
        if index is None:
            current = value
        else:
            if not field.is_repeated or int(index) >= len(value):
                raise ValueError(f"invalid index for {name}")
            current = value[int(index)]
    final = parts[-1]
    match = re.fullmatch(r"([A-Za-z_]\w*)(?:\[(\d+)\])?", final)
    if not match:
        raise ValueError(f"invalid final field path: {final}")
    name, index = match.groups()
    field = current.DESCRIPTOR.fields_by_name.get(name)
    if field is None:
        raise ValueError(f"unknown field: {name}")
    return current, field, None if index is None else int(index)


def parse_scalar(field, text: str):
    if field.type == field.TYPE_STRING:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = text
        if not isinstance(value, str):
            raise ValueError(f"{field.name} requires a string")
        return value
    if field.type == field.TYPE_BYTES:
        if text.startswith("base64:"):
            return base64.b64decode(text[7:])
        return bytes.fromhex(text)
    if field.type == field.TYPE_BOOL:
        if text.lower() not in ("true", "false"):
            raise ValueError(f"{field.name} requires true or false")
        return text.lower() == "true"
    if field.type in (field.TYPE_FLOAT, field.TYPE_DOUBLE):
        return float(text)
    if field.type == field.TYPE_ENUM:
        if text in field.enum_type.values_by_name:
            return field.enum_type.values_by_name[text].number
        return int(text, 0)
    return int(text, 0)


def apply_set(message, assignment: str) -> None:
    if "=" not in assignment:
        raise ValueError(f"assignment requires path=value: {assignment}")
    path, text = assignment.split("=", 1)
    target, field, index = resolve_path(message, path)
    if field.message_type:
        raise ValueError(f"target field is a message; edit one of its fields: {path}")
    value = parse_scalar(field, text)
    if field.is_repeated:
        values = getattr(target, field.name)
        if index is None:
            raise ValueError(f"repeated field requires an index: {path}[0]")
        if index >= len(values):
            raise ValueError(f"index out of range: {path}")
        values[index] = value
    else:
        setattr(target, field.name, value)


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--key", help="AES key as hexadecimal")
    parser.add_argument("--iv", help="AES IV as hexadecimal")
    parser.add_argument("--key-file", type=Path, help="aes-material.json captured with the profile session")
    parser.add_argument(
        "--descriptors",
        type=Path,
        default=Path(__file__).with_name("profile-descriptors.pb"),
        help="FileDescriptorSet generated from the Japanese client",
    )


def add_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--player-name",
        help="replace resources.profile.name with this display name",
    )
    parser.add_argument(
        "--player-id",
        type=parse_player_id,
        help="replace the offline auth user ID and write a replay override sidecar",
    )
    parser.add_argument(
        "--anonymization-file",
        type=Path,
        help="sidecar path for --player-id; defaults beside the input profile",
    )


def backup_profile(profile: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    backup = backup_dir / f"{profile.stem}-{stamp}{profile.suffix}"
    suffix = 1
    while backup.exists():
        backup = backup_dir / f"{profile.stem}-{stamp}-{suffix}{profile.suffix}"
        suffix += 1
    shutil.copy2(profile, backup)
    return backup


def upsert_quest_state(message, quest_id: int, clear_count: int) -> bool:
    states = message.resources.quest_states
    for state in states:
        if state.quest_id == quest_id:
            if state.clear_count < clear_count:
                state.clear_count = clear_count
            return False

    state = states.add()
    state.quest_id = quest_id
    state.clear_count = clear_count
    return True


def upsert_revived_event(message, event_id: int) -> bool:
    events = message.resources.revived_events
    for event in events:
        if event.event_id == event_id:
            return False

    event = events.add()
    event.event_id = event_id
    return True


def apply_state_file(message, path: Path) -> tuple[int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    added_quests = 0
    added_events = 0
    for quest_id, clear_count in (data.get("quest_states") or {}).items():
        added_quests += upsert_quest_state(message, int(quest_id), int(clear_count))
    for event_id in data.get("revived_events") or []:
        added_events += upsert_revived_event(message, int(event_id))
    return added_quests, added_events


def current_timestamp() -> tuple[int, int]:
    now = datetime.datetime.now(datetime.timezone.utc)
    return int(now.timestamp()), now.microsecond * 1000


def set_timestamp(target, timestamp: tuple[int, int]) -> None:
    target.seconds, target.nanos = timestamp


def apply_player_name(message, player_name: str | None) -> None:
    if player_name is None:
        return
    if not player_name.strip():
        raise ValueError("player name cannot be empty")
    message.resources.profile.name = player_name


def write_player_id_override(path: Path, player_id: str) -> None:
    numeric_id = int(player_id.replace("'", ""), 10)
    path.write_text(
        json.dumps(
            {
                "player_id": numeric_id,
                "player_id_text": player_id,
                "session_token": DEFAULT_ANONYMIZED_SESSION_TOKEN,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def load_master_records(master_root: Path, name: str) -> list[dict[str, Any]]:
    path = master_root / f"{name}.json"
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"could not read master-data file: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"master-data file is not valid JSON: {path}") from error
    if not isinstance(records, list):
        raise ValueError(f"master-data file must contain an array: {path}")
    return records


def index_master_records(records: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(record["id"]): record for record in records}


def maximum_level_exp(level_records: list[dict[str, Any]], maximum_level: int) -> int:
    by_id = index_master_records(level_records)
    next_level = by_id.get(maximum_level + 1)
    if next_level is not None:
        return max(0, int(next_level["exp"]) - 1)
    level = by_id.get(maximum_level)
    if level is None:
        raise ValueError(f"master data has no level {maximum_level}")
    return int(level["exp"])


def board_progress(
    board_id: int | None,
    boards: dict[int, dict[str, Any]],
    pages: dict[int, dict[str, Any]],
    page_limit: int | None = None,
) -> tuple[int, int]:
    if board_id is None:
        return 0, 0
    board = boards.get(int(board_id))
    if board is None:
        return 0, 0
    page_ids = board.get("page_ids") or []
    if page_limit is None:
        page_limit = len(page_ids)
    page_limit = max(0, min(int(page_limit), len(page_ids)))
    if page_limit == 0:
        return 0, 0
    last_page = pages.get(int(page_ids[page_limit - 1]))
    panel_count = len(last_page.get("panel_ids") or []) if last_page else 0
    panel_bits = (1 << panel_count) - 1 if panel_count else 0
    return page_limit, panel_bits


def board_values(
    board_id: int | None,
    boards: dict[int, dict[str, Any]],
    pages: dict[int, dict[str, Any]],
    panels: dict[int, dict[str, Any]],
    page_limit: int | None = None,
) -> dict[str, int]:
    values = {
        "growboard_hp": 0,
        "growboard_speed": 0,
        "growboard_attack": 0,
        "growboard_magic": 0,
        "growboard_defense": 0,
        "growboard_mental": 0,
        "growboard_all_status_rate": 0,
        "growboard_trait_rank_weight_bonus": 0,
    }
    if board_id is None or int(board_id) not in boards:
        return values

    page_ids = boards[int(board_id)].get("page_ids") or []
    if page_limit is not None:
        page_ids = page_ids[: max(0, min(int(page_limit), len(page_ids)))]
    status_fields = {
        1: "growboard_hp",
        2: "growboard_speed",
        3: "growboard_attack",
        4: "growboard_magic",
        5: "growboard_defense",
        6: "growboard_mental",
    }
    for page_id in page_ids:
        page = pages.get(int(page_id))
        if page is None:
            continue
        for panel_id in page.get("panel_ids") or []:
            panel = panels.get(int(panel_id))
            if panel is None:
                continue
            value = int(panel.get("value") or 0)
            panel_type = int(panel.get("type") or 0)
            if panel_type == 1:
                field_name = status_fields.get(panel.get("status_type"))
                if field_name is not None:
                    values[field_name] += value
            elif panel_type == 3:
                values["growboard_all_status_rate"] += value
            elif panel_type == 6:
                values["growboard_trait_rank_weight_bonus"] += value
    return values


def maximize_character(
    character,
    master: dict[str, Any],
    max_exp: int,
    max_level_limit_increase: int,
    common_rarities: dict[int, dict[str, Any]],
    boards: dict[int, dict[str, Any]],
    pages: dict[int, dict[str, Any]],
    panels: dict[int, dict[str, Any]],
) -> bool:
    before = character.SerializeToString()
    maximum_rarity = int(master.get("max_rarity") or master.get("initial_rarity") or 1)
    rarity_data = common_rarities.get(maximum_rarity, {})
    neo_max_page = (
        int(rarity_data.get("growboard_neo_max_page") or 0)
        if master.get("neo_growboard_id") is not None
        else 0
    )

    normal_page, normal_bits = board_progress(master.get("growboard_id"), boards, pages)
    ex_page, ex_bits = board_progress(master.get("ex_growboard_id"), boards, pages)
    neo_page, neo_bits = board_progress(
        master.get("neo_growboard_id"),
        boards,
        pages,
        neo_max_page,
    )
    normal_values = board_values(master.get("growboard_id"), boards, pages, panels)
    ex_values = board_values(master.get("ex_growboard_id"), boards, pages, panels)
    neo_values = board_values(
        master.get("neo_growboard_id"),
        boards,
        pages,
        panels,
        neo_page,
    )

    character.rarity = max(character.rarity, maximum_rarity)
    character.exp = max(character.exp, max_exp)
    character.normal1_skill_rank = max(
        character.normal1_skill_rank,
        len(master.get("normal1_skill_ids") or []),
    )
    character.normal2_skill_rank = max(
        character.normal2_skill_rank,
        len(master.get("normal2_skill_ids") or []),
    )
    character.growboard_current_page = normal_page
    character.growboard_panel_bits = normal_bits
    character.growboard_ex_current_page = ex_page
    character.growboard_ex_panel_bits = ex_bits
    character.growboard_neo_current_page = neo_page
    character.growboard_neo_panel_bits = neo_bits
    character.growboard_neo_max_page = neo_max_page

    for field_name in (
        "growboard_hp",
        "growboard_speed",
        "growboard_attack",
        "growboard_magic",
        "growboard_defense",
        "growboard_mental",
        "growboard_all_status_rate",
        "growboard_trait_rank_weight_bonus",
    ):
        value = normal_values[field_name] + ex_values[field_name] + neo_values[field_name]
        setattr(character, field_name, max(getattr(character, field_name), value))

    character.growboard_level_limit = max(character.growboard_level_limit, 90)
    character.level_limit_increase_value = max(
        character.level_limit_increase_value,
        max_level_limit_increase,
    )
    for field_name, master_name in (
        ("board_ability1_rank", "board_ability1_ids"),
        ("board_ability2_rank", "board_ability2_ids"),
        ("board_ability3_rank", "board_ability3_ids"),
    ):
        setattr(
            character,
            field_name,
            max(getattr(character, field_name), len(master.get(master_name) or [])),
        )
    return character.SerializeToString() != before


def maximize_memoria(memoria, master: dict[str, Any], max_exp: int, rarities: dict[int, dict[str, Any]]) -> bool:
    before = memoria.SerializeToString()
    rarity = int(master.get("rarity") or 1)
    maximum_limit_break = int(rarities.get(rarity, {}).get("max_limit_break") or 0)
    memoria.exp = max(memoria.exp, max_exp)
    memoria.limit_break = max(memoria.limit_break, maximum_limit_break)
    return memoria.SerializeToString() != before


def apply_task_count_requirements(message, requirements: dict[int, int]) -> int:
    existing_task_counts: dict[int, list[Any]] = {}
    for task_count in message.resources.total_task_counts:
        existing_task_counts.setdefault(task_count.condition_id, []).append(task_count)

    updated_task_counts = 0
    for condition_id, required_count in requirements.items():
        states = existing_task_counts.get(condition_id)
        if states:
            for state in states:
                if state.count < required_count:
                    state.count = required_count
                    updated_task_counts += 1
            continue

        task_count = message.resources.total_task_counts.add()
        task_count.condition_id = condition_id
        task_count.count = required_count
        updated_task_counts += 1
    return updated_task_counts


def apply_communication_states(
    message,
    communication_records: list[dict[str, Any]],
) -> tuple[int, int, int]:
    by_character: dict[int, list[dict[str, Any]]] = {}
    task_requirements: dict[int, int] = {}
    for record in communication_records:
        character_id = int(record["character_id"])
        by_character.setdefault(character_id, []).append(record)
        for task in record.get("key_tasks") or []:
            condition_id = int(task["condition_id"])
            task_requirements[condition_id] = max(
                task_requirements.get(condition_id, 0),
                int(task.get("count") or 1),
            )

    existing_states = {
        state.character_id: state for state in message.resources.communication_states
    }
    added_states = 0
    updated_states = 0
    for character_id, records in by_character.items():
        state = existing_states.get(character_id)
        if state is None:
            state = message.resources.communication_states.add()
            state.character_id = character_id
            existing_states[character_id] = state
            added_states += 1
            before = None
        else:
            before = state.SerializeToString()

        released = set(state.released_story_numbers)
        cleared = set(state.cleared_story_numbers)
        reward_scene_id: int | None = None
        for record in sorted(records, key=lambda value: int(value["story_number"])):
            story_number = int(record["story_number"])
            released.add(story_number)
            cleared.add(story_number)
            if record.get("reward_scene_id") is not None:
                reward_scene_id = int(record["reward_scene_id"])
        del state.released_story_numbers[:]
        state.released_story_numbers.extend(sorted(released))
        del state.cleared_story_numbers[:]
        state.cleared_story_numbers.extend(sorted(cleared))
        if reward_scene_id is not None:
            state.reward_scene_id.value = reward_scene_id

        if before is not None and state.SerializeToString() != before:
            updated_states += 1

    updated_task_counts = apply_task_count_requirements(message, task_requirements)
    return added_states, updated_states, updated_task_counts


def apply_character_story_states(
    message,
    story_records: list[dict[str, Any]],
) -> tuple[int, int, int]:
    branch_conditions: dict[int, set[int]] = {}
    task_requirements: dict[int, int] = {}
    for record in story_records:
        for key_story in record.get("key_stories") or []:
            condition = key_story.get("condition")
            if condition is not None:
                branch_conditions.setdefault(int(key_story["id"]), set()).add(int(condition))
        for task in record.get("key_tasks") or []:
            condition_id = int(task["condition_id"])
            task_requirements[condition_id] = max(
                task_requirements.get(condition_id, 0),
                int(task.get("count") or 1),
            )

    existing_states = {
        state.character_story_id: state for state in message.resources.character_story_states
    }
    added_states = 0
    updated_states = 0
    for record in story_records:
        story_id = int(record["id"])
        state = existing_states.get(story_id)
        if state is None:
            state = message.resources.character_story_states.add()
            state.character_story_id = story_id
            existing_states[story_id] = state
            added_states += 1
            before = None
        else:
            before = state.SerializeToString()

        expected_conditions = {CHARACTER_STORY_BASE_CONDITION}
        if record.get("subsequent_branch"):
            expected_conditions.update(branch_conditions.get(story_id, set()))
        expected_clear_count = max(1, len(expected_conditions))
        state.clear_count = max(state.clear_count, expected_clear_count)
        condition_states = set(state.condition_states)
        condition_states.update(expected_conditions)
        del state.condition_states[:]
        state.condition_states.extend(sorted(condition_states))

        if before is not None and state.SerializeToString() != before:
            updated_states += 1

    updated_task_counts = apply_task_count_requirements(message, task_requirements)
    return added_states, updated_states, updated_task_counts


def apply_complete_collection(
    message,
    master_root: Path,
    include_non_receivable_backgrounds: bool = False,
) -> tuple[int, ...]:
    characters = load_master_records(master_root, "character")
    character_levels = load_master_records(master_root, "character_level")
    character_level_limit_releases = load_master_records(master_root, "character_level_limit_release")
    character_common_rarities = load_master_records(master_root, "character_common_rarity")
    growboards = load_master_records(master_root, "growboard")
    growboard_pages = load_master_records(master_root, "growboard_page")
    growboard_panels = load_master_records(master_root, "growboard_panel")
    memorias = load_master_records(master_root, "memoria")
    memoria_levels = load_master_records(master_root, "memoria_level")
    memoria_rarities = load_master_records(master_root, "memoria_rarity")
    communication_records = load_master_records(master_root, "communication")
    character_story_records = load_master_records(master_root, "character_story")
    recipes = load_master_records(master_root, "recipe")
    character_skins = load_master_records(master_root, "character_skin")
    homes = load_master_records(master_root, "home")
    photo_backgrounds = load_master_records(master_root, "photo_background")
    chara_home_motions = load_master_records(master_root, "chara_home_motion")
    chara_home_bgms = load_master_records(master_root, "chara_home_bgm")
    photo_frames = load_master_records(master_root, "photo_frame")
    chara_home_cameras = load_master_records(master_root, "chara_home_camera")
    mod_timelines = load_master_records(master_root, "mod_timeline")
    received_at = current_timestamp()
    max_character_exp = maximum_level_exp(character_levels, MAX_CHARACTER_LEVEL)
    max_memoria_exp = max(int(record["exp"]) for record in memoria_levels)
    max_level_limit_increase = sum(
        int(record.get("value") or 0) for record in character_level_limit_releases
    )
    character_common_rarity_by_id = index_master_records(character_common_rarities)
    growboards_by_id = index_master_records(growboards)
    growboard_pages_by_id = index_master_records(growboard_pages)
    growboard_panels_by_id = index_master_records(growboard_panels)
    memoria_rarities_by_id = index_master_records(memoria_rarities)

    existing_characters = {
        character.character_id: character for character in message.resources.characters
    }
    added_characters = 0
    updated_characters = 0
    for master in characters:
        character_id = int(master["id"])
        character = existing_characters.get(character_id)
        is_new = character is None
        if character is None:
            character = message.resources.characters.add()
            character.character_id = character_id
            set_timestamp(character.received_at, received_at)
            existing_characters[character_id] = character
            added_characters += 1
        if maximize_character(
            character,
            master,
            max_character_exp,
            max_level_limit_increase,
            character_common_rarity_by_id,
            growboards_by_id,
            growboard_pages_by_id,
            growboard_panels_by_id,
        ):
            if not is_new:
                updated_characters += 1

    owned_memoria_ids = {memoria.memoria_id for memoria in message.resources.memorias}
    used_memoria_entity_ids = {memoria.entity_id for memoria in message.resources.memorias}
    next_memoria_entity_id = max(used_memoria_entity_ids or {0}) + 1
    added_memorias = 0
    updated_memorias = 0
    memoria_by_id = index_master_records(memorias)
    for memoria in message.resources.memorias:
        master = memoria_by_id.get(memoria.memoria_id)
        if master is not None and maximize_memoria(memoria, master, max_memoria_exp, memoria_rarities_by_id):
            updated_memorias += 1

    for master in memorias:
        memoria_id = int(master["id"])
        if memoria_id in owned_memoria_ids:
            continue

        while next_memoria_entity_id in used_memoria_entity_ids:
            next_memoria_entity_id += 1
        memoria = message.resources.memorias.add()
        memoria.entity_id = next_memoria_entity_id
        memoria.memoria_id = memoria_id
        set_timestamp(memoria.received_at, received_at)
        owned_memoria_ids.add(memoria_id)
        used_memoria_entity_ids.add(next_memoria_entity_id)
        next_memoria_entity_id += 1
        maximize_memoria(memoria, master, max_memoria_exp, memoria_rarities_by_id)
        added_memorias += 1

    for recipe in message.resources.recipes:
        if not recipe.HasField("received_at"):
            set_timestamp(recipe.received_at, received_at)

    owned_recipe_ids = {recipe.recipe_id for recipe in message.resources.recipes}
    added_recipes = 0
    for master in recipes:
        recipe_id = int(master["id"])
        if recipe_id in owned_recipe_ids:
            continue

        recipe = message.resources.recipes.add()
        recipe.recipe_id = recipe_id
        set_timestamp(recipe.received_at, received_at)
        owned_recipe_ids.add(recipe_id)
        added_recipes += 1

    owned_character_skin_ids = {skin.character_skin_id for skin in message.resources.character_skins}
    added_character_skins = 0
    for master in character_skins:
        character_skin_id = int(master["id"])
        if character_skin_id in owned_character_skin_ids:
            continue

        character_skin = message.resources.character_skins.add()
        character_skin.character_skin_id = character_skin_id
        set_timestamp(character_skin.received_at, received_at)
        owned_character_skin_ids.add(character_skin_id)
        added_character_skins += 1

    owned_background_ids = {background.background_id for background in message.resources.chara_home_backgrounds}
    added_photo_backgrounds = 0
    for master in photo_backgrounds:
        if not include_non_receivable_backgrounds and not master.get("is_receivable"):
            continue
        background_id = int(master["id"])
        if background_id in owned_background_ids:
            continue

        background = message.resources.chara_home_backgrounds.add()
        background.background_id = background_id
        set_timestamp(background.received_at, received_at)
        owned_background_ids.add(background_id)
        added_photo_backgrounds += 1

    owned_motion_ids = {motion.motion_id for motion in message.resources.chara_home_motions}
    added_chara_home_motions = 0
    for master in chara_home_motions:
        if not master.get("is_receivable"):
            continue
        motion_id = int(master["id"])
        if motion_id in owned_motion_ids:
            continue

        motion = message.resources.chara_home_motions.add()
        motion.motion_id = motion_id
        set_timestamp(motion.received_at, received_at)
        owned_motion_ids.add(motion_id)
        added_chara_home_motions += 1

    owned_mod_timeline_ids = {
        state.mod_timeline_id for state in message.resources.mod_timeline_states
    }
    added_mod_timeline_states = 0
    for master in mod_timelines:
        mod_timeline_id = int(master["id"])
        if mod_timeline_id in owned_mod_timeline_ids:
            continue

        state = message.resources.mod_timeline_states.add()
        state.mod_timeline_id = mod_timeline_id
        set_timestamp(state.received_at, received_at)
        owned_mod_timeline_ids.add(mod_timeline_id)
        added_mod_timeline_states += 1

    owned_home_ids = {home.home_id for home in message.resources.homes}
    added_homes = 0
    for master in homes:
        home_id = int(master["id"])
        if home_id in owned_home_ids:
            continue

        home = message.resources.homes.add()
        home.home_id = home_id
        set_timestamp(home.received_at, received_at)
        owned_home_ids.add(home_id)
        added_homes += 1

    (
        added_communication_states,
        updated_communication_states,
        updated_communication_task_counts,
    ) = apply_communication_states(message, communication_records)
    (
        added_character_story_states,
        updated_character_story_states,
        updated_character_story_task_counts,
    ) = apply_character_story_states(message, character_story_records)

    asset_key_quest_ids = {
        int(master["key_quest_id"])
        for records in (photo_backgrounds, chara_home_bgms, photo_frames, chara_home_cameras, mod_timelines)
        for master in records
        if master.get("key_quest_id") is not None
    }
    updated_asset_key_quests = 0
    for quest_id in asset_key_quest_ids:
        state = next(
            (state for state in message.resources.quest_states if state.quest_id == quest_id),
            None,
        )
        if state is None:
            state = message.resources.quest_states.add()
            state.quest_id = quest_id
            state.clear_count = 1
            updated_asset_key_quests += 1
        elif state.clear_count < 1:
            state.clear_count = 1
            updated_asset_key_quests += 1

    camera_task_requirements: dict[int, int] = {}
    for records in (photo_frames, photo_backgrounds, chara_home_motions, chara_home_cameras):
        for master in records:
            for task in master.get("key_tasks") or []:
                condition_id = int(task["condition_id"])
                required_count = int(task.get("count") or 1)
                camera_task_requirements[condition_id] = max(
                    camera_task_requirements.get(condition_id, 0),
                    required_count,
                )

    updated_camera_task_counts = apply_task_count_requirements(message, camera_task_requirements)

    return (
        added_characters,
        updated_characters,
        added_memorias,
        updated_memorias,
        added_communication_states,
        updated_communication_states,
        updated_communication_task_counts,
        added_character_story_states,
        updated_character_story_states,
        updated_character_story_task_counts,
        added_recipes,
        added_character_skins,
        added_photo_backgrounds,
        added_chara_home_motions,
        added_mod_timeline_states,
        added_homes,
        updated_asset_key_quests,
        updated_camera_task_counts,
    )


def default_master_root() -> Path:
    packaged_root = Path(__file__).with_name("master")
    if packaged_root.is_dir():
        return packaged_root
    return Path(__file__).resolve().parents[2] / "resleriana-db-main" / "data" / "master" / "jp"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("profile", type=Path, nargs="?", help="defaults to the game-root profile.bin")
    add_common_arguments(inspect_parser)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("profile", type=Path, nargs="?", help="defaults to the game-root profile.bin")
    export_parser.add_argument("json_output", type=Path, nargs="?", help="defaults beside the selected profile")
    add_common_arguments(export_parser)

    edit_parser = subparsers.add_parser("edit")
    edit_parser.add_argument("profile", type=Path, nargs="?", help="defaults to the game-root profile.bin")
    edit_parser.add_argument("output", type=Path, nargs="?")
    edit_parser.add_argument(
        "--in-place",
        action="store_true",
        help="replace the source profile after creating a timestamped backup",
    )
    edit_parser.add_argument(
        "--backup-dir",
        type=Path,
        help="backup directory for --in-place; defaults to profile-backups beside the profile",
    )
    edit_parser.add_argument(
        "--state-file",
        type=Path,
        help="JSON manifest containing quest_states and revived_events to upsert",
    )
    edit_parser.add_argument("--set", action="append", default=[], metavar="PATH=VALUE")
    add_common_arguments(edit_parser)
    add_identity_arguments(edit_parser)

    complete_parser = subparsers.add_parser(
        "complete-collection",
        help="unlock and maximize the collection, Bond chapters, Character Stories, and historical events",
    )
    complete_parser.add_argument("profile", type=Path, nargs="?", help="defaults to the game-root profile.bin")
    complete_parser.add_argument("output", type=Path, nargs="?")
    complete_parser.add_argument(
        "--in-place",
        action="store_true",
        help="replace the source profile after creating a timestamped backup",
    )
    complete_parser.add_argument(
        "--backup-dir",
        type=Path,
        help="backup directory for --in-place; defaults to profile-backups beside the profile",
    )
    complete_parser.add_argument(
        "--master-root",
        type=Path,
        default=default_master_root(),
        help="Japanese master-data directory used for collection, progression, Bond, and story records",
    )
    complete_parser.add_argument(
        "--include-non-receivable-backgrounds",
        action="store_true",
        help="also serialize non-receivable photo backgrounds for an experimental profile",
    )
    complete_parser.add_argument(
        "--state-file",
        type=Path,
        default=Path(__file__).with_name("historical-event-state.json"),
        help="historical event quest-state manifest to apply; defaults to the checked-in manifest",
    )
    add_common_arguments(complete_parser)
    add_identity_arguments(complete_parser)

    normalize_parser = subparsers.add_parser(
        "normalize",
        help="re-encrypt a profile into the share-compatible format without changing its data",
    )
    normalize_parser.add_argument("profile", type=Path, nargs="?", help="defaults to the game-root profile.bin")
    normalize_parser.add_argument("output", type=Path, nargs="?")
    normalize_parser.add_argument(
        "--in-place",
        action="store_true",
        help="replace the source profile after creating a timestamped backup",
    )
    normalize_parser.add_argument(
        "--backup-dir",
        type=Path,
        help="backup directory for --in-place; defaults to profile-backups beside the profile",
    )
    add_common_arguments(normalize_parser)

    args = parser.parse_args()
    args.profile = args.profile or default_profile_path()
    if args.command == "export" and args.json_output is None:
        args.json_output = args.profile.with_name(f"{args.profile.stem}.json")
    if bool(args.key) != bool(args.iv):
        raise ValueError("--key and --iv must be supplied together")
    if args.key:
        keys = [parse_hex(args.key, "key")]
        ivs = [parse_hex(args.iv, "iv")]
    elif args.key_file:
        keys, ivs = load_material(args.key_file)
    else:
        observer_material = default_observer_material_path(args.profile)
        if observer_material is not None:
            keys, ivs = load_material(observer_material)
        else:
            keys = [SHARE_PROFILE_KEY, DEFAULT_KEY]
            ivs = [SHARE_PROFILE_IV, DEFAULT_IV]

    protobuf_data, marker, key, iv = decrypt_with_candidates(args.profile.read_bytes(), keys, ivs)
    pool = load_descriptor_pool(args.descriptors)
    message = parse_message(protobuf_data, pool)

    if args.command == "inspect":
        print(f"profile={args.profile}")
        print(f"protobuf_bytes={len(protobuf_data)} marker=0x{marker:02x}")
        print_message(message)
    elif args.command == "export":
        args.json_output.write_text(
            json_format.MessageToJson(message, preserving_proto_field_name=True, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"wrote {args.json_output}")
    elif args.command in ("edit", "complete-collection", "normalize"):
        if args.in_place and args.output is not None:
            raise ValueError("--in-place cannot be combined with an output path")
        if not args.in_place and args.output is None:
            raise ValueError(f"{args.command} requires an output path or --in-place")
        if args.command == "edit":
            if not args.set and args.state_file is None and args.player_name is None and args.player_id is None:
                raise ValueError("edit requires --set, --state-file, --player-name, or --player-id")
            if args.state_file is not None:
                added_quests, added_events = apply_state_file(message, args.state_file)
                print(f"applied state manifest: new_quest_states={added_quests} new_revived_events={added_events}")
            for assignment in args.set:
                apply_set(message, assignment)
        elif args.command == "complete-collection":
            added_quests, added_events = apply_state_file(message, args.state_file)
            (
                added_characters,
                updated_characters,
                added_memorias,
                updated_memorias,
                added_communication_states,
                updated_communication_states,
                updated_communication_task_counts,
                added_character_story_states,
                updated_character_story_states,
                updated_character_story_task_counts,
                added_recipes,
                added_character_skins,
                added_photo_backgrounds,
                added_chara_home_motions,
                added_mod_timeline_states,
                added_homes,
                updated_asset_key_quests,
                updated_camera_task_counts,
            ) = apply_complete_collection(
                message,
                args.master_root,
                args.include_non_receivable_backgrounds,
            )
            print(
                "applied complete collection and historical event state: "
                f"new_characters={added_characters} "
                f"updated_characters={updated_characters} "
                f"new_memorias={added_memorias} "
                f"updated_memorias={updated_memorias} "
                f"new_communication_states={added_communication_states} "
                f"updated_communication_states={updated_communication_states} "
                f"updated_communication_task_counts={updated_communication_task_counts} "
                f"new_character_story_states={added_character_story_states} "
                f"updated_character_story_states={updated_character_story_states} "
                f"updated_character_story_task_counts={updated_character_story_task_counts} "
                f"new_recipes={added_recipes} "
                f"new_character_skins={added_character_skins} "
                f"new_photo_backgrounds={added_photo_backgrounds} "
                f"new_chara_home_motions={added_chara_home_motions} "
                f"new_mod_timeline_states={added_mod_timeline_states} "
                f"new_homes={added_homes} "
                f"updated_asset_key_quests={updated_asset_key_quests} "
                f"updated_camera_task_counts={updated_camera_task_counts} "
                f"new_quest_states={added_quests} "
                f"new_revived_events={added_events}"
            )
        if args.command != "normalize":
            apply_player_name(message, args.player_name)
        encrypted = encrypt_profile(
            message.SerializeToString(),
            key,
            iv,
            marker,
        )
        output = args.profile if args.in_place else args.output
        if output is None:
            raise ValueError("missing profile output")
        if not args.in_place and output.resolve() == args.profile.resolve():
            raise ValueError("output must be different from input")
        if args.in_place:
            backup_dir = args.backup_dir or args.profile.parent / "profile-backups"
            backup = backup_profile(args.profile, backup_dir)
            temporary = args.profile.with_name(args.profile.name + ".tmp")
            temporary.write_bytes(encrypted)
            temporary.replace(args.profile)
            print(f"backed up {args.profile} to {backup}")
            print(f"updated {args.profile} bytes={len(encrypted)}")
        else:
            output.write_bytes(encrypted)
            print(f"wrote {output} bytes={len(encrypted)}")
        if getattr(args, "player_id", None) is not None:
            anonymization_file = args.anonymization_file or args.profile.with_name("profile-anonymization.json")
            write_player_id_override(anonymization_file, args.player_id)
            print(f"wrote player ID override {anonymization_file}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
