import hashlib
import gzip
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from mitmproxy import http

try:
    from cryptography.hazmat.primitives.ciphers import Cipher as _CryptographyCipher
    from cryptography.hazmat.primitives.ciphers import algorithms as _CryptographyAlgorithms
    from cryptography.hazmat.primitives.ciphers import modes as _CryptographyModes
except ImportError:
    _CryptographyCipher = None
    _CryptographyAlgorithms = None
    _CryptographyModes = None

try:
    from Crypto.Cipher import AES as _PyCryptoAES
except ImportError:
    _PyCryptoAES = None


BASE_DIR = Path(__file__).resolve().parent
GAME_DIR = Path(os.environ.get("JAPANESE_GAME_DIR", str(BASE_DIR.parent.parent if BASE_DIR.name == "JapaneseOffline" else BASE_DIR)))
PROGRESSION_MASTER_DIR = GAME_DIR / "progression-master"
EXPEDITION_REWARD_PATH = "/expedition/reward_receive"
REPLAY_MODE = os.environ.get("JAPANESE_REPLAY_MODE", "generated").strip().lower() == "replay"
HYBRID_MODE = os.environ.get("JAPANESE_REPLAY_MODE", "generated").strip().lower() == "hybrid"
HYBRID_HANDSHAKE_PATHS = {"/status", "/refund_info/get_country_code", "/auth/sign_in", "/user/log_in"}
HYBRID_INIT_PATHS = {
    "/login_bonus/receive",
    "/external_purchase/receive",
    "/mail/list",
    "/mail/open",
}
HYBRID_PROFILE_KEY = bytes.fromhex("cb0e4a3fbec976b5bcfe02a2ff5243d4")
HYBRID_PROFILE_IV = bytes.fromhex("65a99b89a634fca3193c5212e5219378")
HYBRID_AUTH_KEY = bytes.fromhex("243d4cb0e4a3fbec976b5bcfe02a2ff5")
HYBRID_AUTH_IV = bytes.fromhex("65a99b89a634fca3193c5212e5219378")
HYBRID_RESPONSE_MARKER = 0x7B
HYBRID_PROFILE_MARKER = 0x13
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
DEFAULT_ASSET_VERSION = "1787706536_QVzMLXDQ2KLO9bgR"
DEFAULT_MASTER_DATA_VERSION = "1787730744__RjK13fBy4f67c4c"
LOCAL_ENCRYPTED_MASTER_DATA_NAME = "japanese-masterdata-encrypted.bytes"
LOCAL_EMPTY_VERSION_MASTER_DATA_NAME = "japanese-masterdata-encrypted-empty-version.bytes"
LOCAL_EMPTY_TOKEN_MASTER_DATA_NAME = "japanese-masterdata-encrypted-empty-token.bytes"
DEFAULT_EXPEDITION_SPECIAL_REWARD_IDS = (1074, 1075, 1076, 1077, 1078, 1079, 1080)
REUSABLE_PATHS = {
    "/status",
    "/refund_info/get_country_code",
    "/auth/sign_in",
    "/user/log_in",
    "/login_bonus/receive",
    "/external_purchase/receive",
    EXPEDITION_REWARD_PATH,
}

# Captured successful no-op RecipeLearnResponse: changed_resources is present but empty.
OFFLINE_RECIPE_LEARN_RESPONSE = bytes.fromhex("14fc17f3894a4c3227473e9d04d1f1ac5c")

CURRENT_OBSERVER_WAIT_SECONDS = 10.0


def current_observer_directory() -> Path:
    roots = (GAME_DIR / "japanese-capture",)
    candidates = sorted(
        (
            directory
            for root in roots
            for directory in root.glob("native-observer-*")
            if directory.is_dir()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise ValueError("current offline native observer has not produced aes-material.json")
    return candidates[0]


def current_observer_material() -> tuple[tuple[bytes, ...], tuple[bytes, ...], bytes, bytes]:
    deadline = time.monotonic() + CURRENT_OBSERVER_WAIT_SECONDS
    last_error: Exception | None = None
    while True:
        try:
            material_path = current_observer_directory() / "aes-material.json"
            material = json.loads(material_path.read_text(encoding="utf-8"))
            key_values = material.get("key_candidates") or ([material["key"]] if material.get("key") else [])
            iv_values = material.get("iv_candidates") or ([material["iv"]] if material.get("iv") else [])
            keys = tuple(dict.fromkeys(bytes.fromhex(value) for value in key_values))
            ivs = tuple(dict.fromkeys(bytes.fromhex(value) for value in iv_values))
            if not keys or not ivs:
                raise ValueError(f"observer material has no key/IV candidates: {material_path}")
            primary_key = bytes.fromhex(material.get("key") or key_values[0])
            primary_iv = bytes.fromhex(material.get("iv") or iv_values[0])
            return keys, ivs, primary_key, primary_iv
        except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            last_error = error
            if time.monotonic() >= deadline:
                raise ValueError(f"could not load current offline observer material: {last_error}") from error
            time.sleep(0.1)


@lru_cache(maxsize=None)
def progression_master_index(name: str) -> dict[int, dict[str, object]]:
    path = PROGRESSION_MASTER_DIR / f"{name}.json"
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise ValueError(f"progression master table must be a JSON array: {path}")
    return {int(record["id"]): record for record in values if isinstance(record, dict) and "id" in record}


def observed_aes_sequences() -> tuple[tuple[tuple[bytes, ...], tuple[bytes, ...]], ...]:
    return ((JAPANESE_AES_KEYS, (JAPANESE_AES_IV,)),)


def observed_aes_candidates() -> tuple[tuple[bytes, ...], tuple[bytes, ...]]:
    keys = []
    ivs = []
    for sequence_keys, sequence_ivs in observed_aes_sequences():
        for key in sequence_keys:
            if key not in keys:
                keys.append(key)
        for iv in sequence_ivs:
            if iv not in ivs:
                ivs.append(iv)
    return tuple(keys), tuple(ivs)
SKIN_RESPONSE_MARKER = 0x7B
SKIN_KEY_WAIT_SECONDS = 3.0
SKIN_KEY_RETRY_INTERVAL = 0.1
PROFILE_KEY_WAIT_SECONDS = 3.0
last_response_material: tuple[bytes, bytes, int] | None = None
auth_response_count = 0


def observer_response_material() -> tuple[bytes, bytes, int]:
    return JAPANESE_AES_KEYS[SKIN_RESPONSE_MARKER], JAPANESE_AES_IV, SKIN_RESPONSE_MARKER


def response_material() -> tuple[bytes, bytes, int]:
    return last_response_material or observer_response_material()


def remember_response_material(material: tuple[bytes, bytes, int]) -> tuple[bytes, bytes, int]:
    global last_response_material
    last_response_material = material
    return material
@dataclass
class Record:
    number: int
    url: str
    method: str
    status: int
    request_headers: dict[str, str]
    request_body: bytes
    response_body: bytes

    @property
    def path(self) -> str:
        return urlsplit(self.url).path

    @property
    def body_hash(self) -> str:
        return hashlib.sha256(self.request_body).hexdigest()


def session_directory() -> Path:
    configured = os.environ.get("JAPANESE_CAPTURE_SESSION")
    if configured:
        configured_path = Path(configured)
        if configured_path.is_dir():
            return configured_path

    configured_file = GAME_DIR / "offline-session.txt"
    if configured_file.exists():
        configured_value = configured_file.read_text(encoding="utf-8").strip()
        if configured_value:
            configured_path = Path(configured_value)
            if configured_path.is_absolute() and configured_path.is_dir():
                return configured_path
            if not configured_path.is_absolute():
                for root in capture_roots():
                    candidate = root / configured_value
                    if candidate.is_dir():
                        return candidate

    sessions = sorted(
        (
            session
            for root in capture_roots()
            for session in root.glob("session-*")
            if session.is_dir()
        ),
        key=lambda path: path.stat().st_mtime,
    )
    if not sessions:
        return GAME_DIR / "japanese-capture"
    return sessions[-1]


def capture_roots() -> list[Path]:
    return [GAME_DIR / "japanese-capture"]


def parse_record(metadata_path: Path) -> Record:
    values: dict[str, str] = {}
    headers: dict[str, str] = {}
    in_headers = False
    for line in metadata_path.read_text(encoding="utf-8").splitlines():
        if line == "REQUEST_HEADERS_BEGIN":
            in_headers = True
            continue
        if line == "REQUEST_HEADERS_END":
            in_headers = False
            continue
        if in_headers:
            if ":" in line:
                key, value = line.split(":", 1)
                value = value.strip()
                headers[key.strip().lower()] = "" if value == "(empty)" else value
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value

    number = int(metadata_path.stem)
    request_path = metadata_path.with_name(f"{number:04d}-request.bin")
    response_path = metadata_path.with_name(f"{number:04d}-response.bin")
    return Record(
        number=number,
        url=values["URL"],
        method=values["METHOD"].upper(),
        status=int(values["STATUS"]),
        request_headers=headers,
        request_body=request_path.read_bytes() if request_path.exists() else b"",
        response_body=response_path.read_bytes() if response_path.exists() else b"",
    )


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return value, offset
        shift += 7
        if shift > 63:
            raise ValueError("varint is too long")
    raise ValueError("truncated varint")


def write_varint(value: int) -> bytes:
    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def read_wire_fields(data: bytes) -> list[tuple[int, int, object]]:
    fields = []
    offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset)
        field_number = tag >> 3
        wire_type = tag & 7
        if wire_type == 0:
            value, offset = read_varint(data, offset)
        elif wire_type == 1:
            value = data[offset:offset + 8]
            offset += 8
        elif wire_type == 2:
            length, offset = read_varint(data, offset)
            value = data[offset:offset + length]
            offset += length
        elif wire_type == 5:
            value = data[offset:offset + 4]
            offset += 4
        else:
            raise ValueError(f"unsupported wire type {wire_type}")
        fields.append((field_number, wire_type, value))
    return fields


def write_field(field_number: int, wire_type: int, value: object) -> bytes:
    encoded = write_varint((field_number << 3) | wire_type)
    if wire_type == 0:
        return encoded + write_varint(int(value))
    if wire_type == 2:
        payload = bytes(value)
        return encoded + write_varint(len(payload)) + payload
    return encoded + bytes(value)


def decrypt_api_response(data: bytes) -> tuple[int, bytes, bytes, bytes]:
    if len(data) < 17 or (len(data) - 1) % 16:
        raise ValueError("encrypted API response has an invalid size")
    key = JAPANESE_AES_KEYS[data[0]]
    iv = JAPANESE_AES_IV
    try:
        compressed = pkcs7_unpad(aes_decrypt(data[1:], key, iv))
        plaintext = gzip.decompress(compressed)
        read_wire_fields(plaintext)
        return data[0], plaintext, key, iv
    except (RuntimeError, OSError, EOFError, ValueError) as error:
        raise ValueError("could not decrypt API response") from error


def encrypt_api_response(marker: int, plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    compressed = gzip.compress(plaintext, mtime=0)
    return bytes([marker]) + aes_encrypt(pkcs7_pad(compressed), key, iv)


def default_encrypted_empty_response(gzip_body: bool = True) -> bytes:
    response_key, response_iv, response_marker = response_material()
    if gzip_body:
        return encrypt_api_response(response_marker, b"", response_key, response_iv)
    return bytes([response_marker]) + aes_encrypt(
        pkcs7_pad(b""),
        response_key,
        response_iv,
    )


def default_login_bonus_response() -> bytes:
    response_key, response_iv, response_marker = response_material()
    login_bonus = b"".join(
        (
            write_field(1, 0, 1),
            write_field(2, 0, 581),
            write_field(3, 2, write_field(1, 0, 100003)),
            write_field(4, 0, 5),
        )
    )
    plaintext = b"".join(
        (
            write_field(1, 2, login_bonus),
            write_field(2, 2, b""),
        )
    )
    return encrypt_api_response(
        response_marker,
        plaintext,
        response_key,
        response_iv,
    )


def default_web_session_token_response() -> bytes:
    response_key, response_iv, response_marker = response_material()
    token = str(uuid.uuid4()).encode("ascii")
    return encrypt_api_response(
        response_marker,
        write_field(1, 2, token),
        response_key,
        response_iv,
    )


def default_auth_response(request_body: bytes = b"") -> bytes:
    global auth_response_count
    if request_body:
        try:
            _, response_key, _, response_marker = remember_response_material(
                decrypt_request_with_response_material(
                    request_body,
                    is_api_message,
                    "/auth/sign_in",
                )[1:]
            )
            remember_response_material((response_key, JAPANESE_AES_IV, response_marker))
        except ValueError:
            response_index = (request_body[0] + 1) & 0xFF
            auth_response_count += 1
            response_key, response_iv, response_marker = remember_response_material(
                (JAPANESE_AES_KEYS[response_index], JAPANESE_AES_IV, response_index)
            )
    else:
        response_key, response_iv, response_marker = response_material()
    session_token = "00000000-0000-4000-8000-000000000000"
    player_id = 0
    override_path = GAME_DIR / "profile-anonymization.json"
    try:
        override = json.loads(override_path.read_text(encoding="utf-8"))
        player_id = int(override.get("player_id", player_id))
        session_token = str(override.get("session_token", session_token))
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        pass
    plaintext = b"".join(
        (
            write_field(1, 2, session_token.encode("utf-8")),
            write_field(2, 0, 1),
            write_field(3, 0, player_id),
            write_field(4, 0, 1),
        )
    )
    return encrypt_api_response(
        response_marker,
        plaintext,
        response_key,
        response_iv,
    )


def hybrid_auth_response() -> bytes:
    plaintext = b"".join(
        (
            write_field(1, 2, b"00000000-0000-4000-8000-000000000000"),
            write_field(2, 0, 1),
            write_field(3, 0, 0),
            write_field(4, 0, 1),
        )
    )
    return encrypt_api_response(
        HYBRID_RESPONSE_MARKER,
        plaintext,
        HYBRID_AUTH_KEY,
        HYBRID_AUTH_IV,
    )


def profile_response(
    profile_path: Path,
    target_response: bytes | None = None,
) -> tuple[bytes, bool]:
    profile = b""
    deadline = time.monotonic() + PROFILE_KEY_WAIT_SECONDS
    while True:
        try:
            profile = profile_path.read_bytes()
            profile_plaintext = decrypt_profile_plaintext(profile)
            response_key, response_iv, marker = response_material()
            if target_response:
                try:
                    marker, _, response_key, response_iv = decrypt_api_response(target_response)
                    remember_response_material((response_key, response_iv, marker))
                    return encrypt_api_response(marker, profile_plaintext, response_key, response_iv), True
                except (RuntimeError, OSError, EOFError, ValueError):
                    pass
            return encrypt_api_response(marker, profile_plaintext, response_key, response_iv), True
        except (OSError, RuntimeError, ValueError, StopIteration) as error:
            if HYBRID_MODE and target_response:
                print(f"HYBRID-PROFILE-DECRYPT-FAILED {type(error).__name__}: {error}", file=sys.stderr)
            if time.monotonic() >= deadline:
                return profile, False
            time.sleep(SKIN_KEY_RETRY_INTERVAL)


def default_profile_response(profile_path: Path) -> tuple[bytes, bool]:
    return profile_response(profile_path)


def requested_home_icon_id() -> int | None:
    if os.environ.get("JAPANESE_HOME_ICON_RENDER") != "1":
        return None
    value = os.environ.get("JAPANESE_HOME_ICON_HOME_ID")
    if not value:
        return None
    try:
        home_id = int(value, 10)
    except ValueError:
        return None
    return home_id if home_id > 0 else None


def patch_home_icon_profile(response_body: bytes) -> bytes:
    home_id = requested_home_icon_id()
    if home_id is None:
        return response_body
    marker, plaintext, key, iv = decrypt_api_response(response_body)
    resources = next(
        bytes(value)
        for field_number, wire_type, value in read_wire_fields(plaintext)
        if field_number == 1 and wire_type == 2
    )
    profile = next(
        bytes(value)
        for field_number, wire_type, value in read_wire_fields(resources)
        if field_number == 39 and wire_type == 2
    )
    profile = replace_message_field(profile, 10, write_field(1, 0, home_id))
    profile = replace_message_field(profile, 11, None)
    resources = replace_message_field(resources, 39, profile)
    patched = replace_message_field(plaintext, 1, resources)
    return encrypt_api_response(marker, patched, key, iv)


def replace_varint_field(data: bytes, field_number: int, value: int) -> bytes:
    output = bytearray()
    replaced = False
    for number, wire_type, field_value in read_wire_fields(data):
        if number == field_number and wire_type == 0:
            output.extend(write_field(number, wire_type, value))
            replaced = True
        else:
            output.extend(write_field(number, wire_type, field_value))
    if not replaced:
        output.extend(write_field(field_number, 0, value))
    return bytes(output)


def is_skin_request_plaintext(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False

    character_id_seen = False
    for field_number, wire_type, value in fields:
        if field_number == 1 and wire_type == 0 and not character_id_seen:
            character_id_seen = 0 < int(value) < 1_000_000
            continue
        if field_number == 2 and wire_type == 2:
            try:
                inner_fields = read_wire_fields(bytes(value))
            except ValueError:
                return False
            continue
        # Newer client builds may add optional fields to this request.
        if field_number > 0 and wire_type in (0, 1, 2, 5):
            continue
        return False
    return character_id_seen


def pkcs7_unpad(data: bytes) -> bytes:
    if not data or len(data) % 16:
        raise ValueError("invalid AES block data")
    padding = data[-1]
    if padding < 1 or padding > 16 or data[-padding:] != bytes([padding]) * padding:
        raise ValueError("invalid PKCS#7 padding")
    return data[:-padding]


def pkcs7_pad(data: bytes) -> bytes:
    padding = 16 - (len(data) % 16)
    return data + bytes([padding]) * padding


def aes_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    if _CryptographyCipher is not None:
        decryptor = _CryptographyCipher(
            _CryptographyAlgorithms.AES(key),
            _CryptographyModes.CBC(iv),
        ).decryptor()
        return decryptor.update(data) + decryptor.finalize()
    if _PyCryptoAES is not None:
        return _PyCryptoAES.new(key, _PyCryptoAES.MODE_CBC, iv).decrypt(data)
    raise RuntimeError("no AES implementation is available")


def aes_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    if _CryptographyCipher is not None:
        encryptor = _CryptographyCipher(
            _CryptographyAlgorithms.AES(key),
            _CryptographyModes.CBC(iv),
        ).encryptor()
        return encryptor.update(data) + encryptor.finalize()
    if _PyCryptoAES is not None:
        return _PyCryptoAES.new(key, _PyCryptoAES.MODE_CBC, iv).encrypt(data)
    raise RuntimeError("no AES implementation is available")


def decrypt_request_with_response_material(
    data: bytes,
    validator,
    response_path: str | None = None,
) -> tuple[bytes, bytes, bytes, int]:
    if not data:
        response_key, response_iv, response_marker = response_material()
        return b"", response_key, response_iv, response_marker
    if len(data) < 17 or (len(data) - 1) % 16:
        raise ValueError("encrypted request has an invalid size")
    marker = data[0]
    key = JAPANESE_AES_KEYS[marker]
    iv = JAPANESE_AES_IV
    try:
        plaintext = pkcs7_unpad(aes_decrypt(data[1:], key, iv))
        if not validator(plaintext):
            raise ValueError("request plaintext failed validation")
        response_key = JAPANESE_AES_KEYS[(marker + 1) & 0xFF]
        response_marker = (marker + 1) & 0xFF
        if REPLAY_MODE and response_path is not None:
            captured_material = captured_response_material(response_path, key, iv)
            if captured_material is not None:
                response_key, response_iv, response_marker = captured_material
                return plaintext, response_key, response_iv, response_marker
        return plaintext, response_key, iv, response_marker
    except (RuntimeError, ValueError) as error:
        raise ValueError("could not decrypt request") from error


def decrypt_direct_candidates(data: bytes) -> tuple[bytes, bytes, bytes, int]:
    return decrypt_request_with_response_material(data, is_skin_request_plaintext, "/character/skin_set")


def decrypt_request_plaintext(data: bytes, validator) -> bytes:
    return decrypt_request_with_response_material(data, validator)[0]


def replace_repeated_varint_field(data: bytes, field_number: int, values: list[int]) -> bytes:
    output = bytearray()
    for number, wire_type, field_value in read_wire_fields(data):
        if number != field_number:
            output.extend(write_field(number, wire_type, field_value))
    for value in values:
        output.extend(write_field(field_number, 0, value))
    return bytes(output)


def replace_message_field(data: bytes, field_number: int, value: bytes | None) -> bytes:
    output = bytearray()
    for number, wire_type, field_value in read_wire_fields(data):
        if number != field_number:
            output.extend(write_field(number, wire_type, field_value))
    if value is not None:
        output.extend(write_field(field_number, 2, value))
    return bytes(output)


def replace_repeated_message_field(data: bytes, field_number: int, values: list[bytes]) -> bytes:
    output = bytearray()
    for number, wire_type, field_value in read_wire_fields(data):
        if number != field_number:
            output.extend(write_field(number, wire_type, field_value))
    for value in values:
        output.extend(write_field(field_number, 2, value))
    return bytes(output)


def expedition_special_reward_ids() -> tuple[int, ...]:
    path = GAME_DIR / "expedition-special-rewards.json"
    try:
        values = json.loads(path.read_text(encoding="utf-8")).get("reward_item_ids")
        result = tuple(int(value) for value in values or [])
        if result:
            return result
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return DEFAULT_EXPEDITION_SPECIAL_REWARD_IDS


def make_expedition_special_reward_response(response_body: bytes, reward_item_id: int) -> bytes:
    marker, plaintext, key, iv = decrypt_api_response(response_body)
    special_reward = b"".join(
        (
            write_field(1, 0, 5),
            write_field(2, 0, reward_item_id),
            write_field(3, 0, 1),
        )
    )
    patched = replace_repeated_message_field(plaintext, 3, [special_reward])
    patched = replace_varint_field(patched, 4, 1)
    patched = replace_repeated_message_field(patched, 5, [])
    return encrypt_api_response(marker, patched, key, iv)


def make_changed_resources_response(
    profile: bytes | None = None,
    characters: list[bytes] | None = None,
    items: list[bytes] | None = None,
    character_pieces: list[bytes] | None = None,
    memorias: list[bytes] | None = None,
    status: bytes | None = None,
    wallet: bytes | None = None,
    total_task_counts: list[bytes] | None = None,
    parties: list[bytes] | None = None,
    party_members: list[bytes] | None = None,
    equipment_tools: list[bytes] | None = None,
    equipment_presets: list[bytes] | None = None,
    battle_tools: list[bytes] | None = None,
    ships: list[bytes] | None = None,
    ship_parties: list[bytes] | None = None,
    ship_tools: list[bytes] | None = None,
    chara_homes: list[bytes] | None = None,
    growboard_role_rates: list[bytes] | None = None,
    deleted_resources: bytes | None = None,
    extra_response_fields: list[tuple[int, int, object]] | None = None,
    response_key: bytes | None = None,
    response_iv: bytes | None = None,
    response_marker: int | None = None,
) -> bytes:
    if response_key is None or response_iv is None or response_marker is None:
        response_key, response_iv, response_marker = response_material()
    plaintext = make_changed_resources_plaintext(
        profile=profile,
        characters=characters,
        items=items,
        character_pieces=character_pieces,
        memorias=memorias,
        status=status,
        wallet=wallet,
        total_task_counts=total_task_counts,
        parties=parties,
        party_members=party_members,
        equipment_tools=equipment_tools,
        equipment_presets=equipment_presets,
        battle_tools=battle_tools,
        ships=ships,
        ship_parties=ship_parties,
        ship_tools=ship_tools,
        chara_homes=chara_homes,
        growboard_role_rates=growboard_role_rates,
        deleted_resources=deleted_resources,
        extra_response_fields=extra_response_fields,
    )
    return bytes([response_marker]) + aes_encrypt(
        pkcs7_pad(gzip.compress(plaintext, mtime=0)),
        response_key,
        response_iv,
    )


def make_changed_resources_plaintext(
    profile: bytes | None = None,
    characters: list[bytes] | None = None,
    items: list[bytes] | None = None,
    character_pieces: list[bytes] | None = None,
    memorias: list[bytes] | None = None,
    status: bytes | None = None,
    wallet: bytes | None = None,
    total_task_counts: list[bytes] | None = None,
    parties: list[bytes] | None = None,
    party_members: list[bytes] | None = None,
    equipment_tools: list[bytes] | None = None,
    equipment_presets: list[bytes] | None = None,
    battle_tools: list[bytes] | None = None,
    ships: list[bytes] | None = None,
    ship_parties: list[bytes] | None = None,
    ship_tools: list[bytes] | None = None,
    chara_homes: list[bytes] | None = None,
    growboard_role_rates: list[bytes] | None = None,
    deleted_resources: bytes | None = None,
    extra_response_fields: list[tuple[int, int, object]] | None = None,
) -> bytes:
    resources = bytearray()
    if wallet is not None:
        resources.extend(write_field(1, 2, wallet))
    for character in characters or []:
        resources.extend(write_field(2, 2, character))
    for item in items or []:
        resources.extend(write_field(3, 2, item))
    for character_piece in character_pieces or []:
        resources.extend(write_field(8, 2, character_piece))
    for party in parties or []:
        resources.extend(write_field(9, 2, party))
    for party_member in party_members or []:
        resources.extend(write_field(24, 2, party_member))
    for equipment_tool in equipment_tools or []:
        resources.extend(write_field(4, 2, equipment_tool))
    for growboard_role_rate in growboard_role_rates or []:
        resources.extend(write_field(14, 2, growboard_role_rate))
    for equipment_preset in equipment_presets or []:
        resources.extend(write_field(26, 2, equipment_preset))
    for battle_tool in battle_tools or []:
        resources.extend(write_field(11, 2, battle_tool))
    for memoria in memorias or []:
        resources.extend(write_field(29, 2, memoria))
    if status is not None:
        resources.extend(write_field(6, 2, status))
    for total_task_count in total_task_counts or []:
        resources.extend(write_field(32, 2, total_task_count))
    if profile is not None:
        resources.extend(write_field(39, 2, profile))
    for ship in ships or []:
        resources.extend(write_field(66, 2, ship))
    for ship_party in ship_parties or []:
        resources.extend(write_field(67, 2, ship_party))
    for ship_tool in ship_tools or []:
        resources.extend(write_field(68, 2, ship_tool))
    for chara_home in chara_homes or []:
        resources.extend(write_field(61, 2, chara_home))
    response = bytearray(write_field(1, 2, bytes(resources)))
    if deleted_resources:
        response.extend(write_field(2, 2, deleted_resources))
    for field_number, wire_type, value in extra_response_fields or []:
        response.extend(write_field(field_number, wire_type, value))
    return bytes(response)


PROFILE_REPEATED_KEYS: dict[int, tuple[int, ...]] = {
    2: (1,),       # Character.character_id
    3: (1,),       # Item.item_id
    4: (1,),       # EquipmentTool.entity_id
    8: (1,),       # CharacterPiece.character_id
    9: (5, 1),     # Party.party_type, number
    11: (1,),      # BattleTool.entity_id
    12: (1,),      # Recipe.recipe_id
    14: (1,),      # GrowboardRoleRate.role
    15: (1,),      # GrowthPackState.growth_pack_id
    16: (1,),      # GrowthPackStepState.growth_pack_step_id
    18: (1,),      # ExpeditionState.number
    19: (1,),      # Emblem.emblem_id
    20: (1,),      # ItemChallenge.item_challenge_id
    21: (1,),      # EpisodeState.episode_id
    22: (1,),      # QuestState.quest_id
    24: (1, 2, 3), # PartyMember.party_type, number, position
    25: (1,),      # ExplorationProgress.quest_id
    26: (1,),      # EquipmentPreset.number
    29: (1,),      # Memoria.entity_id
    30: (1,),      # ResearchGroup.group_id
    32: (1,),      # TotalTaskCount.condition_id
    33: (1,),      # Mission.mission_id
    39: (),        # Profile is a singleton message
    40: (1,),      # RevivedEvent.event_id
    46: (1,),      # CommunicationState.character_id
    47: (1,),      # CharacterStoryState.character_story_id
    61: (1,),      # CharaHome.slot_id
    66: (1,),      # Ship.ship_id
    67: (1,),      # ShipParty.number
    68: (1,),      # ShipTool.entity_id
}
PROFILE_NESTED_MERGE_FIELDS = {1, 5, 6, 7, 39, 41}


DELETED_RESOURCE_FIELDS = {
    1: 4,   # ResourceEntities.equipment_tool_entity_ids -> Resources.equipment_tools
    2: 11,  # ResourceEntities.battle_tool_entity_ids -> Resources.battle_tools
    3: 29,  # ResourceEntities.memoria_entity_ids -> Resources.memorias
}


def resource_record_key(record: bytes, key_fields: tuple[int, ...]) -> tuple[int, ...] | None:
    values = {number: int(value) for number, wire, value in read_wire_fields(record) if wire == 0}
    if not key_fields or any(number not in values for number in key_fields):
        return None
    return tuple(values[number] for number in key_fields)


def merge_wire_message(existing: bytes, update: bytes) -> bytes:
    updates: dict[int, list[tuple[int, object]]] = {}
    for number, wire, value in read_wire_fields(update):
        updates.setdefault(number, []).append((wire, value))
    output = bytearray()
    processed: set[int] = set()
    for number, wire, value in read_wire_fields(existing):
        changes = updates.get(number)
        if not changes:
            output.extend(write_field(number, wire, value))
            continue
        if number in processed:
            continue
        for new_wire, new_value in changes:
            output.extend(write_field(number, new_wire, new_value))
        processed.add(number)
    for number, changes in updates.items():
        if number not in processed:
            for wire, value in changes:
                output.extend(write_field(number, wire, value))
    return bytes(output)


def deleted_id_set(deleted_resources: bytes, field_number: int) -> set[int]:
    values: set[int] = set()
    for number, wire, value in read_wire_fields(deleted_resources):
        if number != field_number:
            continue
        if wire == 0:
            values.add(int(value))
        elif wire == 2:
            values.update(read_varints(bytes(value)))
    return values


def remove_deleted_profile_entities(resources: bytes, deleted_resources: bytes) -> bytes:
    deleted_by_resource = {
        resource_field: deleted_id_set(deleted_resources, deleted_field)
        for deleted_field, resource_field in DELETED_RESOURCE_FIELDS.items()
    }
    output = bytearray()
    for number, wire, value in read_wire_fields(resources):
        deleted_ids = deleted_by_resource.get(number)
        if wire == 2 and deleted_ids:
            record_key_fields = PROFILE_REPEATED_KEYS.get(number, (1,))
            record = bytes(value)
            key = resource_record_key(record, record_key_fields)
            if key and key[0] in deleted_ids:
                continue
        output.extend(write_field(number, wire, value))
    return bytes(output)


def merge_profile_resources(existing: bytes, update: bytes) -> bytes:
    """Merge generated ChangedResources fields into persisted profile resources."""
    existing_fields = read_wire_fields(existing)
    updates_by_number: dict[int, list[tuple[int, object]]] = {}
    for number, wire, value in read_wire_fields(update):
        updates_by_number.setdefault(number, []).append((wire, value))

    output = bytearray()
    processed: set[int] = set()
    for number, wire, value in existing_fields:
        updates = updates_by_number.get(number)
        if not updates:
            output.extend(write_field(number, wire, value))
            continue

        key_fields = PROFILE_REPEATED_KEYS.get(number)
        if key_fields and wire == 2:
            indexed_updates: dict[tuple[int, ...], bytes] = {}
            unkeyed_updates: list[bytes] = []
            for update_wire, update_value in updates:
                if update_wire != 2:
                    continue
                update_record = bytes(update_value)
                key = resource_record_key(update_record, key_fields)
                if key is None:
                    unkeyed_updates.append(update_record)
                else:
                    indexed_updates[key] = update_record

            current_record = bytes(value)
            current_key = resource_record_key(current_record, key_fields)
            replacement = indexed_updates.pop(current_key, None) if current_key is not None else None
            output.extend(write_field(number, 2, replacement if replacement is not None else current_record))
            processed.add(number)
            # Append remaining changed entities after existing entries of this field.
            continue

        if number in PROFILE_NESTED_MERGE_FIELDS and wire == 2:
            replacement = next(
                (bytes(update_value) for update_wire, update_value in updates if update_wire == 2),
                bytes(value),
            )
            merged = merge_wire_message(bytes(value), replacement)
            output.extend(write_field(number, 2, merged))
            processed.add(number)
            continue

        if number in processed:
            continue
        # Singular scalar/message fields are replaced with the update value(s).
        for update_wire, update_value in updates:
            output.extend(write_field(number, update_wire, update_value))
        processed.add(number)

    # Append new or unmatched repeated records, preserving the update payload order.
    for number, updates in updates_by_number.items():
        if number in processed and PROFILE_REPEATED_KEYS.get(number):
            existing_keys = {
                resource_record_key(bytes(value), PROFILE_REPEATED_KEYS[number])
                for old_number, old_wire, value in existing_fields
                if old_number == number and old_wire == 2
            }
            emitted_keys = set()
            for update_wire, update_value in updates:
                if update_wire != 2:
                    continue
                record = bytes(update_value)
                key = resource_record_key(record, PROFILE_REPEATED_KEYS[number])
                if key is None or (key not in existing_keys and key not in emitted_keys):
                    output.extend(write_field(number, 2, record))
                if key is not None:
                    emitted_keys.add(key)
            continue
        if number not in processed:
            for update_wire, update_value in updates:
                output.extend(write_field(number, update_wire, update_value))

    return bytes(output)


def merge_profile_resources_response(profile_plaintext: bytes, response_plaintext: bytes) -> bytes | None:
    updated_resources = next(
        (bytes(value) for number, wire, value in read_wire_fields(response_plaintext) if number == 1 and wire == 2),
        None,
    )
    if updated_resources is None:
        return None
    deleted_resources = next(
        (bytes(value) for number, wire, value in read_wire_fields(response_plaintext) if number == 2 and wire == 2),
        b"",
    )
    existing_resources = next(
        (bytes(value) for number, wire, value in read_wire_fields(profile_plaintext) if number == 1 and wire == 2),
        b"",
    )
    merged_resources = merge_profile_resources(existing_resources, updated_resources)
    if deleted_resources:
        merged_resources = remove_deleted_profile_entities(merged_resources, deleted_resources)
    return replace_message_field_in_place(profile_plaintext, 1, merged_resources)


def load_home_profile_state(profile_path: Path) -> tuple[bytes, dict[int, bytes], list[int]]:
    plaintext = decrypt_profile_plaintext(profile_path.read_bytes())
    resources = next(
        bytes(value)
        for field_number, wire_type, value in read_wire_fields(plaintext)
        if field_number == 1 and wire_type == 2
    )
    profile = next(
        (bytes(value) for field_number, wire_type, value in read_wire_fields(resources) if field_number == 39 and wire_type == 2),
        b"",
    )
    chara_homes: dict[int, bytes] = {}
    for field_number, wire_type, value in read_wire_fields(resources):
        if field_number != 61 or wire_type != 2:
            continue
        home = bytes(value)
        slot_id = next(
            int(inner_value)
            for inner_number, inner_type, inner_value in read_wire_fields(home)
            if inner_number == 1 and inner_type == 0
        )
        chara_homes[slot_id] = home
    favorites = [
        int(value)
        for field_number, wire_type, value in read_wire_fields(profile)
        if field_number == 12 and wire_type == 0
    ]
    return profile, chara_homes, favorites


def decrypt_profile_plaintext(data: bytes) -> bytes:
    if len(data) < 17 or (len(data) - 1) % 16:
        raise ValueError("profile has an invalid size")
    marker = data[0]
    if marker >= len(JAPANESE_AES_KEYS):
        raise ValueError("profile has an invalid AES marker")
    try:
        compressed = pkcs7_unpad(aes_decrypt(data[1:], JAPANESE_AES_KEYS[marker], JAPANESE_AES_IV))
        return gzip.decompress(compressed)
    except (RuntimeError, OSError, EOFError, ValueError) as error:
        raise ValueError("could not decrypt profile") from error


def decode_skin_request(data: bytes) -> tuple[int, int | None, bytes, bytes, int]:
    deadline = time.monotonic() + SKIN_KEY_WAIT_SECONDS
    last_error: ValueError | None = None
    while True:
        try:
            plaintext, response_key, response_iv, response_marker = decrypt_direct_candidates(data)
            character_id = None
            skin_id = None
            for field_number, wire_type, value in read_wire_fields(plaintext):
                if field_number == 1 and wire_type == 0:
                    character_id = int(value)
                elif field_number == 2 and wire_type == 2:
                    for inner_number, inner_type, inner_value in read_wire_fields(bytes(value)):
                        if inner_number == 1 and inner_type == 0:
                            skin_id = int(inner_value)
            if character_id is not None:
                return character_id, skin_id, response_key, response_iv, response_marker
            last_error = ValueError("skin request has no character_id")
        except ValueError as error:
            last_error = error

        if time.monotonic() >= deadline:
            raise last_error or ValueError("could not decode skin request")
        time.sleep(SKIN_KEY_RETRY_INTERVAL)


def is_favorite_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    return len(fields) == 1 and fields[0][0] == 1 and fields[0][1] == 0 and 0 < int(fields[0][2]) < 1_000_000


def is_home_register_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    if not fields or any(number not in range(1, 7) or wire_type != 0 for number, wire_type, _ in fields):
        return False
    values = {number for number, _, _ in fields}
    return 1 in values and 2 in values


def is_selected_home_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    for number, wire_type, value in fields:
        if number not in (1, 2) or wire_type != 2:
            return False
        try:
            nested = read_wire_fields(bytes(value))
        except ValueError:
            return False
        if not any(inner_number == 1 and inner_type == 0 for inner_number, inner_type, _ in nested):
            return False
    return bool(fields)


def is_exploration_start_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    if not fields:
        return False
    for number, wire_type, value in fields:
        if number in (1, 2) and wire_type == 0:
            continue
        if number == 7 and wire_type == 2:
            try:
                read_wire_fields(bytes(value))
            except ValueError:
                return False
            continue
        return False
    values = {
        number: int(value)
        for number, wire_type, value in fields
        if wire_type == 0
    }
    return values.get(1, 0) > 0 and values.get(2, 0) > 0


def is_exploration_finish_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    return (
        len(fields) == 1
        and fields[0][0] == 1
        and fields[0][1] == 0
        and 0 < int(fields[0][2])
    )


def is_party_bulk_update_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    if not fields:
        return False
    for number, wire_type, value in fields:
        if number in (1, 2, 5) and wire_type == 0:
            continue
        if number == 3 and wire_type == 2:
            try:
                read_wire_fields(bytes(value))
            except ValueError:
                return False
            continue
        if number == 4 and wire_type in (0, 2):
            if wire_type == 2:
                try:
                    read_varints(bytes(value))
                except ValueError:
                    return False
            continue
        return False
    return any(number == 1 and wire_type == 0 for number, wire_type, _ in fields) and any(
        number == 2 and wire_type == 0 for number, wire_type, _ in fields
    )


def is_party_battle_tools_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    return bool(fields) and all(
        (number in (1, 3) and wire_type == 0) or (number == 2 and wire_type in (0, 2))
        for number, wire_type, _ in fields
    ) and any(number == 1 for number, _, _ in fields) and any(number == 3 for number, _, _ in fields)


def is_character_equip_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    return bool(fields) and all(
        (number in (1, 2) and wire_type == 0) or (number == 3 and wire_type == 2)
        for number, wire_type, _ in fields
    ) and any(number == 1 for number, _, _ in fields) and any(number == 2 for number, _, _ in fields)


def is_character_memoria_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    return bool(fields) and all(
        (number == 1 and wire_type == 0) or (number == 2 and wire_type == 2)
        for number, wire_type, _ in fields
    ) and any(number == 1 for number, _, _ in fields)


def is_equipment_preset_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    return bool(fields) and all(
        (number == 1 and wire_type == 0) or (number in (2, 3, 4, 5) and wire_type == 2)
        for number, wire_type, _ in fields
    ) and any(number == 1 for number, _, _ in fields)


def is_equipment_preset_equip_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    if not fields or any(number not in (1, 2, 3) for number, _, _ in fields):
        return False
    numbers = {number for number, _, _ in fields}
    values = {
        number: int(value)
        for number, wire_type, value in fields
        if wire_type == 0
    }
    if (
        len(values) != sum(1 for number, wire_type, _ in fields if wire_type == 0)
        or values.get(1, 0) <= 0
        or values.get(2, 0) not in (1, 2, 3)
        or any(number not in (1, 2, 3) or wire_type not in ((0,) if number in (1, 2) else (2,)) for number, wire_type, _ in fields)
    ):
        return False
    if 3 in numbers:
        try:
            wrapped = read_wire_fields(message_field(data, 3) or b"")
        except ValueError:
            return False
        if any(number != 1 or wire_type != 0 for number, wire_type, _ in wrapped):
            return False
    return True


def is_equipment_preset_memoria_set_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    if not fields or any(number not in (1, 2) for number, _, _ in fields):
        return False
    if any(number == 1 and wire_type != 0 for number, wire_type, _ in fields):
        return False
    if any(number == 2 and wire_type != 2 for number, wire_type, _ in fields):
        return False
    if varint_field(data, 1, 0) <= 0:
        return False
    if any(number == 2 for number, _, _ in fields):
        wrapped = message_field(data, 2) or b""
        try:
            inner = read_wire_fields(wrapped)
        except ValueError:
            return False
        if any(number != 1 or wire_type != 0 for number, wire_type, _ in inner):
            return False
    return True


def is_equipment_preset_update_name_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    if (
        not fields
        or any(number not in (1, 2) for number, _, _ in fields)
        or not any(number == 1 and wire_type == 0 and int(value) > 0 for number, wire_type, value in fields)
        or not any(number == 2 and wire_type == 2 for number, wire_type, _ in fields)
        or any(
            (number == 1 and wire_type != 0) or (number == 2 and wire_type != 2)
            for number, wire_type, _ in fields
        )
    ):
        return False
    try:
        message_field(data, 2).decode("utf-8")  # type: ignore[union-attr]
    except (AttributeError, UnicodeDecodeError):
        return False
    return True


def is_tool_lock_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    tool_entities = [bytes(value) for number, wire_type, value in fields if number == 1 and wire_type == 2]
    values = {
        number: int(value)
        for number, wire_type, value in fields
        if wire_type == 0
    }
    if (
        not fields
        or any(number not in (1, 2) for number, _, _ in fields)
        or len(tool_entities) != 1
        or any(number == 1 and wire_type != 2 for number, wire_type, _ in fields)
        or any(number == 2 and (wire_type != 0 or int(value) not in (0, 1)) for number, wire_type, value in fields)
    ):
        return False
    try:
        entity = read_wire_fields(tool_entities[0])
    except ValueError:
        return False
    entity_values = {
        number: int(value)
        for number, wire_type, value in entity
        if wire_type == 0
    }
    return (
        all(number in (1, 2) and wire_type == 0 for number, wire_type, _ in entity)
        and entity_values.get(1, 0) in (6, 14)
        and entity_values.get(2, 0) > 0
        and values.get(2, 0) in (0, 1)
    )


def is_tool_convert_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    entities = [bytes(value) for number, wire_type, value in fields if number == 1 and wire_type == 2]
    if not fields or len(entities) != len(fields) or not entities:
        return False
    seen: set[tuple[int, int]] = set()
    for entity in entities:
        try:
            values = {
                number: int(value)
                for number, wire_type, value in read_wire_fields(entity)
                if wire_type == 0
            }
            nested = read_wire_fields(entity)
        except ValueError:
            return False
        if (
            any(number not in (1, 2) or wire_type != 0 for number, wire_type, _ in nested)
            or values.get(1, 0) not in (6, 14)
            or values.get(2, 0) <= 0
            or (values[1], values[2]) in seen
        ):
            return False
        seen.add((values[1], values[2]))
    return True


def is_ship_bulk_update_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
        for number, wire_type, value in fields:
            if number in (1, 5) and wire_type == 0:
                if number == 5 and int(value) not in (0, 1):
                    return False
            elif number in (2, 4) and wire_type in (0, 2):
                values = [int(value)] if wire_type == 0 else read_varints(bytes(value))
                if any(value <= 0 for value in values):
                    return False
            elif number == 3 and wire_type == 2:
                wrapped = read_wire_fields(bytes(value))
                if any(inner_number != 1 or inner_type != 0 for inner_number, inner_type, _ in wrapped):
                    return False
            else:
                return False
    except ValueError:
        return False
    return (
        bool(fields)
        and any(number == 1 and wire_type == 0 and int(value) > 0 for number, wire_type, value in fields)
        and any(number == 2 and wire_type in (0, 2) for number, wire_type, _ in fields)
    )


def is_ship_tools_set_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
        for number, wire_type, value in fields:
            if number == 1 and wire_type == 0:
                if int(value) <= 0:
                    return False
            elif number == 2 and wire_type in (0, 2):
                values = [int(value)] if wire_type == 0 else read_varints(bytes(value))
                if any(value <= 0 for value in values):
                    return False
            else:
                return False
    except ValueError:
        return False
    return bool(fields) and any(number == 1 and wire_type == 0 for number, wire_type, _ in fields)


def is_ship_create_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    values = {number: int(value) for number, wire_type, value in fields if wire_type == 0}
    return (
        len(fields) == 2
        and all(number in (1, 2) and wire_type == 0 for number, wire_type, _ in fields)
        and values.get(1, 0) > 0
        and values.get(2, 0) > 0
    )


def is_mana_use_item_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    values = {number: int(value) for number, wire_type, value in fields if wire_type == 0}
    return (
        len(fields) == 2
        and all(number in (1, 2) and wire_type == 0 for number, wire_type, _ in fields)
        and values.get(1, 0) > 0
        and values.get(2, 0) > 0
    )


def is_character_bulk_set_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    if not fields:
        return False
    for number, wire_type, value in fields:
        if number == 1 and wire_type == 0:
            continue
        if number in (2, 3, 4, 5) and wire_type == 2:
            try:
                wrapped = read_wire_fields(bytes(value))
            except ValueError:
                return False
            if any(inner_number != 1 or inner_type != 0 for inner_number, inner_type, _ in wrapped):
                return False
            continue
        return False
    return any(number == 1 and wire_type == 0 for number, wire_type, _ in fields)


def is_character_enhance_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    if not fields:
        return False
    character_id_seen = False
    for number, wire_type, value in fields:
        if number == 1 and wire_type == 0 and int(value) > 0:
            character_id_seen = True
            continue
        if number == 2 and wire_type == 2:
            try:
                consumed_item = read_wire_fields(bytes(value))
            except ValueError:
                return False
            consumed_values = {
                inner_number: int(inner_value)
                for inner_number, inner_type, inner_value in consumed_item
                if inner_type == 0
            }
            if consumed_values.get(1, 0) <= 0 or consumed_values.get(2, 0) <= 0:
                return False
            if any(inner_number not in (1, 2) or inner_type != 0 for inner_number, inner_type, _ in consumed_item):
                return False
            continue
        return False
    return character_id_seen


def is_character_rarity_enhance_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    values = {
        number: int(value)
        for number, wire_type, value in fields
        if wire_type == 0
    }
    return (
        bool(fields)
        and all(number in (1, 3) and wire_type == 0 for number, wire_type, _ in fields)
        and values.get(1, 0) > 0
        and values.get(3, 0) > 0
    )


def is_character_enhancement_reset_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    values = {
        number: int(value)
        for number, wire_type, value in fields
        if wire_type == 0
    }
    return (
        bool(fields)
        and all(number in (1, 2) and wire_type == 0 for number, wire_type, _ in fields)
        and values.get(1, 0) > 0
        and values.get(2, 0) in (0, 1)
    )


def is_character_level_limit_release_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    return (
        len(fields) == 1
        and fields[0][0] == 1
        and fields[0][1] == 0
        and int(fields[0][2]) > 0
    )


def is_growboard_page_release_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    values = {
        number: int(value)
        for number, wire_type, value in fields
        if wire_type == 0
    }
    return (
        bool(fields)
        and all(
            (number in (1, 2) and wire_type == 0)
            or (number == 3 and wire_type == 2)
            for number, wire_type, _ in fields
        )
        and values.get(1, 0) > 0
        and values.get(2, 0) in (0, 1)
        and (
            3 not in {number for number, _, _ in fields}
            or nested_varint_field(data, 3, 1) is not None
        )
    )


def is_growboard_bulk_release_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    values = {
        number: int(value)
        for number, wire_type, value in fields
        if wire_type == 0
    }
    return (
        bool(fields)
        and all(
            (number in (1, 2, 3, 4) and wire_type == 0)
            or (number == 5 and wire_type == 2)
            for number, wire_type, _ in fields
        )
        and values.get(1, 0) > 0
        and values.get(2, 0) > 0
        and 0 <= values.get(3, -1) <= 0xFF
        and values.get(4, 0) in (0, 1)
        and (
            5 not in {number for number, _, _ in fields}
            or nested_varint_field(data, 5, 1) is not None
        )
    )


def is_memoria_progression_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    entity_id_seen = False
    for number, wire_type, value in fields:
        if number == 1 and wire_type == 0 and int(value) > 0:
            entity_id_seen = True
            continue
        if number == 2 and wire_type == 2:
            try:
                consumed_item = read_wire_fields(bytes(value))
            except ValueError:
                return False
            consumed_values = {
                inner_number: int(inner_value)
                for inner_number, inner_type, inner_value in consumed_item
                if inner_type == 0
            }
            if consumed_values.get(1, 0) <= 0 or consumed_values.get(2, 0) <= 0:
                return False
            if any(inner_number not in (1, 2) or inner_type != 0 for inner_number, inner_type, _ in consumed_item):
                return False
            continue
        if number == 3 and wire_type in (0, 2):
            try:
                values = [int(value)] if wire_type == 0 else read_varints(bytes(value))
            except ValueError:
                return False
            if any(entity_id <= 0 for entity_id in values):
                return False
            continue
        return False
    return entity_id_seen


def is_memoria_lock_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
    except ValueError:
        return False
    values = {
        number: int(value)
        for number, wire_type, value in fields
        if wire_type == 0
    }
    return (
        bool(fields)
        and all(number in (1, 2) and wire_type == 0 for number, wire_type, _ in fields)
        and values.get(1, 0) > 0
        and values.get(2, 0) in (0, 1)
    )


def is_memoria_sell_request(data: bytes) -> bool:
    try:
        fields = read_wire_fields(data)
        entity_ids = varint_values(data, 1)
    except ValueError:
        return False
    return (
        bool(fields)
        and all(number == 1 and wire_type in (0, 2) for number, wire_type, _ in fields)
        and bool(entity_ids)
        and all(entity_id > 0 for entity_id in entity_ids)
    )


def is_api_message(data: bytes) -> bool:
    try:
        return bool(read_wire_fields(data))
    except ValueError:
        return False


def read_varints(data: bytes) -> list[int]:
    values = []
    offset = 0
    while offset < len(data):
        value, offset = read_varint(data, offset)
        values.append(value)
    return values


_CAPTURED_RESPONSE_MATERIALS: tuple[
    dict[tuple[str, bytes, bytes], tuple[bytes, bytes, int]],
    dict[str, tuple[bytes, bytes, int]],
] | None = None


def captured_response_material(
    response_path: str,
    request_key: bytes | None = None,
    request_iv: bytes | None = None,
) -> tuple[bytes, bytes, int] | None:
    if not REPLAY_MODE:
        return None

    global _CAPTURED_RESPONSE_MATERIALS
    if _CAPTURED_RESPONSE_MATERIALS is None:
        exact_materials: dict[tuple[str, bytes, bytes], tuple[bytes, bytes, int]] = {}
        default_materials: dict[str, tuple[bytes, bytes, int]] = {}
        validators = {
            "/auth/sign_in": is_api_message,
            "/user/log_in": is_api_message,
            "/login_bonus/receive": is_api_message,
            "/external_purchase/receive": is_api_message,
            "/character/skin_set": is_skin_request_plaintext,
            "/chara_home/register": is_home_register_request,
            "/profile/update_chara_home_favorite_character_list": is_favorite_request,
            "/profile/update_selected_home_id": is_selected_home_request,
            "/exploration/start": is_exploration_start_request,
            "/exploration/finish": is_exploration_finish_request,
            "/party/bulk_update": is_party_bulk_update_request,
            "/party/battle_tools_set": is_party_battle_tools_request,
            "/character/equip": is_character_equip_request,
            "/character/memoria_set": is_character_memoria_request,
            "/character/bulk_set": is_character_bulk_set_request,
            "/equipment_preset/bulk_set": is_equipment_preset_request,
            "/equipment_preset/equip": is_equipment_preset_equip_request,
            "/equipment_preset/memoria_set": is_equipment_preset_memoria_set_request,
            "/equipment_preset/update_name": is_equipment_preset_update_name_request,
            "/tool/lock": is_tool_lock_request,
            "/tool/convert": is_tool_convert_request,
            "/mana/use_item": is_mana_use_item_request,
            "/ship/bulk_update": is_ship_bulk_update_request,
            "/ship/ship_tools_set": is_ship_tools_set_request,
            "/ship/create": is_ship_create_request,
            "/character/enhance": is_character_enhance_request,
            "/character/rarity_enhance": is_character_rarity_enhance_request,
            "/character/enhancement_reset": is_character_enhancement_reset_request,
            "/character/level_limit_release": is_character_level_limit_release_request,
            "/character/growboard_page_release": is_growboard_page_release_request,
            "/character/growboard_bulk_release": is_growboard_bulk_release_request,
            "/memoria/enhance": is_memoria_progression_request,
            "/memoria/limit_break": is_memoria_progression_request,
            "/memoria/lock": is_memoria_lock_request,
            "/memoria/sell": is_memoria_sell_request,
        }
        keys, ivs = observed_aes_candidates()
        sequences = observed_aes_sequences()
        sessions = sorted(
            (
                session
                for root in capture_roots()
                for session in root.glob("session-*")
                if session.is_dir()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for session in sessions:
            for metadata_path in sorted(session.glob("[0-9][0-9][0-9][0-9].txt"), reverse=True):
                record = parse_record(metadata_path)
                validator = validators.get(record.path)
                if validator is None or not record.response_body:
                    continue

                response_key = response_iv = None
                response_marker = record.response_body[0]
                for key in keys:
                    for iv in ivs:
                        try:
                            compressed = pkcs7_unpad(aes_decrypt(record.response_body[1:], key, iv))
                            plaintext = gzip.decompress(compressed)
                            read_wire_fields(plaintext)
                            response_key = key
                            response_iv = iv
                            break
                        except (RuntimeError, OSError, EOFError, ValueError):
                            continue
                    if response_key is not None:
                        break
                if response_key is None or not record.request_body:
                    if response_key is not None and response_iv is not None:
                        default_materials.setdefault(
                            record.path,
                            (response_key, response_iv, response_marker),
                        )
                    continue

                request_material = None
                for sequence_keys, sequence_ivs in sequences:
                    for request_key_candidate in sequence_keys:
                        for request_iv_candidate in sequence_ivs:
                            try:
                                plaintext = pkcs7_unpad(
                                    aes_decrypt(record.request_body[1:], request_key_candidate, request_iv_candidate)
                                )
                                if validator(plaintext):
                                    request_material = (request_key_candidate, request_iv_candidate)
                                    break
                            except (RuntimeError, ValueError):
                                continue
                        if request_material is not None:
                            break
                    if request_material is not None:
                        break
                if request_material is not None:
                    exact_materials.setdefault(
                        (record.path, request_material[0], request_material[1]),
                        (response_key, response_iv, response_marker),
                    )
                    default_materials.setdefault(
                        record.path,
                        (response_key, response_iv, response_marker),
                    )
        _CAPTURED_RESPONSE_MATERIALS = (exact_materials, default_materials)

    exact_materials, default_materials = _CAPTURED_RESPONSE_MATERIALS
    if request_key is not None and request_iv is not None:
        material = exact_materials.get((response_path, request_key, request_iv))
        if material is not None:
            return material
    return default_materials.get(response_path)


def varint_field(data: bytes, field_number: int, default: int = 0) -> int:
    for number, wire_type, value in read_wire_fields(data):
        if number == field_number and wire_type == 0:
            return int(value)
    return default


def nested_varint_field(data: bytes, field_number: int, nested_field_number: int) -> int | None:
    for number, wire_type, value in read_wire_fields(data):
        if number != field_number or wire_type != 2:
            continue
        for nested_number, nested_type, nested_value in read_wire_fields(bytes(value)):
            if nested_number == nested_field_number and nested_type == 0:
                return int(nested_value)
    return None


def load_profile_character_records(profile_path: Path) -> dict[int, bytes]:
    plaintext = decrypt_profile_plaintext(profile_path.read_bytes())
    resources = next(
        bytes(value)
        for field_number, wire_type, value in read_wire_fields(plaintext)
        if field_number == 1 and wire_type == 2
    )
    characters = {}
    for field_number, wire_type, value in read_wire_fields(resources):
        if field_number != 2 or wire_type != 2:
            continue
        character_id = next(
            int(inner_value)
            for inner_number, inner_type, inner_value in read_wire_fields(bytes(value))
            if inner_number == 1 and inner_type == 0
        )
        characters[character_id] = bytes(value)
    return characters


def load_profile_equipment_preset_records(profile_path: Path) -> dict[int, bytes]:
    plaintext = decrypt_profile_plaintext(profile_path.read_bytes())
    resources = next(
        bytes(value)
        for field_number, wire_type, value in read_wire_fields(plaintext)
        if field_number == 1 and wire_type == 2
    )
    presets = {}
    for field_number, wire_type, value in read_wire_fields(resources):
        if field_number != 26 or wire_type != 2:
            continue
        preset = bytes(value)
        number = next(
            int(inner_value)
            for inner_number, inner_type, inner_value in read_wire_fields(preset)
            if inner_number == 1 and inner_type == 0
        )
        presets[number] = preset
    return presets


def default_equipment_preset_record(number: int) -> bytes:
    name = f"\u88c5\u5099\u30d7\u30ea\u30bb\u30c3\u30c8{number}".encode("utf-8")
    return write_field(1, 0, number) + write_field(2, 2, name)


def profile_resources(profile_plaintext: bytes) -> bytes:
    resources = message_field(profile_plaintext, 1)
    if resources is None:
        raise ValueError("profile has no Resources message")
    return resources


def profile_resource_records(
    profile_plaintext: bytes,
    resource_field_number: int,
    key_field_number: int = 1,
) -> dict[int, bytes]:
    resources = profile_resources(profile_plaintext)
    records: dict[int, bytes] = {}
    for number, wire_type, value in read_wire_fields(resources):
        if number != resource_field_number or wire_type != 2:
            continue
        record = bytes(value)
        key = varint_field(record, key_field_number, -1)
        if key >= 0:
            records[key] = record
    return records


def consumed_item_quantities(request_plaintext: bytes, field_number: int = 2) -> dict[int, int]:
    quantities: dict[int, int] = {}
    for number, wire_type, value in read_wire_fields(request_plaintext):
        if number != field_number or wire_type != 2:
            continue
        item_id = varint_field(bytes(value), 1, 0)
        quantity = varint_field(bytes(value), 2, 0)
        if item_id <= 0 or quantity <= 0:
            raise ValueError("consumed item requires a positive ID and quantity")
        quantities[item_id] = quantities.get(item_id, 0) + quantity
    return quantities


def updated_consumed_item_records(
    item_records: dict[int, bytes],
    consumed_quantities: dict[int, int],
) -> list[bytes]:
    changed_items = []
    for item_id, amount in sorted(consumed_quantities.items()):
        record = item_records.get(item_id)
        if record is None:
            raise ValueError(f"profile has no item {item_id}")
        quantity = varint_field(record, 2, 0)
        if quantity < amount:
            raise ValueError(f"item {item_id} quantity {quantity} is below requested {amount}")
        changed_items.append(replace_varint_field(record, 2, quantity - amount))
    return changed_items


def updated_reward_item_records(
    item_records: dict[int, bytes],
    rewards: dict[int, int],
) -> list[bytes]:
    changed_items = []
    for item_id, amount in sorted(rewards.items()):
        if amount <= 0:
            continue
        record = item_records.get(item_id)
        if record is None:
            record = write_field(1, 0, item_id)
        quantity = varint_field(record, 2, 0)
        total_quantity = varint_field(record, 3, 0)
        record = replace_varint_field(record, 2, quantity + amount)
        record = replace_varint_field(record, 3, total_quantity + amount)
        changed_items.append(record)
    return changed_items


def experience_item_refund(exp: int, item_master: dict[int, dict[str, object]]) -> tuple[int, dict[int, int]]:
    """Return Japanese EXP candies in descending-value denominations, floored to the smallest candy."""
    if exp <= 0:
        return 0, {}
    experience_items = sorted(
        (
            (int(item.get("value", 0)), item_id)
            for item_id, item in item_master.items()
            if int(item.get("item_type", 0)) == 3 and int(item.get("value", 0)) > 0
        ),
        reverse=True,
    )
    if not experience_items:
        raise ValueError("progression master has no character EXP items")
    minimum_value = min(value for value, _ in experience_items)
    refundable_exp = exp - (exp % minimum_value)
    remaining = refundable_exp
    refund_items: dict[int, int] = {}
    for value, item_id in experience_items:
        quantity, remaining = divmod(remaining, value)
        if quantity:
            refund_items[item_id] = quantity
    if remaining:
        raise ValueError(f"character EXP refund left an unsupported remainder of {remaining}")
    return refundable_exp, refund_items


def resource_reward(resource_type: int, quantity: int, resource_id: int | None = None) -> bytes:
    fields = bytearray(write_field(1, 0, resource_type))
    if resource_id is not None:
        fields.extend(write_field(2, 0, resource_id))
    fields.extend(write_field(3, 0, quantity))
    return bytes(fields)


def mana_status_after_delta(status: bytes, delta: int, now: int | None = None) -> tuple[bytes, int]:
    """Apply Japanese hourly Mana regeneration, then a direct Mana change."""
    now = int(time.time()) if now is None else int(now)
    mana = varint_field(status, 4, 0)
    updated_at = message_field(status, 15)
    if mana < 20 and updated_at is not None:
        last_updated = varint_field(updated_at, 1, 0)
        mana += max(0, now - last_updated) // 3600
    mana += delta
    if mana < 0:
        raise ValueError("Mana balance is below the requested cost")
    timestamp = write_field(1, 0, now)
    updated_status = write_field(4, 0, mana) + write_field(15, 2, timestamp)
    return updated_status, mana


def growboard_spec_for_request(
    character_master: dict[str, object],
    board_type: int,
    is_ex: bool,
) -> dict[str, object]:
    """Map the captured Japanese board selector to normal, EX, or Neo profile fields."""
    if board_type == 1 and not is_ex:
        name, master_key, page_field, bits_field, width, panel_task, page_task = (
            "normal", "growboard_id", 15, 16, 7, 49, 91
        )
    elif board_type == 1 and is_ex:
        name, master_key, page_field, bits_field, width, panel_task, page_task = (
            "ex", "ex_growboard_id", 17, 18, 6, 100, None
        )
    elif board_type == 2 and not is_ex:
        name, master_key, page_field, bits_field, width, panel_task, page_task = (
            "neo", "neo_growboard_id", 35, 36, 8, None, None
        )
    else:
        raise ValueError(f"unsupported growboard selection board_type={board_type} is_ex={is_ex}")
    board_id = int(character_master.get(master_key) or 0)
    if board_id <= 0:
        raise ValueError(f"character has no {name} growboard")
    return {
        "name": name,
        "master_id": board_id,
        "page_field": page_field,
        "bits_field": bits_field,
        "width": width,
        "panel_task": panel_task,
        "page_task": page_task,
    }


NORMAL_GROWBOARD_PAGE_TASKS = {
    2: 91,
    3: 92,
    4: 93,
    5: 94,
    6: 95,
    7: 96,
    8: 97,
    9: 98,
    10: 99,
    11: 470,
    12: 471,
    13: 579,
    14: 580,
    15: 1155,
    16: 1156,
}


def normal_growboard_page_task_updates(
    task_records: dict[int, bytes],
    current_page: int,
    target_page: int,
) -> list[bytes]:
    return [
        updated_total_task_count_record(task_records, condition_id)
        for page in range(current_page + 1, target_page + 1)
        if (condition_id := NORMAL_GROWBOARD_PAGE_TASKS.get(page)) is not None
    ]


def growboard_available_page_count(
    character: bytes,
    character_master: dict[str, object],
    board: dict[str, object],
    spec: dict[str, object],
) -> int:
    page_ids = [int(value) for value in board.get("page_ids") or []]
    available = len(page_ids)
    if spec["name"] == "neo":
        available = varint_field(character, 37, 0)
        if available <= 0:
            rarity = varint_field(character, 11, int(character_master["initial_rarity"]))
            rarity_data = progression_master_index("character_common_rarity").get(rarity)
            if rarity_data is None:
                raise ValueError(f"progression master has no character rarity {rarity}")
            available = int(rarity_data.get("growboard_neo_max_page", 0))
        available = min(available, len(page_ids))
    return available


def released_growboard_panel_ids(
    character: bytes,
    character_master: dict[str, object],
    board: dict[str, object],
    spec: dict[str, object],
) -> list[int]:
    page_ids = [int(value) for value in board.get("page_ids") or []]
    available_pages = growboard_available_page_count(character, character_master, board, spec)
    page_field = int(spec["page_field"])
    bits_field = int(spec["bits_field"])
    width = int(spec["width"])
    current_page = varint_field(character, page_field, 1) or 1
    if current_page < 1 or current_page > available_pages:
        raise ValueError(
            f"character growboard page {current_page} is outside available pages 1..{available_pages}"
        )
    mask = (1 << width) - 1
    current_bits = varint_field(character, bits_field, 0)
    if current_bits & ~mask:
        raise ValueError(f"character growboard panel bits exceed the {width}-panel board mask")
    pages = progression_master_index("growboard_page")
    panel_ids: list[int] = []
    for page_index in range(current_page):
        page_id = page_ids[page_index]
        page = pages.get(page_id)
        if page is None:
            raise ValueError(f"growboard page master data is missing: {page_id}")
        page_panels = [int(value) for value in page.get("panel_ids") or []]
        if len(page_panels) != width:
            raise ValueError(f"growboard page {page_id} does not contain {width} panels")
        active_bits = mask if page_index < current_page - 1 else current_bits
        panel_ids.extend(
            panel_id
            for position, panel_id in enumerate(page_panels)
            if active_bits & (1 << position)
        )
    return panel_ids


def updated_total_task_count_record(
    task_count_records: dict[int, bytes],
    condition_id: int,
    increment: int = 1,
) -> bytes:
    if increment <= 0:
        raise ValueError("total-task-count increment must be positive")
    record = task_count_records.get(condition_id, write_field(1, 0, condition_id))
    return replace_varint_field(record, 2, varint_field(record, 2, 0) + increment)


def adjusted_total_task_count_record(
    task_count_records: dict[int, bytes],
    condition_id: int,
    delta: int,
) -> bytes | None:
    record = task_count_records.get(condition_id)
    if record is None or delta == 0:
        return None
    count = varint_field(record, 2, 0)
    updated_count = max(0, count + delta)
    if updated_count == count:
        return None
    return replace_varint_field(record, 2, updated_count)


CHARACTER_LEVEL_TASK_CONDITIONS = {
    10: 48,
    20: 86,
    30: 87,
    40: 88,
    50: 89,
    60: 158,
    70: 386,
    80: 387,
    90: 388,
    100: 574,
}


def character_level_for_exp(exp: int) -> int:
    levels = progression_master_index("character_level")
    return max(
        (level for level, data in levels.items() if int(data["exp"]) <= exp),
        default=1,
    )


def total_task_count_record_at_value(
    task_count_records: dict[int, bytes],
    condition_id: int,
    count: int,
) -> bytes:
    record = task_count_records.get(condition_id, write_field(1, 0, condition_id))
    return replace_varint_field(record, 2, count)


def character_level_task_updates(
    task_count_records: dict[int, bytes],
    old_exp: int,
    new_exp: int,
    include_max_level: bool = True,
) -> list[bytes]:
    old_level = character_level_for_exp(old_exp)
    new_level = character_level_for_exp(new_exp)
    updates = []
    if include_max_level:
        old_maximum = varint_field(task_count_records.get(47, b""), 2, 0)
        updates.append(total_task_count_record_at_value(task_count_records, 47, max(old_maximum, new_level)))
    for level, condition_id in CHARACTER_LEVEL_TASK_CONDITIONS.items():
        if old_level < level <= new_level:
            updated = adjusted_total_task_count_record(task_count_records, condition_id, 1)
        elif new_level < level <= old_level:
            updated = adjusted_total_task_count_record(task_count_records, condition_id, -1)
        else:
            updated = None
        if updated is not None:
            updates.append(updated)
    return updates


def character_with_skin(record: bytes | None, character_id: int, skin_id: int | None) -> bytes:
    fields = read_wire_fields(record) if record is not None else []
    output = bytearray()
    has_character_id = False
    has_skin = False
    for field_number, wire_type, value in fields:
        if field_number == 1:
            output.extend(write_field(1, 0, character_id))
            has_character_id = True
        elif field_number == 34:
            has_skin = True
            if skin_id is not None:
                output.extend(write_field(34, 2, write_field(1, 0, skin_id)))
        elif wire_type in (0, 1, 2, 5):
            output.extend(write_field(field_number, wire_type, value))
    if not has_character_id:
        output[:0] = write_field(1, 0, character_id)
    if skin_id is not None and not has_skin:
        output.extend(write_field(34, 2, write_field(1, 0, skin_id)))
    return bytes(output)


def character_skin_id(record: bytes) -> int | None:
    for field_number, wire_type, value in read_wire_fields(record):
        if field_number != 34 or wire_type != 2:
            continue
        for inner_number, inner_type, inner_value in read_wire_fields(bytes(value)):
            if inner_number == 1 and inner_type == 0:
                return int(inner_value)
    return None


def make_skin_response(
    character_records: dict[int, bytes],
    character_id: int,
    skin_id: int | None,
    response_key: bytes | None = None,
    response_iv: bytes | None = None,
    response_marker: int | None = None,
) -> bytes:
    if response_key is None or response_iv is None or response_marker is None:
        response_key, response_iv, response_marker = response_material()
    changed_characters = [
        character_with_skin(character_records.get(character_id), character_id, skin_id)
    ]
    if skin_id is not None:
        changed_characters.extend(
            character_with_skin(record, other_character_id, None)
            for other_character_id, record in character_records.items()
            if other_character_id != character_id and character_skin_id(record) == skin_id
        )
    resources = b"".join(write_field(2, 2, character) for character in changed_characters)
    plaintext = write_field(1, 2, resources)
    compressed = gzip.compress(plaintext, mtime=0)
    return bytes([response_marker]) + aes_encrypt(
        pkcs7_pad(compressed),
        response_key,
        response_iv,
    )


def make_illustrated_book_response(profile_path: Path, request_body: bytes) -> bytes:
    _, response_key, response_iv, response_marker = decrypt_request_with_response_material(
        request_body,
        is_api_message,
        "/illustrated_book/start",
    )
    profile_plaintext = decrypt_profile_plaintext(profile_path.read_bytes())
    resources = next(
        bytes(value)
        for number, wire, value in read_wire_fields(profile_plaintext)
        if number == 1 and wire == 2
    )
    memoria_ids = []
    for number, wire, value in read_wire_fields(resources):
        if number != 29 or wire != 2:
            continue
        memoria_id = next(
            int(inner_value)
            for inner_number, inner_wire, inner_value in read_wire_fields(bytes(value))
            if inner_number == 2 and inner_wire == 0
        )
        memoria_ids.append(memoria_id)
    memoria_values = b"".join(
        write_varint(memoria_id) for memoria_id in dict.fromkeys(memoria_ids)
    )
    treasure_values = b"".join(
        write_varint(reward_id) for reward_id in DEFAULT_EXPEDITION_SPECIAL_REWARD_IDS
    )
    plaintext = b"".join(
        (
            write_field(1, 2, b""),
            write_field(3, 2, memoria_values),
            write_field(4, 2, treasure_values),
        )
    )
    return encrypt_api_response(response_marker, plaintext, response_key, response_iv)


def message_field(data: bytes, field_number: int) -> bytes | None:
    return next(
        (
            bytes(value)
            for number, wire_type, value in read_wire_fields(data)
            if number == field_number and wire_type == 2
        ),
        None,
    )


def varint_values(data: bytes, field_number: int) -> list[int]:
    values = []
    for number, wire_type, value in read_wire_fields(data):
        if number != field_number:
            continue
        if wire_type == 0:
            values.append(int(value))
        elif wire_type == 2:
            values.extend(read_varints(bytes(value)))
    return values


def replace_message_field_in_place(data: bytes, field_number: int, value: bytes | None) -> bytes:
    output = bytearray()
    replaced = False
    for number, wire_type, field_value in read_wire_fields(data):
        if number == field_number:
            if value is not None and not replaced:
                output.extend(write_field(field_number, 2, value))
                replaced = True
            continue
        output.extend(write_field(number, wire_type, field_value))
    if value is not None and not replaced:
        output.extend(write_field(field_number, 2, value))
    return bytes(output)


def replace_packed_varint_field(data: bytes, field_number: int, values: list[int]) -> bytes:
    without_field = replace_message_field_in_place(data, field_number, None)
    packed = b"".join(write_varint(value) for value in values)
    return without_field + write_field(field_number, 2, packed)


def character_with_equipment(
    record: bytes | None,
    character_id: int,
    field_number: int,
    value: bytes | None,
) -> bytes:
    character = record or write_field(1, 0, character_id)
    character = replace_message_field_in_place(character, field_number, value)
    if not any(number == 1 and wire_type == 0 for number, wire_type, _ in read_wire_fields(character)):
        character = write_field(1, 0, character_id) + character
    return character


def party_member_from_request(data: bytes, party_type: int, number: int, position: int) -> bytes:
    member = bytearray()
    member.extend(write_field(1, 0, party_type))
    member.extend(write_field(2, 0, number))
    member.extend(write_field(3, 0, position))
    output_fields = {
        1: 4,
        2: 5,
        3: 6,
        4: 7,
        5: 8,
    }
    for source_field, target_field in output_fields.items():
        value = message_field(data, source_field)
        if value is not None:
            member.extend(write_field(target_field, 2, value))
    return bytes(member)


def party_from_request(
    party_type: int,
    number: int,
    battle_tool_entity_ids: list[int],
    leader_position: int | None,
) -> bytes:
    party = bytearray()
    party.extend(write_field(1, 0, number))
    for entity_id in battle_tool_entity_ids:
        party.extend(write_field(4, 0, entity_id))
    party.extend(write_field(5, 0, party_type))
    if leader_position is not None:
        party.extend(write_field(6, 0, leader_position))
    return bytes(party)


EXPLORATION_ROUTE_TYPE_VALUES = {
    "gathering": 0,
    "battle": 1,
    "talk": 2,
}


def exploration_routes(quest_id: int) -> list[dict[str, int | str]]:
    path = GAME_DIR / "exploration-routes-jp.json"
    try:
        routes = json.loads(path.read_text(encoding="utf-8"))
        values = routes.get(str(quest_id), [])
        return [
            {
                "area_id": int(value["area_id"]),
                "number": int(value.get("number", 0)),
                "route_type": str(value["route_type"]),
            }
            for value in values
        ]
    except (OSError, TypeError, ValueError, json.JSONDecodeError, KeyError):
        return []


def exploration_party_status_from_progress(progress: bytes) -> bytes | None:
    return next(
        (
            bytes(value)
            for field_number, wire_type, value in read_wire_fields(progress)
            if field_number == 14 and wire_type == 2
        ),
        None,
    )


def exploration_progress_from_response(data: bytes) -> tuple[bytes, bytes] | None:
    try:
        resources = next(
            bytes(value)
            for field_number, wire_type, value in read_wire_fields(data)
            if field_number == 1 and wire_type == 2
        )
        progress = next(
            bytes(value)
            for field_number, wire_type, value in read_wire_fields(resources)
            if field_number == 25 and wire_type == 2
        )
    except (StopIteration, ValueError):
        return None
    party_status = exploration_party_status_from_progress(progress)
    return progress, party_status or b""


def default_exploration_party_status(slot_count: int = 5) -> bytes:
    status = bytearray()
    for _ in range(slot_count):
        status.extend(write_field(1, 0, 1))
        status.extend(write_field(2, 2, b""))
        status.extend(write_field(4, 0, 0))
    return bytes(status)


def make_exploration_progress(
    quest_id: int,
    party_number: int,
    routes: list[dict[str, int | str]],
    party_status: bytes,
    control_character_id: bytes | None = None,
) -> tuple[bytes, int]:
    if not routes:
        routes = [{"area_id": quest_id * 10 + 1, "number": 0, "route_type": "gathering"}]
    route_values = [EXPLORATION_ROUTE_TYPE_VALUES.get(str(route["route_type"]), 0) for route in routes]
    progress = bytearray()
    progress.extend(write_field(1, 0, quest_id))
    progress.extend(write_field(2, 0, int(routes[0]["area_id"])))
    for route_value in route_values:
        progress.extend(write_field(3, 0, route_value))
    for _ in routes:
        progress.extend(write_field(4, 0, 0))
    progress.extend(write_field(5, 0, party_number))
    if control_character_id is not None:
        progress.extend(write_field(7, 2, control_character_id))
    for _ in routes:
        progress.extend(write_field(12, 0, 0))
    progress.extend(write_field(14, 2, party_status or default_exploration_party_status()))
    return bytes(progress), int(routes[0]["area_id"])


def make_exploration_start_response(progress: bytes) -> bytes:
    resources = write_field(25, 2, progress)
    return write_field(1, 2, resources)


def make_exploration_finish_response() -> bytes:
    return write_field(2, 2, b"")


class Replay:
    def __init__(self):
        self.session = session_directory()
        self.records = sorted(
            (parse_record(path) for path in self.session.glob("[0-9][0-9][0-9][0-9].txt")),
            key=lambda record: record.number,
        )
        self.used: set[int] = set()
        self.character_records: dict[int, bytes] | None = None
        self.equipment_preset_records: dict[int, bytes] | None = None
        self.home_state_loaded = False
        self.home_profile = b""
        self.home_records: dict[int, bytes] = {}
        self.home_favorite_character_ids: list[int] = []
        self.last_selected_home_field = 10
        self.exploration_templates: dict[tuple[int, int], tuple[bytes, bytes]] = {}
        self.exploration_fallback_template: tuple[bytes, bytes] | None = None
        self.expedition_special_reward_ids = expedition_special_reward_ids()
        self.expedition_special_reward_index = 0
        self.default_login_attempts = 0
        self.hybrid_logged_in = False
        self.profile_backup_path: Path | None = None
        self.profile_backup_failed = False
        self.log_path = GAME_DIR / "offline-replay.log"
        if not REPLAY_MODE:
            self.backup_profile_at_session_start()
        self.log(
            f"loaded session={self.session} records={len(self.records)} "
            f"capture_fallback={not bool(self.records)} mode={'replay' if REPLAY_MODE else 'generated'}"
        )
        if not self.records:
            self.log("CAPTURE-SESSION-MISSING using profile/default offline responses")

    def log(self, message: str) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")

    def backup_profile_at_session_start(self) -> None:
        profile_path = GAME_DIR / "profile.bin"
        if not profile_path.is_file():
            self.log("PROFILE-BACKUP-SKIPPED reason=profile_missing_at_session_start")
            return
        try:
            original = profile_path.read_bytes()
            backup_dir = GAME_DIR / "profile-backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            base = backup_dir / f"profile-before-offline-session-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.bin"
            backup = base
            suffix = 1
            while backup.exists():
                backup = base.with_name(f"{base.stem}-{suffix}{base.suffix}")
                suffix += 1
            backup.write_bytes(original)
            self.profile_backup_path = backup
            self.log(f"PROFILE-BACKUP path={backup.name} timing=session_start")
        except OSError as error:
            self.profile_backup_failed = True
            self.log(f"PROFILE-BACKUP-FAILED timing=session_start reason={type(error).__name__}:{error}")

    def persist_profile_update(self, changed_response_plaintext: bytes, source: str) -> None:
        if REPLAY_MODE or not changed_response_plaintext:
            return
        profile_path = GAME_DIR / "profile.bin"
        try:
            current_profile = profile_path.read_bytes()
            if not current_profile:
                raise ValueError("profile.bin is empty")
            marker = current_profile[0]
            if marker >= len(JAPANESE_AES_KEYS):
                raise ValueError("profile.bin has an invalid AES marker")
            current_plaintext = decrypt_profile_plaintext(current_profile)
            merged_plaintext = merge_profile_resources_response(
                current_plaintext,
                changed_response_plaintext,
            )
            if merged_plaintext is None or merged_plaintext == current_plaintext:
                return

            if self.profile_backup_path is None:
                if self.profile_backup_failed:
                    raise OSError("profile backup at session start failed")
                self.backup_profile_at_session_start()
                if self.profile_backup_path is None:
                    raise OSError("could not create a profile backup before mutation")

            encrypted = encrypt_api_response(
                marker,
                merged_plaintext,
                JAPANESE_AES_KEYS[marker],
                JAPANESE_AES_IV,
            )
            temporary = profile_path.with_name(profile_path.name + ".offline.tmp")
            temporary.write_bytes(encrypted)
            temporary.replace(profile_path)
            self.log(f"PROFILE-PERSISTED source={source} bytes={len(encrypted)}")
        except (OSError, RuntimeError, ValueError, StopIteration) as error:
            self.log(f"PROFILE-PERSIST-FAILED source={source} reason={type(error).__name__}:{error}")

    def persist_changed_resources_response(self, response_body: bytes, source: str) -> None:
        try:
            _, plaintext, _, _ = decrypt_api_response(response_body)
            self.persist_profile_update(plaintext, source)
        except (OSError, RuntimeError, ValueError, StopIteration) as error:
            self.log(f"PROFILE-PERSIST-DECODE-FAILED source={source} reason={type(error).__name__}:{error}")

    def choose(self, flow: http.HTTPFlow) -> Record | None:
        original_host = flow.request.headers.get("x-offline-original-host", flow.request.host).lower()
        path = urlsplit(flow.request.pretty_url).path
        method = flow.request.method.upper()
        request_body = flow.request.raw_content or b""
        body_hash = hashlib.sha256(request_body).hexdigest()
        candidates = [
            record
            for record in self.records
            if (record.number not in self.used or path in REUSABLE_PATHS)
            and urlsplit(record.url).netloc.lower() == f"game.resleriana.jp"
            and record.path == path
            and record.method == method
        ]
        if not candidates:
            self.log(f"MISS host={original_host} method={method} path={path} body={len(request_body)}")
            return None

        asset_version = flow.request.headers.get("x-asset-version", "")
        matching_header = [
            record
            for record in candidates
            if record.request_headers.get("x-asset-version", "") == asset_version
        ]
        header_candidates = matching_header if matching_header else candidates
        exact_body = [record for record in header_candidates if record.body_hash == body_hash]
        chosen = exact_body[0] if exact_body else header_candidates[0]

        if path not in REUSABLE_PATHS:
            self.used.add(chosen.number)
        self.log(
            f"HIT {chosen.number:04d} host={original_host} method={method} "
            f"path={path} status={chosen.status} body={len(request_body)}"
        )
        return chosen

    def skin_response(self, flow: http.HTTPFlow) -> bytes:
        request_body = flow.request.raw_content or b""
        try:
            character_id, skin_id, response_key, response_iv, response_marker = decode_skin_request(request_body)
            if self.character_records is None:
                self.character_records = load_profile_character_records(GAME_DIR / "profile.bin")
            cleared_character_ids = []
            if skin_id is not None:
                cleared_character_ids = [
                    other_character_id
                    for other_character_id, record in self.character_records.items()
                    if other_character_id != character_id and character_skin_id(record) == skin_id
                ]
            response = make_skin_response(
                self.character_records,
                character_id,
                skin_id,
                response_key,
                response_iv,
                response_marker,
            )
            self.persist_changed_resources_response(response, "/character/skin_set")
            for other_character_id in cleared_character_ids:
                self.character_records[other_character_id] = character_with_skin(
                    self.character_records[other_character_id],
                    other_character_id,
                    None,
                )
            self.character_records[character_id] = character_with_skin(
                self.character_records.get(character_id),
                character_id,
                skin_id,
            )
            self.log(
                f"LOCAL-SKIN host={flow.request.host} method=POST path=/character/skin_set "
                f"status=200 character_id={character_id} skin_id={skin_id if skin_id is not None else 'default'} "
                f"cleared_character_ids={','.join(str(value) for value in cleared_character_ids) or 'none'}"
            )
            return response
        except (OSError, RuntimeError, ValueError, StopIteration) as error:
            request_body = flow.request.raw_content or b""
            self.log(
                f"SKIN-KEY-WAIT-FAILED path=/character/skin_set reason={type(error).__name__}:{error} "
                f"body={len(request_body)} hash={hashlib.sha256(request_body).hexdigest()}"
            )
            raise

    def party_response(self, flow: http.HTTPFlow) -> bytes:
        path = urlsplit(flow.request.pretty_url).path
        request_body = flow.request.raw_content or b""
        validators = {
            "/party/bulk_update": is_party_bulk_update_request,
            "/party/battle_tools_set": is_party_battle_tools_request,
            "/character/equip": is_character_equip_request,
            "/character/memoria_set": is_character_memoria_request,
            "/character/bulk_set": is_character_bulk_set_request,
            "/equipment_preset/bulk_set": is_equipment_preset_request,
            "/equipment_preset/equip": is_equipment_preset_equip_request,
            "/equipment_preset/memoria_set": is_equipment_preset_memoria_set_request,
            "/equipment_preset/update_name": is_equipment_preset_update_name_request,
        }
        plaintext, response_key, response_iv, response_marker = decrypt_request_with_response_material(
            request_body,
            validators[path],
            path,
        )

        if path == "/party/bulk_update":
            values = {
                number: int(value)
                for number, wire_type, value in read_wire_fields(plaintext)
                if wire_type == 0
            }
            member_payloads = [
                bytes(value)
                for number, wire_type, value in read_wire_fields(plaintext)
                if number == 3 and wire_type == 2
            ]
            party_members = [
                party_member_from_request(member, values[1], values[2], position)
                for position, member in enumerate(member_payloads, 1)
            ]
            party = party_from_request(
                values[1],
                values[2],
                varint_values(plaintext, 4),
                values.get(5),
            )
            self.log(
                f"LOCAL-PARTY-BULK host={flow.request.host} method=POST path={path} status=200 "
                f"party_type={values[1]} number={values[2]} members={len(party_members)}"
            )
            return self.changed_resources_encrypted_response(
                response_key,
                response_iv,
                response_marker,
                parties=[party],
                party_members=party_members,
            )

        if path == "/party/battle_tools_set":
            values = {
                number: int(value)
                for number, wire_type, value in read_wire_fields(plaintext)
                if wire_type == 0
            }
            party = party_from_request(
                values[3],
                values[1],
                varint_values(plaintext, 2),
                None,
            )
            self.log(
                f"LOCAL-PARTY-TOOLS host={flow.request.host} method=POST path={path} status=200 "
                f"party_type={values[3]} number={values[1]} tools={len(varint_values(plaintext, 2))}"
            )
            return self.changed_resources_encrypted_response(
                response_key,
                response_iv,
                response_marker,
                parties=[party],
            )

        if path.startswith("/equipment_preset/"):
            preset_number = next(
                int(value)
                for number, wire_type, value in read_wire_fields(plaintext)
                if number == 1 and wire_type == 0
            )
            if self.equipment_preset_records is None:
                self.equipment_preset_records = load_profile_equipment_preset_records(GAME_DIR / "profile.bin")
            preset = self.equipment_preset_records.get(
                preset_number,
                default_equipment_preset_record(preset_number),
            )
            if path == "/equipment_preset/bulk_set":
                for source_field, target_field in ((2, 3), (3, 4), (4, 5), (5, 6)):
                    preset = replace_message_field_in_place(
                        preset,
                        target_field,
                        message_field(plaintext, source_field),
                    )
            elif path == "/equipment_preset/equip":
                slot_type = varint_field(plaintext, 2, 0)
                if slot_type not in (1, 2, 3):
                    raise ValueError(f"unsupported equipment preset slot type: {slot_type}")
                preset = replace_message_field_in_place(
                    preset,
                    slot_type + 2,
                    message_field(plaintext, 3),
                )
            elif path == "/equipment_preset/memoria_set":
                preset = replace_message_field_in_place(
                    preset,
                    6,
                    message_field(plaintext, 2),
                )
            else:
                name = next(
                    bytes(value)
                    for number, wire_type, value in read_wire_fields(plaintext)
                    if number == 2 and wire_type == 2
                )
                preset = replace_message_field_in_place(preset, 2, name)
            self.equipment_preset_records[preset_number] = preset
            self.log(
                f"LOCAL-EQUIPMENT-PRESET host={flow.request.host} method=POST path={path} status=200 "
                f"preset_number={preset_number}"
            )
            return self.changed_resources_encrypted_response(
                response_key,
                response_iv,
                response_marker,
                equipment_presets=[preset],
            )

        if self.character_records is None:
            self.character_records = load_profile_character_records(GAME_DIR / "profile.bin")
        character_id = next(
            int(value)
            for number, wire_type, value in read_wire_fields(plaintext)
            if number == 1 and wire_type == 0
        )
        record = self.character_records.get(character_id)
        if path == "/character/bulk_set":
            character = record or write_field(1, 0, character_id)
            for source_field, target_field in ((2, 3), (3, 4), (4, 5), (5, 28)):
                character = replace_message_field_in_place(
                    character,
                    target_field,
                    message_field(plaintext, source_field),
                )
            self.character_records[character_id] = character
            self.log(
                f"LOCAL-CHARACTER-BULK host={flow.request.host} method=POST path={path} status=200 "
                f"character_id={character_id}"
            )
        elif path == "/character/equip":
            slot_type = next(
                int(value)
                for number, wire_type, value in read_wire_fields(plaintext)
                if number == 2 and wire_type == 0
            )
            if slot_type not in (1, 2, 3):
                raise ValueError(f"unsupported character equipment slot: {slot_type}")
            character = character_with_equipment(
                record,
                character_id,
                slot_type + 2,
                message_field(plaintext, 3),
            )
            self.character_records[character_id] = character
            self.log(
                f"LOCAL-CHARACTER-EQUIP host={flow.request.host} method=POST path={path} status=200 "
                f"character_id={character_id} slot_type={slot_type}"
            )
        else:
            character = character_with_equipment(
                record,
                character_id,
                28,
                message_field(plaintext, 2),
            )
            self.character_records[character_id] = character
            self.log(
                f"LOCAL-CHARACTER-MEMORIA host={flow.request.host} method=POST path={path} status=200 "
                f"character_id={character_id}"
            )
        return self.changed_resources_encrypted_response(
            response_key,
            response_iv,
            response_marker,
            characters=[character],
        )

    def tool_response(self, flow: http.HTTPFlow) -> bytes:
        path = urlsplit(flow.request.pretty_url).path
        validators = {
            "/tool/lock": is_tool_lock_request,
            "/tool/convert": is_tool_convert_request,
        }
        request_plaintext, response_key, response_iv, response_marker = decrypt_request_with_response_material(
            flow.request.raw_content or b"",
            validators[path],
            path,
        )
        profile_plaintext = decrypt_profile_plaintext((GAME_DIR / "profile.bin").read_bytes())

        if path == "/tool/lock":
            tool_entity = message_field(request_plaintext, 1)
            if tool_entity is None:
                raise ValueError("tool lock request has no ToolEntity")
            tool_type = varint_field(tool_entity, 1, 0)
            entity_id = varint_field(tool_entity, 2, 0)
            is_locked = varint_field(request_plaintext, 2, 0) == 1
            if tool_type == 14:
                resource_field = 11
                records = profile_resource_records(profile_plaintext, resource_field)
                record = records.get(entity_id)
                if record is None:
                    raise ValueError(f"profile has no battle tool entity {entity_id}")
                updated = b"".join(
                    write_field(number, wire_type, value)
                    for number, wire_type, value in read_wire_fields(record)
                    if number != 8
                )
                if is_locked:
                    updated += write_field(8, 0, 1)
                self.log(f"LOCAL-TOOL-LOCK path={path} status=200 type={tool_type} locked={is_locked}")
                return self.changed_resources_encrypted_response(
                    response_key,
                    response_iv,
                    response_marker,
                    battle_tools=[updated],
                )
            if tool_type == 6:
                resource_field = 4
                records = profile_resource_records(profile_plaintext, resource_field)
                record = records.get(entity_id)
                if record is None:
                    raise ValueError(f"profile has no equipment tool entity {entity_id}")
                updated = b"".join(
                    write_field(number, wire_type, value)
                    for number, wire_type, value in read_wire_fields(record)
                    if number != 8
                )
                if is_locked:
                    updated += write_field(8, 0, 1)
                self.log(f"LOCAL-TOOL-LOCK path={path} status=200 type={tool_type} locked={is_locked}")
                return self.changed_resources_encrypted_response(
                    response_key,
                    response_iv,
                    response_marker,
                    equipment_tools=[updated],
                )
            raise ValueError(f"unsupported ToolEntity type {tool_type}")

        consumed_entities = [
            bytes(value)
            for number, wire_type, value in read_wire_fields(request_plaintext)
            if number == 1 and wire_type == 2
        ]
        battle_tool_records = profile_resource_records(profile_plaintext, 11)
        equipment_tool_records = profile_resource_records(profile_plaintext, 4)
        tool_masters = {
            14: progression_master_index("battle_tool"),
            6: progression_master_index("equipment_tool"),
        }
        converted_entities = {14: [], 6: []}
        reward_quantity = 0
        for consumed_entity in consumed_entities:
            tool_type = varint_field(consumed_entity, 1, 0)
            entity_id = varint_field(consumed_entity, 2, 0)
            records = battle_tool_records if tool_type == 14 else equipment_tool_records
            tool_record = records.get(entity_id)
            if tool_record is None:
                raise ValueError(f"profile has no tool entity {entity_id} of type {tool_type}")
            tool_id = varint_field(tool_record, 2, 0)
            master = tool_masters[tool_type].get(tool_id)
            if master is None:
                raise ValueError(f"progression master has no tool {tool_id} of type {tool_type}")
            rarity = int(master.get("rarity", 0))
            converted_value = {1: 1, 2: 3}.get(rarity, 10)
            trait_rank_total = sum(
                varint_field(bytes(value), 2, 0)
                for number, wire_type, value in read_wire_fields(tool_record)
                if number == 5 and wire_type == 2
            )
            rank_total = progression_master_index("trait_rank_total").get(trait_rank_total + 1, {})
            reward_field = (
                "battle_tool_conversion_rewards"
                if tool_type == 14
                else "equipment_tool_conversion_rewards"
            )
            conversion_rewards = rank_total.get(reward_field) or []
            if conversion_rewards:
                converted_value += int(conversion_rewards[0].get("quantity", 0))
            reward_quantity += converted_value
            converted_entities[tool_type].append(entity_id)

        item_records = profile_resource_records(profile_plaintext, 3)
        changed_items = updated_reward_item_records(item_records, {134: reward_quantity})
        reward_item = next(record for record in changed_items if varint_field(record, 1, 0) == 134)
        task_records = profile_resource_records(profile_plaintext, 32)
        total_converted_count = len(consumed_entities)
        task_updates = [
            total_task_count_record_at_value(task_records, 739, varint_field(reward_item, 3, 0)),
            updated_total_task_count_record(task_records, 135, total_converted_count),
        ]
        deleted_resources = bytearray()
        if converted_entities[6]:
            deleted_resources.extend(
                write_field(1, 2, b"".join(write_varint(value) for value in converted_entities[6]))
            )
        if converted_entities[14]:
            deleted_resources.extend(
                write_field(2, 2, b"".join(write_varint(value) for value in converted_entities[14]))
            )
        reward = resource_reward(5, reward_quantity, 134)
        tool_conversion_limit_count = varint_field(profile_plaintext, 6, 100)
        self.log(
            f"LOCAL-TOOL-CONVERT path={path} status=200 tools={total_converted_count} "
            f"reward={reward_quantity}"
        )
        return self.changed_resources_encrypted_response(
            response_key,
            response_iv,
            response_marker,
            items=changed_items,
            total_task_counts=task_updates,
            deleted_resources=bytes(deleted_resources),
            extra_response_fields=[(3, 2, reward), (4, 0, tool_conversion_limit_count)],
        )

    def mana_response(self, flow: http.HTTPFlow) -> bytes:
        request_plaintext, response_key, response_iv, response_marker = decrypt_request_with_response_material(
            flow.request.raw_content or b"",
            is_mana_use_item_request,
            "/mana/use_item",
        )
        profile_plaintext = decrypt_profile_plaintext((GAME_DIR / "profile.bin").read_bytes())
        item_id = varint_field(request_plaintext, 1, 0)
        count = varint_field(request_plaintext, 2, 0)
        items = updated_consumed_item_records(
            profile_resource_records(profile_plaintext, 3),
            {item_id: count},
        )
        status = message_field(profile_resources(profile_plaintext), 6)
        if status is None:
            raise ValueError("profile has no Status message for Mana item use")
        status, new_mana = mana_status_after_delta(status, count)
        task_records = profile_resource_records(profile_plaintext, 32)
        task_counts = [task_records[1]] if 1 in task_records else []
        self.log(f"LOCAL-MANA-USE path=/mana/use_item status=200 item={item_id} count={count} mana={new_mana}")
        return self.changed_resources_encrypted_response(
            response_key,
            response_iv,
            response_marker,
            items=items,
            status=status,
            total_task_counts=task_counts,
        )

    def ship_response(self, flow: http.HTTPFlow) -> bytes:
        path = urlsplit(flow.request.pretty_url).path
        validators = {
            "/ship/bulk_update": is_ship_bulk_update_request,
            "/ship/ship_tools_set": is_ship_tools_set_request,
            "/ship/create": is_ship_create_request,
        }
        request_plaintext, response_key, response_iv, response_marker = decrypt_request_with_response_material(
            flow.request.raw_content or b"",
            validators[path],
            path,
        )
        profile_plaintext = decrypt_profile_plaintext((GAME_DIR / "profile.bin").read_bytes())

        if path in ("/ship/bulk_update", "/ship/ship_tools_set"):
            party_number = varint_field(request_plaintext, 1, 0)
            party_records = profile_resource_records(profile_plaintext, 67)
            party = party_records.get(party_number, write_field(1, 0, party_number))
            if path == "/ship/bulk_update":
                party = replace_packed_varint_field(party, 2, varint_values(request_plaintext, 2))
                party = replace_message_field_in_place(party, 3, message_field(request_plaintext, 3))
                party = replace_packed_varint_field(party, 4, varint_values(request_plaintext, 4))
                task_records = profile_resource_records(profile_plaintext, 32)
                task_count = updated_total_task_count_record(task_records, 2877)
                task_counts = [task_count]
            else:
                selected_ship_tools = varint_values(request_plaintext, 2)
                owned_ship_tools = profile_resource_records(profile_plaintext, 68)
                if any(entity_id not in owned_ship_tools for entity_id in selected_ship_tools):
                    raise ValueError("ship party references an unowned ship tool")
                party = replace_packed_varint_field(party, 5, selected_ship_tools)
                task_counts = []
            self.log(
                f"LOCAL-SHIP-PARTY path={path} status=200 party={party_number} "
                f"members={len(varint_values(request_plaintext, 2)) if path.endswith('bulk_update') else 0}"
            )
            return self.changed_resources_encrypted_response(
                response_key,
                response_iv,
                response_marker,
                ship_parties=[party],
                total_task_counts=task_counts,
            )

        part_id = varint_field(request_plaintext, 1, 0)
        count = varint_field(request_plaintext, 2, 0)
        part = progression_master_index("ship_part").get(part_id)
        if part is None:
            raise ValueError(f"Japanese ship-part master has no part {part_id}")
        consumed_items: dict[int, int] = {}
        mana_cost = 0
        for cost in part.get("costs") or []:
            resource_type = int(cost.get("type", 0))
            resource_id = int(cost.get("id", 0))
            quantity = int(cost.get("quantity", 0)) * count
            if quantity <= 0:
                continue
            if resource_type == 5:
                consumed_items[resource_id] = consumed_items.get(resource_id, 0) + quantity
            elif resource_type == 9 and resource_id == 1:
                mana_cost += quantity
            else:
                raise ValueError(
                    f"unsupported ship-part cost type={resource_type} id={resource_id}"
                )
        item_records = profile_resource_records(profile_plaintext, 3)
        changed_items = updated_consumed_item_records(item_records, consumed_items)
        resources = profile_resources(profile_plaintext)
        status_record = message_field(resources, 6)
        if status_record is None:
            raise ValueError("profile has no Status message for ship-part creation")
        changed_status = (
            mana_status_after_delta(status_record, -mana_cost)[0]
            if mana_cost
            else None
        )
        target = int(part.get("enhance_target", 0))
        enhance_type = int(part.get("enhance_type", 0))
        target_id = int(part.get("target_id", 0))
        value = int(part.get("value", 0)) * count
        if target == 1:
            ship_records = profile_resource_records(profile_plaintext, 66)
            ship = ship_records.get(target_id)
            if ship is None:
                raise ValueError(f"profile has no ship {target_id}")
            if enhance_type == 1:
                exp = varint_field(ship, 2, 0) + value
                level_data = progression_master_index("ship_level")
                derived_rank = max(
                    (
                        int(data.get("rank", 0))
                        for data in level_data.values()
                        if int(data.get("exp", 0)) <= exp
                    ),
                    default=varint_field(ship, 3, 1),
                )
                rank = max(varint_field(ship, 3, 1), derived_rank)
            elif enhance_type == 2:
                exp = varint_field(ship, 2, 0)
                rank = varint_field(ship, 3, 1) + value
            else:
                raise ValueError(f"unsupported ship enhancement type {enhance_type}")
            ship = replace_varint_field(ship, 2, exp)
            ship = replace_varint_field(ship, 3, rank)
            ship_records = [ship]
            ship_tool_records = []
            task_records = profile_resource_records(profile_plaintext, 32)
            task_counts = [updated_total_task_count_record(task_records, 2875, count)]
            if 2878 in task_records:
                task_counts.append(task_records[2878])
        elif target == 2:
            ship_tools = profile_resource_records(profile_plaintext, 68)
            matches = [
                record
                for record in ship_tools.values()
                if varint_field(record, 2, 0) == target_id
            ]
            if len(matches) != 1:
                raise ValueError(f"profile must contain one ship tool with tool_id={target_id}")
            ship_tool = matches[0]
            if enhance_type == 1:
                exp = varint_field(ship_tool, 3, 0) + value
                level_data = progression_master_index("ship_tool_level")
                derived_rank = max(
                    (
                        int(data.get("rank", 0))
                        for data in level_data.values()
                        if int(data.get("exp", 0)) <= exp
                    ),
                    default=varint_field(ship_tool, 4, 1),
                )
                rank = max(varint_field(ship_tool, 4, 1), derived_rank)
            elif enhance_type == 2:
                exp = varint_field(ship_tool, 3, 0)
                rank = varint_field(ship_tool, 4, 1) + value
            else:
                raise ValueError(f"unsupported ship-tool enhancement type {enhance_type}")
            ship_tool = replace_varint_field(ship_tool, 3, exp)
            ship_tool = replace_varint_field(ship_tool, 4, rank)
            ship_records = []
            ship_tool_records = [ship_tool]
            task_counts = []
        else:
            raise ValueError(f"unsupported ship-part enhancement target {target}")

        self.log(
            f"LOCAL-SHIP-CREATE path={path} status=200 part={part_id} count={count} "
            f"target={target} target_id={target_id}"
        )
        return self.changed_resources_encrypted_response(
            response_key,
            response_iv,
            response_marker,
            items=changed_items,
            status=changed_status,
            total_task_counts=task_counts,
            ships=ship_records,
            ship_tools=ship_tool_records,
        )

    def progression_response(self, flow: http.HTTPFlow) -> bytes:
        path = urlsplit(flow.request.pretty_url).path
        validators = {
            "/character/enhance": is_character_enhance_request,
            "/character/rarity_enhance": is_character_rarity_enhance_request,
            "/character/enhancement_reset": is_character_enhancement_reset_request,
            "/character/level_limit_release": is_character_level_limit_release_request,
            "/character/growboard_page_release": is_growboard_page_release_request,
            "/character/growboard_bulk_release": is_growboard_bulk_release_request,
            "/memoria/enhance": is_memoria_progression_request,
            "/memoria/limit_break": is_memoria_progression_request,
            "/memoria/lock": is_memoria_lock_request,
            "/memoria/sell": is_memoria_sell_request,
        }
        request_plaintext, response_key, response_iv, response_marker = decrypt_request_with_response_material(
            flow.request.raw_content or b"",
            validators[path],
            path,
        )
        profile_plaintext = decrypt_profile_plaintext((GAME_DIR / "profile.bin").read_bytes())
        resources = profile_resources(profile_plaintext)

        if path == "/character/enhance":
            character_id = varint_field(request_plaintext, 1, 0)
            character = profile_resource_records(profile_plaintext, 2).get(character_id)
            if character is None:
                raise ValueError(f"profile has no character {character_id}")
            item_records = profile_resource_records(profile_plaintext, 3)
            consumed = consumed_item_quantities(request_plaintext)
            items = updated_consumed_item_records(item_records, consumed)
            item_master = progression_master_index("item")
            gained_exp = 0
            for item_id, quantity in consumed.items():
                item_data = item_master.get(item_id)
                if item_data is None:
                    raise ValueError(f"progression master has no item {item_id}")
                gained_exp += int(item_data.get("value", 0)) * quantity

            # CharacterLevelData stores the next level's EXP threshold; the playable cap is one below it.
            level_limit = (
                (varint_field(character, 29, 10) or 10)
                + varint_field(character, 30, 0)
                + 1
            )
            level_data = progression_master_index("character_level").get(level_limit)
            if level_data is None:
                raise ValueError(f"progression master has no character level limit {level_limit}")
            exp_limit = max(0, int(level_data["exp"]) - 1)
            old_exp = varint_field(character, 12, 0)
            new_exp = min(old_exp + gained_exp, exp_limit)
            new_character = replace_varint_field(character, 12, new_exp)
            status = None
            # Japanese character EXP enhancement charges one tenth of the consumed item's EXP in Cole.
            cole_cost = gained_exp // 10
            if cole_cost:
                status = message_field(resources, 6)
                if status is None:
                    raise ValueError("profile has no Status message for character EXP cost")
                cole = varint_field(status, 3, 0)
                if cole < cole_cost:
                    raise ValueError(f"Cole quantity {cole} is below character EXP cost {cole_cost}")
                status = replace_varint_field(status, 3, cole - cole_cost)
            if self.character_records is not None:
                self.character_records[character_id] = new_character
            task_counts = (
                character_level_task_updates(
                    profile_resource_records(profile_plaintext, 32),
                    old_exp,
                    new_exp,
                )
                if gained_exp > 0
                else []
            )
            self.log(
                f"LOCAL-CHARACTER-ENHANCE path={path} status=200 character_id={character_id} "
                f"items={len(items)} gained_exp={gained_exp} cole={cole_cost} "
                f"exp={varint_field(new_character, 12, 0)}"
            )
            return self.changed_resources_encrypted_response(
                response_key,
                response_iv,
                response_marker,
                characters=[new_character],
                items=items,
                status=status,
                total_task_counts=task_counts,
            )

        if path == "/character/rarity_enhance":
            character_id = varint_field(request_plaintext, 1, 0)
            rarity_count = varint_field(request_plaintext, 3, 0)
            character = profile_resource_records(profile_plaintext, 2).get(character_id)
            if character is None:
                raise ValueError(f"profile has no character {character_id}")
            character_master = progression_master_index("character").get(character_id)
            if character_master is None:
                raise ValueError(f"progression master has no character {character_id}")
            current_rarity = varint_field(character, 11, int(character_master["initial_rarity"]))
            max_rarity = int(character_master["max_rarity"])
            if current_rarity + rarity_count > max_rarity:
                raise ValueError(
                    f"rarity enhancement exceeds character {character_id} maximum rarity {max_rarity}"
                )

            rarity_master = progression_master_index("character_common_rarity")
            piece_cost = 0
            item_costs: dict[int, int] = {}
            cole_cost = 0
            for rarity in range(current_rarity, current_rarity + rarity_count):
                rarity_data = rarity_master.get(rarity)
                if rarity_data is None:
                    raise ValueError(f"progression master has no character rarity {rarity}")
                piece_costs = rarity_data.get("rarity_enhance_piece_costs") or []
                if not piece_costs:
                    raise ValueError(f"rarity {rarity} has no enhancement piece cost")
                piece_cost += int(piece_costs[0])

                additional_costs = rarity_data.get("rarity_enhance_additional_costs") or []
                if additional_costs:
                    next_cost = additional_costs[0]
                    if next_cost.get("required"):
                        for cost in next_cost.get("costs") or []:
                            resource_type = int(cost["type"])
                            resource_id = int(cost["id"])
                            quantity = int(cost["quantity"])
                            if resource_type == 3 and resource_id == 1:
                                cole_cost += quantity
                            elif resource_type == 5:
                                item_costs[resource_id] = item_costs.get(resource_id, 0) + quantity
                            elif resource_type == 8 and resource_id == character_id:
                                piece_cost += quantity
                            else:
                                raise ValueError(
                                    f"unsupported character rarity resource cost type={resource_type} id={resource_id}"
                                )

            piece_record = profile_resource_records(profile_plaintext, 8).get(
                character_id,
                write_field(1, 0, character_id),
            )
            pieces = varint_field(piece_record, 2, 0)
            if pieces < piece_cost:
                raise ValueError(
                    f"character {character_id} pieces {pieces} are below requested cost {piece_cost}"
                )
            new_piece_record = replace_varint_field(piece_record, 2, pieces - piece_cost)
            item_records = profile_resource_records(profile_plaintext, 3)
            changed_items = updated_consumed_item_records(item_records, item_costs)
            status = None
            if cole_cost:
                status = message_field(resources, 6)
                if status is None:
                    raise ValueError("profile has no Status message for rarity enhancement cost")
                cole = varint_field(status, 3, 0)
                if cole < cole_cost:
                    raise ValueError(f"Cole quantity {cole} is below rarity enhancement cost {cole_cost}")
                status = replace_varint_field(status, 3, cole - cole_cost)

            new_rarity = current_rarity + rarity_count
            new_character = replace_varint_field(character, 11, new_rarity)
            if character_master.get("neo_growboard_id") is not None:
                new_rarity_data = rarity_master.get(new_rarity)
                if new_rarity_data is None:
                    raise ValueError(f"progression master has no character rarity {new_rarity}")
                new_character = replace_varint_field(
                    new_character,
                    37,
                    int(new_rarity_data.get("growboard_neo_max_page", 0)),
                )
            if self.character_records is not None:
                self.character_records[character_id] = new_character
            task_records = profile_resource_records(profile_plaintext, 32)
            task_counts = [updated_total_task_count_record(task_records, 90, rarity_count)]
            for condition_id, condition in progression_master_index("total_task_condition").items():
                transition = condition.get("transition") or {}
                if (
                    int(transition.get("transition") or 0) == 33
                    and int(transition.get("focused_on") or 0) == character_id
                ):
                    task_counts.append(
                        updated_total_task_count_record(
                            task_records,
                            condition_id,
                            rarity_count,
                        )
                    )
            self.log(
                f"LOCAL-CHARACTER-RARITY path={path} status=200 character_id={character_id} "
                f"rarity={current_rarity}->{current_rarity + rarity_count} pieces={piece_cost} "
                f"items={len(changed_items)} cole={cole_cost}"
            )
            return self.changed_resources_encrypted_response(
                response_key,
                response_iv,
                response_marker,
                characters=[new_character],
                character_pieces=[new_piece_record],
                items=changed_items,
                status=status,
                total_task_counts=task_counts,
            )

        if path == "/character/enhancement_reset":
            character_id = varint_field(request_plaintext, 1, 0)
            only_reset_level = bool(varint_field(request_plaintext, 2, 0))
            character = profile_resource_records(profile_plaintext, 2).get(character_id)
            if character is None:
                raise ValueError(f"profile has no character {character_id}")
            character_master = progression_master_index("character").get(character_id)
            if character_master is None:
                raise ValueError(f"progression master has no character {character_id}")

            refund_items: dict[int, int] = {}
            old_exp = varint_field(character, 12, 0)
            refunded_exp, exp_item_refund = experience_item_refund(
                old_exp,
                progression_master_index("item"),
            )
            for item_id, quantity in exp_item_refund.items():
                refund_items[item_id] = refund_items.get(item_id, 0) + quantity
            cole_refund = refunded_exp // 10

            new_character = replace_varint_field(character, 12, 0)
            changed_role_rates: list[bytes] = []
            task_records = profile_resource_records(profile_plaintext, 32)
            task_count_changes: dict[int, int] = {}
            if not only_reset_level:
                role = int(character_master["role"])
                role_rate_deltas: dict[int, int] = {}
                panel_master = progression_master_index("growboard_panel")
                board_master = progression_master_index("growboard")
                for board_type, is_ex, master_key in (
                    (1, False, "growboard_id"),
                    (1, True, "ex_growboard_id"),
                    (2, False, "neo_growboard_id"),
                ):
                    if not character_master.get(master_key):
                        continue
                    spec = growboard_spec_for_request(character_master, board_type, is_ex)
                    board = board_master.get(int(spec["master_id"]))
                    if board is None:
                        raise ValueError(f"progression master has no {spec['name']} growboard for {character_id}")
                    expected_board_type = 2 if spec["name"] == "neo" else 1
                    if (
                        int(board.get("board_type", 0)) != expected_board_type
                        or bool(board.get("is_ex")) != (spec["name"] == "ex")
                    ):
                        raise ValueError(f"invalid {spec['name']} growboard master data for {character_id}")
                    active_panel_ids = released_growboard_panel_ids(
                        character,
                        character_master,
                        board,
                        spec,
                    )
                    if spec["name"] == "normal":
                        task_count_changes[49] = task_count_changes.get(49, 0) - len(active_panel_ids)
                        current_page = varint_field(character, int(spec["page_field"]), 1) or 1
                        for page in range(2, current_page + 1):
                            condition_id = NORMAL_GROWBOARD_PAGE_TASKS.get(page)
                            if condition_id is not None:
                                task_count_changes[condition_id] = (
                                    task_count_changes.get(condition_id, 0) - 1
                                )
                    elif spec["name"] == "ex":
                        task_count_changes[100] = task_count_changes.get(100, 0) - len(active_panel_ids)
                    elif spec["name"] == "neo" and varint_field(character, 38, 0) > 0:
                        task_count_changes[1961] = task_count_changes.get(1961, 0) - 1
                    for panel_id in active_panel_ids:
                        panel = panel_master.get(panel_id)
                        if panel is None:
                            raise ValueError(f"progression master has no growboard panel {panel_id}")
                        cole_refund += int(panel.get("cole_cost", 0))
                        for item_cost in panel.get("item_costs") or []:
                            item_id = int(item_cost["id"])
                            refund_items[item_id] = refund_items.get(item_id, 0) + int(item_cost["quantity"])
                        if int(panel["type"]) == 2:
                            rate_fields = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}
                            status_type = int(panel.get("status_type") or 0)
                            rate_field = rate_fields.get(status_type)
                            if rate_field is None:
                                raise ValueError(f"unknown growboard role-rate type {status_type}")
                            role_rate_deltas[rate_field] = (
                                role_rate_deltas.get(rate_field, 0) + int(panel["value"])
                            )

                current_limit_increase = varint_field(character, 30, 0)
                limit_releases = progression_master_index("character_level_limit_release")
                cumulative_limit_increase = 0
                for release_id in sorted(limit_releases):
                    release = limit_releases[release_id]
                    if cumulative_limit_increase >= current_limit_increase:
                        break
                    cumulative_limit_increase += int(release["value"])
                    for item_cost in release.get("item_costs") or []:
                        item_id = int(item_cost["id"])
                        refund_items[item_id] = refund_items.get(item_id, 0) + int(item_cost["quantity"])
                if cumulative_limit_increase != current_limit_increase:
                    raise ValueError(
                        f"character {character_id} has an unsupported level-limit increase {current_limit_increase}"
                    )

                new_character = replace_varint_field(new_character, 8, 1)
                new_character = replace_varint_field(new_character, 9, 1)
                for field_number, value in (
                    (15, 1),
                    (16, 0),
                    (17, 1),
                    (18, 0),
                    (19, 0),
                    (20, 0),
                    (21, 0),
                    (22, 0),
                    (23, 0),
                    (24, 0),
                    (26, 0),
                    (27, 0),
                    (29, 10),
                    (30, 0),
                    (35, 1),
                    (36, 0),
                    (38, 0),
                    (39, 0),
                    (40, 0),
                ):
                    new_character = replace_varint_field(new_character, field_number, value)

                role_rate_records = profile_resource_records(profile_plaintext, 14)
                role_rate = role_rate_records.get(role)
                if role_rate_deltas:
                    if role_rate is None:
                        raise ValueError(f"profile has no growboard role-rate record for role {role}")
                    rate = message_field(role_rate, 2) or b""
                    for field_number, decrement in role_rate_deltas.items():
                        old_value = varint_field(rate, field_number, 0)
                        if old_value < decrement:
                            raise ValueError(
                                f"growboard role rate {role}.{field_number} {old_value} is below reset delta {decrement}"
                            )
                        rate = replace_varint_field(rate, field_number, old_value - decrement)
                    changed_role_rates.append(
                        replace_message_field_in_place(role_rate, 2, rate)
                    )

            item_records = profile_resource_records(profile_plaintext, 3)
            changed_items = updated_reward_item_records(item_records, refund_items)
            if only_reset_level:
                total_task_counts = character_level_task_updates(
                    task_records,
                    old_exp,
                    0,
                    include_max_level=True,
                )
            else:
                total_task_counts = character_level_task_updates(
                    task_records,
                    old_exp,
                    0,
                    include_max_level=False,
                )
                total_task_counts.extend(
                    updated
                    for condition_id, delta in task_count_changes.items()
                    if (updated := adjusted_total_task_count_record(task_records, condition_id, delta))
                    is not None
                )
            status = None
            if cole_refund:
                status = message_field(resources, 6)
                if status is None:
                    raise ValueError("profile has no Status message for character reset refund")
                status = replace_varint_field(
                    status,
                    3,
                    varint_field(status, 3, 0) + cole_refund,
                )

            rewards = []
            if cole_refund:
                rewards.append(resource_reward(3, cole_refund))
            rewards.extend(
                resource_reward(5, quantity, item_id)
                for item_id, quantity in sorted(refund_items.items())
                if quantity > 0
            )
            if self.character_records is not None:
                self.character_records[character_id] = new_character
            changed_plaintext = make_changed_resources_plaintext(
                characters=[new_character],
                items=changed_items,
                status=status,
                total_task_counts=total_task_counts,
                growboard_role_rates=changed_role_rates,
            )
            self.log(
                f"LOCAL-CHARACTER-RESET path={path} status=200 character_id={character_id} "
                f"only_reset_level={only_reset_level} refunded_exp={refunded_exp} "
                f"cole={cole_refund} items={len(changed_items)} role_rates={len(changed_role_rates)}"
            )
            return self.changed_resources_encrypted_response(
                response_key,
                response_iv,
                response_marker,
                characters=[new_character],
                items=changed_items,
                status=status,
                total_task_counts=total_task_counts,
                growboard_role_rates=changed_role_rates,
                extra_response_fields=[(2, 2, reward) for reward in rewards],
                persistence_plaintext=changed_plaintext,
            )

        if path == "/character/level_limit_release":
            character_id = varint_field(request_plaintext, 1, 0)
            character = profile_resource_records(profile_plaintext, 2).get(character_id)
            if character is None:
                raise ValueError(f"profile has no character {character_id}")
            current_increase = varint_field(character, 30, 0)
            release_records = progression_master_index("character_level_limit_release")
            next_release = None
            cumulative_increase = 0
            for release_id in sorted(release_records):
                release = release_records[release_id]
                if cumulative_increase == current_increase:
                    next_release = release
                    break
                cumulative_increase += int(release["value"])
            if next_release is None:
                raise ValueError(
                    f"character {character_id} has no level-limit release after increase {current_increase}"
                )
            item_costs: dict[int, int] = {}
            for cost in next_release.get("item_costs") or []:
                item_id = int(cost["id"])
                item_costs[item_id] = item_costs.get(item_id, 0) + int(cost["quantity"])
            changed_items = updated_consumed_item_records(
                profile_resource_records(profile_plaintext, 3),
                item_costs,
            )
            new_character = replace_varint_field(
                character,
                30,
                current_increase + int(next_release["value"]),
            )
            if self.character_records is not None:
                self.character_records[character_id] = new_character
            self.log(
                f"LOCAL-CHARACTER-LEVEL-LIMIT path={path} status=200 character_id={character_id} "
                f"increase={current_increase}->{current_increase + int(next_release['value'])} "
                f"items={len(changed_items)}"
            )
            return self.changed_resources_encrypted_response(
                response_key,
                response_iv,
                response_marker,
                characters=[new_character],
                items=changed_items,
            )

        if path in {"/character/growboard_page_release", "/character/growboard_bulk_release"}:
            character_id = varint_field(request_plaintext, 1, 0)
            character = profile_resource_records(profile_plaintext, 2).get(character_id)
            if character is None:
                raise ValueError(f"profile has no character {character_id}")
            character_master = progression_master_index("character").get(character_id)
            if character_master is None:
                raise ValueError(f"progression master has no character {character_id}")
            page_release = path.endswith("page_release")
            board_type_field = 3 if page_release else 5
            is_ex_field = 2 if page_release else 4
            board_type = nested_varint_field(request_plaintext, board_type_field, 1)
            if board_type is None:
                board_type = 1
            is_ex = bool(varint_field(request_plaintext, is_ex_field, 0))
            spec = growboard_spec_for_request(character_master, board_type, is_ex)
            growboard_id = int(spec["master_id"])
            growboard = progression_master_index("growboard").get(growboard_id)
            expected_board_type = 2 if spec["name"] == "neo" else 1
            expected_is_ex = spec["name"] == "ex"
            if (
                growboard is None
                or int(growboard.get("board_type", 0)) != expected_board_type
                or bool(growboard.get("is_ex")) != expected_is_ex
            ):
                raise ValueError(f"{spec['name']} growboard master data is missing for character {character_id}")
            page_ids = [int(value) for value in growboard.get("page_ids") or []]
            if not page_ids:
                raise ValueError(f"growboard {growboard_id} has no pages")
            available_pages = growboard_available_page_count(
                character,
                character_master,
                growboard,
                spec,
            )
            page_field = int(spec["page_field"])
            bits_field = int(spec["bits_field"])
            width = int(spec["width"])
            panel_mask = (1 << width) - 1
            task_records = profile_resource_records(profile_plaintext, 32)

            if page_release:
                current_page = varint_field(character, page_field, 1) or 1
                current_bits = varint_field(character, bits_field, 0)
                if current_page >= available_pages:
                    raise ValueError(f"character {character_id} has no next {spec['name']} growboard page")
                if current_bits != panel_mask:
                    raise ValueError(
                        f"all {width} panels on the current {spec['name']} growboard page must be released first"
                    )
                new_character = replace_varint_field(character, page_field, current_page + 1)
                new_character = replace_varint_field(new_character, bits_field, 0)
                task_counts = (
                    normal_growboard_page_task_updates(task_records, current_page, current_page + 1)
                    if spec["name"] == "normal"
                    else []
                )
                if self.character_records is not None:
                    self.character_records[character_id] = new_character
                self.log(
                    f"LOCAL-GROWBOARD-PAGE path={path} status=200 character_id={character_id} "
                    f"board={spec['name']} page={current_page}->{current_page + 1}"
                )
                return self.changed_resources_encrypted_response(
                    response_key,
                    response_iv,
                    response_marker,
                    characters=[new_character],
                    total_task_counts=task_counts,
                )

            target_page = varint_field(request_plaintext, 2, 0)
            requested_bits = varint_field(request_plaintext, 3, -1)
            current_page = varint_field(character, page_field, 1) or 1
            if target_page < current_page or target_page > available_pages:
                raise ValueError(
                    f"{spec['name']} growboard target page {target_page} is outside current/available pages "
                    f"{current_page}..{available_pages}"
                )
            if requested_bits < 0 or requested_bits > panel_mask:
                raise ValueError(f"invalid {spec['name']} growboard panel bits {requested_bits}")

            page_master = progression_master_index("growboard_page")
            panel_master = progression_master_index("growboard_panel")
            item_records = profile_resource_records(profile_plaintext, 3)
            role_records = profile_resource_records(profile_plaintext, 14)
            item_costs: dict[int, int] = {}
            cole_cost = 0
            released_panel_count = 0
            neo_unlocked = False
            changed_role_rates: dict[int, bytes] = {}
            character_record = character
            role = int(character_master["role"])

            def apply_panel_bits(bits: int) -> None:
                nonlocal character_record, cole_cost, released_panel_count, neo_unlocked
                page_number = varint_field(character_record, page_field, 1) or 1
                page_id = page_ids[page_number - 1]
                page_data = page_master.get(page_id)
                if page_data is None:
                    raise ValueError(f"growboard page master data is missing: {page_id}")
                panel_ids = [int(value) for value in page_data.get("panel_ids") or []]
                if len(panel_ids) != width:
                    raise ValueError(f"growboard page {page_id} does not contain {width} panels")
                old_bits = varint_field(character_record, bits_field, 0)
                new_bits = bits & ~old_bits
                for position, panel_id in enumerate(panel_ids):
                    if not new_bits & (1 << position):
                        continue
                    panel = panel_master.get(panel_id)
                    if panel is None:
                        raise ValueError(f"growboard panel master data is missing: {panel_id}")
                    cole_cost += int(panel.get("cole_cost", 0))
                    for item_cost in panel.get("item_costs") or []:
                        item_id = int(item_cost["id"])
                        item_costs[item_id] = item_costs.get(item_id, 0) + int(item_cost["quantity"])

                    panel_type = int(panel["type"])
                    value = int(panel["value"])
                    if panel_type == 1:
                        stat_fields = {1: 19, 2: 20, 3: 21, 4: 22, 5: 23, 6: 24}
                        status_type = int(panel.get("status_type") or 0)
                        target_field = stat_fields.get(status_type)
                        if target_field is None:
                            raise ValueError(f"unknown growboard stat type {status_type}")
                        character_record = replace_varint_field(
                            character_record,
                            target_field,
                            varint_field(character_record, target_field, 0) + value,
                        )
                    elif panel_type == 2:
                        status_type = int(panel.get("status_type") or 0)
                        rate_fields = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}
                        target_field = rate_fields.get(status_type)
                        if target_field is None:
                            raise ValueError(f"unknown growboard role-rate type {status_type}")
                        rate_record = changed_role_rates.get(
                            role,
                            role_records.get(role, write_field(1, 0, role)),
                        )
                        rate = message_field(rate_record, 2) or b""
                        rate = replace_varint_field(
                            rate,
                            target_field,
                            varint_field(rate, target_field, 0) + value,
                        )
                        changed_role_rates[role] = replace_message_field_in_place(
                            rate_record,
                            2,
                            rate,
                        )
                    elif panel_type == 3:
                        target_field = 26
                        character_record = replace_varint_field(
                            character_record,
                            target_field,
                            varint_field(character_record, target_field, 0) + value,
                        )
                    elif panel_type == 4:
                        target_field = 8
                        character_record = replace_varint_field(
                            character_record,
                            target_field,
                            varint_field(character_record, target_field, 0) + value,
                        )
                    elif panel_type == 5:
                        target_field = 9
                        character_record = replace_varint_field(
                            character_record,
                            target_field,
                            varint_field(character_record, target_field, 0) + value,
                        )
                    elif panel_type == 6:
                        target_field = 27
                        character_record = replace_varint_field(
                            character_record,
                            target_field,
                            varint_field(character_record, target_field, 0) + value,
                        )
                    elif panel_type == 7:
                        target_field = 29
                        character_record = replace_varint_field(
                            character_record,
                            target_field,
                            varint_field(character_record, target_field, 10) + value,
                        )
                    elif panel_type == 8 and spec["name"] == "neo":
                        target_field = 38
                        old_rank = varint_field(character_record, target_field, 0)
                        character_record = replace_varint_field(
                            character_record,
                            target_field,
                            old_rank + value,
                        )
                        if old_rank == 0 and value > 0:
                            neo_unlocked = True
                    else:
                        raise ValueError(f"unknown growboard panel type {panel_type}")
                    released_panel_count += 1
                character_record = replace_varint_field(character_record, bits_field, bits)

            while varint_field(character_record, page_field, 1) < target_page:
                apply_panel_bits(panel_mask)
                character_record = replace_varint_field(
                    character_record,
                    page_field,
                    varint_field(character_record, page_field, 1) + 1,
                )
                character_record = replace_varint_field(character_record, bits_field, 0)
            apply_panel_bits(requested_bits)

            changed_items = updated_consumed_item_records(item_records, item_costs)
            status = None
            if cole_cost:
                status = message_field(resources, 6)
                if status is None:
                    raise ValueError("profile has no Status message for growboard Cole cost")
                cole = varint_field(status, 3, 0)
                if cole < cole_cost:
                    raise ValueError(f"Cole quantity {cole} is below growboard cost {cole_cost}")
                status = replace_varint_field(status, 3, cole - cole_cost)
            task_counts = []
            if released_panel_count and spec["panel_task"] is not None:
                task_counts.append(
                    updated_total_task_count_record(
                        task_records,
                        int(spec["panel_task"]),
                        released_panel_count,
                    )
                )
            if spec["name"] == "neo":
                if neo_unlocked:
                    task_counts.append(updated_total_task_count_record(task_records, 1961))
                elif 1961 in task_records:
                    task_counts.append(task_records[1961])
            if spec["name"] == "normal":
                task_counts.extend(
                    normal_growboard_page_task_updates(task_records, current_page, target_page)
                )
            role_rate_response = changed_role_rates.get(role, role_records.get(role))
            if role_rate_response is not None and role not in changed_role_rates:
                changed_role_rates[role] = role_rate_response
            if self.character_records is not None:
                self.character_records[character_id] = character_record
            self.log(
                f"LOCAL-GROWBOARD-BULK path={path} status=200 character_id={character_id} "
                f"board={spec['name']} page={target_page} panel_bits={requested_bits} panels={released_panel_count} "
                f"cole={cole_cost} items={len(changed_items)} role_rates={len(changed_role_rates)}"
            )
            return self.changed_resources_encrypted_response(
                response_key,
                response_iv,
                response_marker,
                characters=[character_record],
                items=changed_items,
                status=status,
                total_task_counts=task_counts,
                growboard_role_rates=list(changed_role_rates.values()),
            )

        memoria_records = profile_resource_records(profile_plaintext, 29)
        target_entity_id = varint_field(request_plaintext, 1, 0)
        target_memoria = memoria_records.get(target_entity_id)
        if path != "/memoria/sell" and target_memoria is None:
            raise ValueError(f"profile has no Memoria entity {target_entity_id}")

        if path == "/memoria/lock":
            is_locked = varint_field(request_plaintext, 2, 0)
            new_memoria = replace_varint_field(target_memoria, 6, is_locked)
            self.log(
                f"LOCAL-MEMORIA-LOCK path={path} status=200 entity_id={target_entity_id} locked={is_locked}"
            )
            return self.changed_resources_encrypted_response(
                response_key,
                response_iv,
                response_marker,
                memorias=[new_memoria],
            )

        if path == "/memoria/enhance":
            consumed_ids = varint_values(request_plaintext, 3)
            if len(consumed_ids) != len(set(consumed_ids)) or target_entity_id in consumed_ids:
                raise ValueError("Memoria enhancement cannot consume the target or duplicate entities")
            item_records = profile_resource_records(profile_plaintext, 3)
            consumed_items = consumed_item_quantities(request_plaintext)
            changed_items = updated_consumed_item_records(item_records, consumed_items)
            item_master = progression_master_index("item")
            memoria_master = progression_master_index("memoria")
            rarity_master = progression_master_index("memoria_rarity")
            gained_exp = 0
            for item_id, quantity in consumed_items.items():
                item_data = item_master.get(item_id)
                if item_data is None:
                    raise ValueError(f"progression master has no item {item_id}")
                gained_exp += int(item_data.get("value", 0)) * quantity

            deleted_ids = []
            for entity_id in consumed_ids:
                consumed_memoria = memoria_records.get(entity_id)
                if consumed_memoria is None:
                    raise ValueError(f"profile has no consumed Memoria entity {entity_id}")
                if varint_field(consumed_memoria, 6, 0):
                    raise ValueError(f"consumed Memoria entity {entity_id} is locked")
                memoria_data = memoria_master.get(varint_field(consumed_memoria, 2, 0))
                if memoria_data is None:
                    raise ValueError(f"progression master has no consumed Memoria {entity_id}")
                rarity_data = rarity_master.get(int(memoria_data["rarity"]))
                if rarity_data is None:
                    raise ValueError(f"progression master has no Memoria rarity {memoria_data['rarity']}")
                gained_exp += varint_field(consumed_memoria, 4, 0) + int(rarity_data["exp"])
                deleted_ids.append(entity_id)

            new_memoria = replace_varint_field(
                target_memoria,
                4,
                varint_field(target_memoria, 4, 0) + gained_exp,
            )
            status = message_field(resources, 6)
            if status is None:
                raise ValueError("profile has no Status message for Memoria enhancement")
            status = replace_varint_field(
                status,
                3,
                varint_field(status, 3, 0) - gained_exp,
            )
            deleted_resources = b"".join(write_field(3, 0, entity_id) for entity_id in deleted_ids)
            task_counts = []
            if gained_exp > 0:
                task_counts.append(
                    updated_total_task_count_record(
                        profile_resource_records(profile_plaintext, 32),
                        105,
                    )
                )
            self.log(
                f"LOCAL-MEMORIA-ENHANCE path={path} status=200 entity_id={target_entity_id} "
                f"gained_exp={gained_exp} consumed_items={len(changed_items)} consumed_memorias={len(deleted_ids)}"
            )
            return self.changed_resources_encrypted_response(
                response_key,
                response_iv,
                response_marker,
                memorias=[new_memoria],
                items=changed_items,
                status=status,
                total_task_counts=task_counts,
                deleted_resources=deleted_resources,
            )

        if path == "/memoria/limit_break":
            consumed_ids = varint_values(request_plaintext, 3)
            if consumed_item_quantities(request_plaintext):
                raise ValueError("Memoria limit break with consumed items is not supported by the reference handler")
            if not consumed_ids or len(consumed_ids) != len(set(consumed_ids)) or target_entity_id in consumed_ids:
                raise ValueError("Memoria limit break requires unique consumed entities other than the target")
            memoria_master = progression_master_index("memoria")
            rarity_master = progression_master_index("memoria_rarity")
            target_data = memoria_master.get(varint_field(target_memoria, 2, 0))
            if target_data is None:
                raise ValueError(f"progression master has no target Memoria {target_entity_id}")
            target_rarity_data = rarity_master.get(int(target_data["rarity"]))
            if target_rarity_data is None:
                raise ValueError(f"progression master has no Memoria rarity {target_data['rarity']}")
            current_limit_break = varint_field(target_memoria, 3, 0)
            if current_limit_break + len(consumed_ids) > int(target_rarity_data["max_limit_break"]):
                raise ValueError(f"Memoria entity {target_entity_id} exceeds its limit-break maximum")
            for entity_id in consumed_ids:
                consumed_memoria = memoria_records.get(entity_id)
                if consumed_memoria is None:
                    raise ValueError(f"profile has no consumed Memoria entity {entity_id}")
                if varint_field(consumed_memoria, 6, 0):
                    raise ValueError(f"consumed Memoria entity {entity_id} is locked")
            new_memoria = replace_varint_field(
                target_memoria,
                3,
                current_limit_break + len(consumed_ids),
            )
            deleted_resources = b"".join(write_field(3, 0, entity_id) for entity_id in consumed_ids)
            task_count = updated_total_task_count_record(
                profile_resource_records(profile_plaintext, 32),
                105,
                len(consumed_ids),
            )
            self.log(
                f"LOCAL-MEMORIA-LIMIT-BREAK path={path} status=200 entity_id={target_entity_id} "
                f"limit_break={current_limit_break}->{current_limit_break + len(consumed_ids)} "
                f"consumed_memorias={len(consumed_ids)}"
            )
            return self.changed_resources_encrypted_response(
                response_key,
                response_iv,
                response_marker,
                memorias=[new_memoria],
                total_task_counts=[task_count],
                deleted_resources=deleted_resources,
            )

        if path == "/memoria/sell":
            entity_ids = varint_values(request_plaintext, 1)
            if len(entity_ids) != len(set(entity_ids)):
                raise ValueError("Memoria sell request contains duplicate entity IDs")
            memoria_master = progression_master_index("memoria")
            rarity_master = progression_master_index("memoria_rarity")
            cole_gained = 0
            for entity_id in entity_ids:
                memoria = memoria_records.get(entity_id)
                if memoria is None:
                    raise ValueError(f"profile has no Memoria entity {entity_id}")
                if varint_field(memoria, 6, 0):
                    raise ValueError(f"Memoria entity {entity_id} is locked")
                memoria_data = memoria_master.get(varint_field(memoria, 2, 0))
                if memoria_data is None:
                    raise ValueError(f"progression master has no Memoria entity type {entity_id}")
                rarity_data = rarity_master.get(int(memoria_data["rarity"]))
                if rarity_data is None:
                    raise ValueError(f"progression master has no Memoria rarity {memoria_data['rarity']}")
                cole_gained += int(rarity_data["sold_cole"]) * (varint_field(memoria, 3, 0) + 1)
            status = message_field(resources, 6)
            if status is None:
                raise ValueError("profile has no Status message for Memoria sale")
            status = replace_varint_field(
                status,
                3,
                varint_field(status, 3, 0) + cole_gained,
            )
            deleted_resources = b"".join(write_field(3, 0, entity_id) for entity_id in entity_ids)
            reward = b"".join(
                (
                    write_field(1, 0, 3),
                    write_field(2, 0, 1),
                    write_field(3, 0, cole_gained),
                )
            )
            self.log(
                f"LOCAL-MEMORIA-SELL path={path} status=200 entities={len(entity_ids)} cole={cole_gained}"
            )
            return self.changed_resources_encrypted_response(
                response_key,
                response_iv,
                response_marker,
                status=status,
                deleted_resources=deleted_resources,
                extra_response_fields=[(3, 2, reward)],
            )

        raise ValueError(f"unsupported progression endpoint: {path}")

    def changed_resources_encrypted_response(
        self,
        response_key: bytes,
        response_iv: bytes,
        response_marker: int,
        profile: bytes | None = None,
        characters: list[bytes] | None = None,
        parties: list[bytes] | None = None,
        party_members: list[bytes] | None = None,
        equipment_tools: list[bytes] | None = None,
        equipment_presets: list[bytes] | None = None,
        battle_tools: list[bytes] | None = None,
        ships: list[bytes] | None = None,
        ship_parties: list[bytes] | None = None,
        ship_tools: list[bytes] | None = None,
        chara_homes: list[bytes] | None = None,
        items: list[bytes] | None = None,
        character_pieces: list[bytes] | None = None,
        memorias: list[bytes] | None = None,
        status: bytes | None = None,
        total_task_counts: list[bytes] | None = None,
        growboard_role_rates: list[bytes] | None = None,
        deleted_resources: bytes | None = None,
        extra_response_fields: list[tuple[int, int, object]] | None = None,
        persistence_plaintext: bytes | None = None,
    ) -> bytes:
        plaintext = make_changed_resources_plaintext(
            profile=profile,
            characters=characters,
            items=items,
            character_pieces=character_pieces,
            memorias=memorias,
            status=status,
            total_task_counts=total_task_counts,
            parties=parties,
            party_members=party_members,
            equipment_tools=equipment_tools,
            battle_tools=battle_tools,
            ships=ships,
            ship_parties=ship_parties,
            ship_tools=ship_tools,
            growboard_role_rates=growboard_role_rates,
            equipment_presets=equipment_presets,
            chara_homes=chara_homes,
            deleted_resources=deleted_resources,
            extra_response_fields=extra_response_fields,
        )
        self.persist_profile_update(
            plaintext if persistence_plaintext is None else persistence_plaintext,
            "generated_changed_resources",
        )
        return bytes([response_marker]) + aes_encrypt(
            pkcs7_pad(gzip.compress(plaintext, mtime=0)),
            response_key,
            response_iv,
        )

    def expedition_reward_response(self, record: Record) -> bytes:
        if not self.expedition_special_reward_ids:
            return record.response_body
        index = self.expedition_special_reward_index
        reward_item_id = self.expedition_special_reward_ids[index % len(self.expedition_special_reward_ids)]
        self.expedition_special_reward_index += 1
        response = make_expedition_special_reward_response(record.response_body, reward_item_id)
        marker_path = GAME_DIR / "offline-expedition-timeline-request.txt"
        temporary_marker_path = marker_path.with_name(marker_path.name + ".tmp")
        try:
            temporary_marker_path.write_text(str(index), encoding="ascii")
            temporary_marker_path.replace(marker_path)
        except OSError as error:
            self.log(f"EXPEDITION-TIMELINE-MARKER-FAILED reason={type(error).__name__}:{error}")
        self.log(
            f"LOCAL-EXPEDITION-REWARD path={EXPEDITION_REWARD_PATH} "
            f"rotation_index={index} special_reward_item_id={reward_item_id}"
        )
        return response

    def ensure_home_state(self) -> None:
        if self.home_state_loaded:
            return
        self.home_state_loaded = True
        try:
            (
                self.home_profile,
                self.home_records,
                self.home_favorite_character_ids,
            ) = load_home_profile_state(GAME_DIR / "profile.bin")
            profile_fields = read_wire_fields(self.home_profile)
            if any(number == 11 and wire_type == 2 for number, wire_type, _ in profile_fields):
                self.last_selected_home_field = 11
            elif any(number == 10 and wire_type == 2 for number, wire_type, _ in profile_fields):
                self.last_selected_home_field = 10
        except (OSError, RuntimeError, ValueError, StopIteration) as error:
            self.log(f"HOME-STATE-LOAD-FAILED reason={type(error).__name__}:{error}")

    def exploration_template(self, quest_id: int, party_number: int) -> tuple[bytes, bytes] | None:
        cache_key = (quest_id, party_number)
        if cache_key in self.exploration_templates:
            return self.exploration_templates[cache_key]

        sessions = sorted(
            (
                session
                for root in capture_roots()
                for session in root.glob("session-*")
                if session.is_dir()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        fallback: tuple[bytes, bytes] | None = None
        for session in sessions:
            for metadata_path in sorted(session.glob("[0-9][0-9][0-9][0-9].txt"), reverse=True):
                try:
                    record = parse_record(metadata_path)
                except (OSError, ValueError, KeyError):
                    continue
                if record.path != "/exploration/start" or not record.response_body:
                    continue
                try:
                    request_plaintext, _, _, _ = decrypt_request_with_response_material(
                        record.request_body,
                        is_exploration_start_request,
                        record.path,
                    )
                    request_values = {
                        number: int(value)
                        for number, wire_type, value in read_wire_fields(request_plaintext)
                        if wire_type == 0
                    }
                    _, response_plaintext, _, _ = decrypt_api_response(record.response_body)
                    template = exploration_progress_from_response(response_plaintext)
                    if template is None:
                        continue
                    template_progress, party_status = template
                    template_key = (request_values.get(1, 0), request_values.get(2, 0))
                    if template_key not in self.exploration_templates:
                        self.exploration_templates[template_key] = (template_progress, party_status)
                    if fallback is None:
                        fallback = (template_progress, party_status)
                except (OSError, RuntimeError, ValueError, StopIteration):
                    continue

        self.exploration_fallback_template = fallback
        return self.exploration_templates.get(cache_key, fallback)

    def exploration_start_response(self, flow: http.HTTPFlow) -> bytes:
        request_body = flow.request.raw_content or b""
        request_plaintext, response_key, response_iv, response_marker = decrypt_request_with_response_material(
            request_body,
            is_exploration_start_request,
            "/exploration/start",
        )
        values = {
            number: int(value)
            for number, wire_type, value in read_wire_fields(request_plaintext)
            if wire_type == 0
        }
        quest_id = values[1]
        party_number = values[2]
        control_character_id = next(
            (
                bytes(value)
                for number, wire_type, value in read_wire_fields(request_plaintext)
                if number == 7 and wire_type == 2
            ),
            None,
        )
        route_data = exploration_routes(quest_id)
        template = self.exploration_template(quest_id, party_number)
        template_exact = (quest_id, party_number) in self.exploration_templates
        template_progress, party_status = template or (b"", b"")
        if not route_data and template_exact and template_progress:
            template_area_id = next(
                (
                    int(value)
                    for number, wire_type, value in read_wire_fields(template_progress)
                    if number == 2 and wire_type == 0
                ),
                quest_id * 10 + 1,
            )
            template_route_type = next(
                (
                    {
                        0: "gathering",
                        1: "battle",
                        2: "talk",
                    }.get(int(value), "gathering")
                    for number, wire_type, value in read_wire_fields(template_progress)
                    if number == 3 and wire_type == 0
                ),
                "gathering",
            )
            route_data = [
                {
                    "area_id": template_area_id,
                    "number": 0,
                    "route_type": template_route_type,
                }
            ]
        if not party_status:
            party_status = default_exploration_party_status()
        progress, area_id = make_exploration_progress(
            quest_id,
            party_number,
            route_data,
            party_status,
            control_character_id,
        )
        self.log(
            f"LOCAL-EXPLORATION-START host={flow.request.host} method=POST "
            f"path=/exploration/start status=200 quest_id={quest_id} party_number={party_number} "
            f"area_id={area_id} route_count={len(route_data)} template={template_exact}"
        )
        response_plaintext = make_exploration_start_response(progress)
        self.persist_profile_update(response_plaintext, "/exploration/start")
        return bytes([response_marker]) + aes_encrypt(
            pkcs7_pad(gzip.compress(response_plaintext, mtime=0)),
            response_key,
            response_iv,
        )

    def exploration_finish_response(self, flow: http.HTTPFlow) -> bytes:
        request_body = flow.request.raw_content or b""
        request_plaintext, response_key, response_iv, response_marker = decrypt_request_with_response_material(
            request_body,
            is_exploration_finish_request,
            "/exploration/finish",
        )
        quest_id = next(
            int(value)
            for number, wire_type, value in read_wire_fields(request_plaintext)
            if number == 1 and wire_type == 0
        )
        self.log(
            f"LOCAL-EXPLORATION-FINISH host={flow.request.host} method=POST "
            f"path=/exploration/finish status=200 quest_id={quest_id} changed_resources=empty"
        )
        return bytes([response_marker]) + aes_encrypt(
            pkcs7_pad(gzip.compress(make_exploration_finish_response(), mtime=0)),
            response_key,
            response_iv,
        )

    def home_response(self, flow: http.HTTPFlow) -> bytes:
        self.ensure_home_state()
        path = urlsplit(flow.request.pretty_url).path
        request_body = flow.request.raw_content or b""
        response_key, response_iv, response_marker = response_material()

        if path == "/chara_home/register":
            plaintext, response_key, response_iv, response_marker = decrypt_request_with_response_material(
                request_body,
                is_home_register_request,
                path,
            )
            values = {
                number: int(value)
                for number, wire_type, value in read_wire_fields(plaintext)
                if wire_type == 0
            }
            slot_id = values[1]
            chara_home = b"".join(
                (
                    write_field(1, 0, slot_id),
                    write_field(2, 0, values[2]),
                    write_field(3, 0, values.get(6, 0)),
                    write_field(4, 0, values.get(3, 0)),
                    write_field(5, 0, values.get(4, 0)),
                    write_field(6, 0, values.get(5, 0)),
                )
            )
            self.home_records[slot_id] = chara_home
            self.log(
                f"LOCAL-HOME host={flow.request.host} method=POST path={path} status=200 "
                f"slot_id={slot_id} character_id={values[2]} background_id={values.get(6, 0)} "
                f"motion_id={values.get(3, 0)} camera_id={values.get(4, 0)} bgm_id={values.get(5, 0)}"
            )
            return self.changed_resources_encrypted_response(
                chara_homes=list(self.home_records.values()),
                response_key=response_key,
                response_iv=response_iv,
                response_marker=response_marker,
            )

        if path == "/profile/update_chara_home_favorite_character_list":
            plaintext, response_key, response_iv, response_marker = decrypt_request_with_response_material(
                request_body,
                is_favorite_request,
                path,
            )
            character_id = varint_field(plaintext, 1)
            if character_id in self.home_favorite_character_ids:
                self.home_favorite_character_ids.remove(character_id)
            else:
                self.home_favorite_character_ids.append(character_id)
            self.home_profile = replace_repeated_varint_field(
                self.home_profile,
                12,
                self.home_favorite_character_ids,
            )
            self.log(
                f"LOCAL-HOME-FAVORITE host={flow.request.host} method=POST path={path} status=200 "
                f"character_id={character_id} favorited={character_id in self.home_favorite_character_ids}"
            )
            return self.changed_resources_encrypted_response(
                profile=self.home_profile,
                response_key=response_key,
                response_iv=response_iv,
                response_marker=response_marker,
            )

        if path == "/profile/update_selected_home_id":
            if request_body:
                plaintext, response_key, response_iv, response_marker = decrypt_request_with_response_material(
                    request_body,
                    is_selected_home_request,
                    path,
                )
                selected_field = 10 if nested_varint_field(plaintext, 1, 1) is not None else 11
                selected_home_id = nested_varint_field(plaintext, 1, 1)
                if selected_home_id is None:
                    selected_home_id = nested_varint_field(plaintext, 2, 1)
                if selected_home_id is not None:
                    self.last_selected_home_field = selected_field
                    self.home_profile = replace_message_field(
                        self.home_profile,
                        selected_field,
                        write_field(1, 0, selected_home_id),
                    )
                    self.home_profile = replace_message_field(
                        self.home_profile,
                        11 if selected_field == 10 else 10,
                        None,
                    )
                    self.log(
                        f"LOCAL-HOME-SELECT host={flow.request.host} method=POST path={path} status=200 "
                        f"home_id={selected_home_id} profile_field={selected_field}"
                    )
            else:
                self.home_profile = replace_message_field(
                    self.home_profile,
                    10,
                    None,
                )
                self.home_profile = replace_message_field(
                    self.home_profile,
                    11,
                    None,
                )
                self.log(
                    f"LOCAL-HOME-SELECT host={flow.request.host} method=POST path={path} status=200 "
                    "selection=default cleared_profile_fields=10,11"
                )
            if not request_body:
                response_key, response_iv, response_marker = response_material()
            return self.changed_resources_encrypted_response(
                profile=self.home_profile,
                response_key=response_key,
                response_iv=response_iv,
                response_marker=response_marker,
            )

        raise ValueError(f"unsupported home endpoint: {path}")

    def auth_response(self, response_body: bytes) -> bytes:
        override_path = GAME_DIR / "profile-anonymization.json"
        if not override_path.exists():
            return response_body
        try:
            override = json.loads(override_path.read_text(encoding="utf-8"))
            player_id = int(override["player_id"])
            if not 0 <= player_id <= 9_223_372_036_854_775_807:
                raise ValueError("player ID is outside the signed 64-bit range")
            marker, plaintext, key, iv = decrypt_api_response(response_body)
            patched = replace_varint_field(plaintext, 3, player_id)
            session_token = override.get("session_token")
            if session_token is not None:
                if not isinstance(session_token, str) or not session_token:
                    raise ValueError("session token override must be a non-empty string")
                patched = replace_message_field(patched, 1, session_token.encode("utf-8"))
            display_id = override.get("player_id_text", str(player_id))
            self.log(
                f"AUTH-ID-OVERRIDE player_id={display_id} wire_value={player_id} "
                f"session_token_overridden={session_token is not None}"
            )
            return encrypt_api_response(marker, patched, key, iv)
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
            self.log(f"AUTH-ID-OVERRIDE-FAILED reason={type(error).__name__}:{error}")
            return response_body

    def default_response(self, flow: http.HTTPFlow) -> bool:
        path = urlsplit(flow.request.pretty_url).path
        timestamp = str(int(time.time()))
        if path == "/status":
            flow.response = http.Response.make(
                200,
                b'{"terms_of_service_version":"2026_08_27","gdpr_privacy_policy_version":"","title":{"timeline_asset_path_hash":"4783682884224829538","id":2,"bgm_path_hash":"7852695906499225647"},"device_auth":"enabled"}\n',
                {"Content-Type": "application/json; charset=utf-8"},
            )
            self.log("DEFAULT path=/status status=200")
            return True
        if path == "/refund_info/get_country_code":
            flow.response = http.Response.make(
                200,
                b"",
                {"Content-Type": "application/octet-stream", "x-server-timestamp": timestamp},
            )
            self.log("DEFAULT path=/refund_info/get_country_code status=200")
            return True
        if path == "/auth/sign_in":
            flow.response = http.Response.make(
                200,
                default_auth_response(flow.request.raw_content or b""),
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": timestamp,
                },
            )
            self.log("DEFAULT path=/auth/sign_in status=200")
            return True
        if path == "/user/log_in":
            profile_path = GAME_DIR / "profile.bin"
            if not profile_path.is_file():
                return False
            asset_version = flow.request.headers.get("x-asset-version", "").strip()
            master_data_version = flow.request.headers.get("x-master-data-version", "").strip()
            self.default_login_attempts += 1
            if self.default_login_attempts == 1 or not asset_version:
                response_body = json.dumps(
                    {
                        "code": "requires_assets_updates",
                        "master_data_version": master_data_version or DEFAULT_MASTER_DATA_VERSION,
                        "asset_version": DEFAULT_ASSET_VERSION,
                    },
                    separators=(",", ":"),
                ).encode("utf-8") + b"\n"
                flow.response = http.Response.make(
                    409,
                    response_body,
                    {"Content-Type": "application/json; charset=utf-8"},
                )
                self.log("DEFAULT path=/user/log_in status=409 code=requires_assets_updates")
                return True
            response_body, reencrypted = default_profile_response(profile_path)
            flow.response = http.Response.make(
                200,
                response_body,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": timestamp,
                },
            )
            self.log(
                f"DEFAULT PROFILE path={profile_path} bytes={len(response_body)} "
                f"reencrypted={reencrypted}"
            )
            return True
        if path == "/web_session/token":
            flow.response = http.Response.make(
                200,
                default_web_session_token_response(),
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": timestamp,
                },
            )
            self.log("DEFAULT path=/web_session/token status=200 token=synthetic")
            return True
        if path in {
            "/login_bonus/receive",
            "/external_purchase/receive",
            EXPEDITION_REWARD_PATH,
        }:
            response_body = (
                default_login_bonus_response()
                if path == "/login_bonus/receive"
                else default_encrypted_empty_response(gzip_body=path != "/external_purchase/receive")
            )
            headers = {
                "Content-Type": "application/octet-stream",
                "x-server-timestamp": timestamp,
            }
            if path != "/external_purchase/receive":
                headers["X-Content-Encoding"] = "gzip"
            flow.response = http.Response.make(200, response_body, headers)
            self.log(f"DEFAULT path={path} status=200")
            return True
        return False

    def recorded_response(self, flow: http.HTTPFlow, record: Record) -> None:
        response_body = record.response_body
        if record.path == "/auth/sign_in" and record.status == 200 and not HYBRID_MODE:
            response_body = self.auth_response(response_body)
        if record.path == "/user/log_in" and record.status == 200:
            profile_path = GAME_DIR / "profile.bin"
            if profile_path.exists():
                response_body = profile_path.read_bytes()
                self.log(f"PROFILE path={profile_path} bytes={len(response_body)} direct=True")
        is_json = response_body.startswith((b"{", b"["))
        headers = {
            "Content-Type": "application/json; charset=utf-8"
            if is_json
            else "application/octet-stream",
            "x-server-timestamp": str(int(time.time())),
        }
        if not is_json and record.path != "/external_purchase/receive":
            headers["X-Content-Encoding"] = "gzip"
        flow.response = http.Response.make(record.status, response_body, headers)

    def respond(self, flow: http.HTTPFlow) -> None:
        path = urlsplit(flow.request.pretty_url).path
        method = flow.request.method.upper()
        if HYBRID_MODE and method == "POST" and path == "/auth/sign_in":
            self.hybrid_logged_in = False
        if REPLAY_MODE:
            record = self.choose(flow)
            if record is not None:
                self.recorded_response(flow, record)
                return
        if HYBRID_MODE and (
            not self.hybrid_logged_in
            or path in {"/status", "/refund_info/get_country_code", "/auth/sign_in"}
            or path in HYBRID_INIT_PATHS
        ) and path in HYBRID_HANDSHAKE_PATHS | HYBRID_INIT_PATHS:
            record = self.choose(flow)
            if record is not None:
                self.recorded_response(flow, record)
                if path == "/user/log_in" and record.status == 200:
                    self.hybrid_logged_in = True
                    self.log("HYBRID login handshake complete; switching to generated responses")
                return
        if method == "POST" and path == "/illustrated_book/start":
            try:
                response_body = make_illustrated_book_response(
                    GAME_DIR / "profile.bin",
                    flow.request.raw_content or b"",
                )
                flow.response = http.Response.make(
                    200,
                    response_body,
                    {
                        "Content-Type": "application/octet-stream",
                        "X-Content-Encoding": "gzip",
                        "x-server-timestamp": str(int(time.time())),
                    },
                )
                self.log(f"LOCAL-ILLUSTRATED-BOOK path={path} status=200")
            except (OSError, RuntimeError, ValueError, StopIteration) as error:
                self.log(f"ILLUSTRATED-BOOK-FAILED path={path} reason={type(error).__name__}:{error}")
                flow.response = http.Response.make(
                    503,
                    b"",
                    {"Content-Type": "application/octet-stream"},
                )
            return
        if method == "POST" and path == "/recipe/learn":
            self.log(f"LOCAL host={flow.request.host} method={method} path={path} status=200 body={len(flow.request.raw_content or b'')}")
            flow.response = http.Response.make(
                200,
                OFFLINE_RECIPE_LEARN_RESPONSE,
                {
                    "Content-Type": "application/octet-stream",
                    "x-server-timestamp": str(int(time.time())),
                },
            )
            return
        if method == "POST" and path == "/exploration/start":
            try:
                response_body = self.exploration_start_response(flow)
            except (OSError, RuntimeError, ValueError, StopIteration) as error:
                self.log(f"EXPLORATION-START-FAILED path={path} reason={type(error).__name__}:{error}")
                flow.response = http.Response.make(
                    503,
                    b"",
                    {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))},
                )
                return
            flow.response = http.Response.make(
                200,
                response_body,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": str(int(time.time())),
                },
            )
            return
        if method == "POST" and path == "/exploration/finish":
            try:
                response_body = self.exploration_finish_response(flow)
            except (OSError, RuntimeError, ValueError, StopIteration) as error:
                self.log(f"EXPLORATION-FINISH-FAILED path={path} reason={type(error).__name__}:{error}")
                flow.response = http.Response.make(
                    503,
                    b"",
                    {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))},
                )
                return
            flow.response = http.Response.make(
                200,
                response_body,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": str(int(time.time())),
                },
            )
            return
        if method == "POST" and path == "/character/skin_set":
            try:
                response_body = self.skin_response(flow)
            except (OSError, RuntimeError, ValueError, StopIteration):
                flow.response = http.Response.make(
                    503,
                    b"",
                    {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))},
                )
                return
            flow.response = http.Response.make(
                200,
                response_body,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": str(int(time.time())),
                },
            )
            return
        if method == "POST" and path in {
            "/party/bulk_update",
            "/party/battle_tools_set",
            "/character/equip",
            "/character/memoria_set",
            "/character/bulk_set",
            "/equipment_preset/bulk_set",
            "/equipment_preset/equip",
            "/equipment_preset/memoria_set",
            "/equipment_preset/update_name",
        }:
            try:
                response_body = self.party_response(flow)
            except (OSError, RuntimeError, ValueError, StopIteration, KeyError, TypeError, IndexError) as error:
                self.log(f"PARTY-UPDATE-FAILED path={path} reason={type(error).__name__}:{error}")
                flow.response = http.Response.make(
                    503,
                    b"",
                    {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))},
                )
                return
            flow.response = http.Response.make(
                200,
                response_body,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": str(int(time.time())),
                },
            )
            return
        if method == "POST" and path in {"/tool/lock", "/tool/convert"}:
            try:
                response_body = self.tool_response(flow)
            except (OSError, RuntimeError, ValueError, StopIteration, KeyError, TypeError, IndexError) as error:
                self.log(f"TOOL-UPDATE-FAILED path={path} reason={type(error).__name__}:{error}")
                flow.response = http.Response.make(
                    503,
                    b"",
                    {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))},
                )
                return
            flow.response = http.Response.make(
                200,
                response_body,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": str(int(time.time())),
                },
            )
            return
        if method == "POST" and path == "/mana/use_item":
            try:
                response_body = self.mana_response(flow)
            except (OSError, RuntimeError, ValueError, StopIteration, KeyError, TypeError, IndexError) as error:
                self.log(f"MANA-USE-FAILED path={path} reason={type(error).__name__}:{error}")
                flow.response = http.Response.make(
                    503,
                    b"",
                    {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))},
                )
                return
            flow.response = http.Response.make(
                200,
                response_body,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": str(int(time.time())),
                },
            )
            return
        if method == "POST" and path in {"/ship/bulk_update", "/ship/ship_tools_set", "/ship/create"}:
            try:
                response_body = self.ship_response(flow)
            except (OSError, RuntimeError, ValueError, StopIteration, KeyError, TypeError, IndexError) as error:
                self.log(f"SHIP-UPDATE-FAILED path={path} reason={type(error).__name__}:{error}")
                flow.response = http.Response.make(
                    503,
                    b"",
                    {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))},
                )
                return
            flow.response = http.Response.make(
                200,
                response_body,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": str(int(time.time())),
                },
            )
            return
        if method == "POST" and path in {
            "/character/enhance",
            "/character/rarity_enhance",
            "/character/enhancement_reset",
            "/character/level_limit_release",
            "/character/growboard_page_release",
            "/character/growboard_bulk_release",
            "/memoria/enhance",
            "/memoria/limit_break",
            "/memoria/lock",
            "/memoria/sell",
        }:
            try:
                response_body = self.progression_response(flow)
            except (OSError, RuntimeError, ValueError, StopIteration, KeyError, TypeError, IndexError) as error:
                self.log(f"PROGRESSION-UPDATE-FAILED path={path} reason={type(error).__name__}:{error}")
                flow.response = http.Response.make(
                    503,
                    b"",
                    {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))},
                )
                return
            flow.response = http.Response.make(
                200,
                response_body,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": str(int(time.time())),
                },
            )
            return
        if REPLAY_MODE and method == "POST" and path == EXPEDITION_REWARD_PATH:
            record = self.choose(flow)
            if record is None:
                flow.response = http.Response.make(
                    503,
                    b"",
                    {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))},
                )
                return
            try:
                response_body = self.expedition_reward_response(record)
            except (RuntimeError, ValueError, OSError) as error:
                self.log(f"EXPEDITION-REWARD-PATCH-FAILED reason={type(error).__name__}:{error}")
                response_body = record.response_body
            flow.response = http.Response.make(
                record.status,
                response_body,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": str(int(time.time())),
                },
            )
            return
        if method == "POST" and path in {
            "/chara_home/register",
            "/profile/update_chara_home_favorite_character_list",
            "/profile/update_selected_home_id",
        }:
            try:
                response_body = self.home_response(flow)
            except (OSError, RuntimeError, ValueError, StopIteration) as error:
                self.log(f"HOME-KEY-WAIT-FAILED path={path} reason={type(error).__name__}:{error}")
                flow.response = http.Response.make(
                    503,
                    b"",
                    {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))},
                )
                return
            flow.response = http.Response.make(
                200,
                response_body,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": str(int(time.time())),
                },
            )
            return

        if not REPLAY_MODE:
            if self.default_response(flow):
                return
            self.log(f"GENERATED-MISS host={flow.request.host} method={method} path={path}")
            flow.response = http.Response.make(
                503,
                b"",
                {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))},
            )
            return

        record = self.choose(flow)
        if record is None:
            flow.response = http.Response.make(
                503,
                b"",
                {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))},
            )
            return
        self.recorded_response(flow, record)


replay = Replay()


def request(flow: http.HTTPFlow):
    original_host = flow.request.headers.get("x-offline-original-host", flow.request.host).lower()
    if original_host == "game.resleriana.jp":
        replay.respond(flow)
    elif original_host == "cdn.resleriana.jp" and urlsplit(flow.request.pretty_url).path.startswith("/master_data/"):
        master_data_version = urlsplit(flow.request.pretty_url).path.removeprefix("/master_data/").strip("/")
        if master_data_version == "(empty)":
            filename = LOCAL_EMPTY_TOKEN_MASTER_DATA_NAME
        elif master_data_version:
            filename = LOCAL_ENCRYPTED_MASTER_DATA_NAME
        else:
            filename = LOCAL_EMPTY_VERSION_MASTER_DATA_NAME
        master_data_path = GAME_DIR / filename
        if master_data_path.is_file():
            replay.log(
                f"MASTER-DATA {flow.request.pretty_url} version={master_data_version or '(empty)'} "
                + f"source={master_data_path}"
            )
            flow.response = http.Response.make(
                200,
                master_data_path.read_bytes(),
                {"Content-Type": "application/octet-stream"},
            )
        else:
            replay.log(f"MASTER-DATA-MISSING {master_data_path}")
            flow.response = http.Response.make(503, b"", {"Content-Type": "application/octet-stream"})
    elif flow.request.pretty_url.lower().split("?", 1)[0].endswith("/manifest.json"):
        manifest = GAME_DIR / "AtelierResleriana_Data" / "ABCache" / "manifest.json"
        replay.log(f"MANIFEST {flow.request.pretty_url}")
        flow.response = http.Response.make(200, manifest.read_text(encoding="utf-8"), {"Content-Type": "application/json; charset=utf-8"})
    elif ".resleriana.jp/" in flow.request.pretty_url.lower():
        replay.log(f"MISS-HOST {flow.request.pretty_url}")
        flow.response = http.Response.make(503, b"", {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))})
