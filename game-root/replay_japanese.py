import hashlib
import gzip
import json
import os
import time
from dataclasses import dataclass
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
EXPEDITION_REWARD_PATH = "/expedition/reward_receive"
DEFAULT_EXPEDITION_SPECIAL_REWARD_IDS = (1074, 1075, 1076, 1077, 1078, 1079, 1080)
REUSABLE_PATHS = {
    "/status",
    "/refund_info/get_country_code",
    "/auth/sign_in",
    "/user/log_in",
    "/login_bonus/receive",
    "/external_purchase/receive",
    "/web_session/token",
    EXPEDITION_REWARD_PATH,
}

# Captured successful no-op RecipeLearnResponse: changed_resources is present but empty.
OFFLINE_RECIPE_LEARN_RESPONSE = bytes.fromhex("14fc17f3894a4c3227473e9d04d1f1ac5c")

# These candidates were observed by the native observer for the Japanese API crypto layer.
API_AES_KEYS = tuple(
    bytes.fromhex(value)
    for value in (
        "b14682ecddfdad0d87a7986516d4ab70",
        "976b5bcfe02a2ff5243d4cb0e4a3fbec",
        "b5bcfe02a2ff5243d4cb0e4a3fbec976",
        "c3928fefb25dad6f3f80a8bfd490f532",
        "80a8bfd490f532c3928fefb25dad6f3f",
        "5c3c5345e14f8ec025ee22a481746c0a",
        "28fefb25dad6f3f80a8bfd490f532c39",
        "6587251fdf64bb5ade7f01517fa921ea",
        "43d4cb0e4a3fbec976b5bcfe02a2ff52",
        "df58bb67dd1f258665e923a97d53027e",
        "fea487a9961c947f7d92ed6b79fc0545",
        "e923a97d53027edf58bb67dd1f258665",
        "c09fb7d62ed9f747c961997a48ea5f54",
        "6cfba3e4b0ccbd24752faa604fdbeb17",
        "f491d4bea9813f6fac5db3ee8f92c332",
        "ed6b79fc0545fea487a9961c947f7d92",
        "5db3ee8f92c332f491d4bea9813f6fac",
        "3f80a8bfd490f532c3928fefb25dad6f",
        "a5f54c09fb7d62ed9f747c961997a48e",
        "3d4cb0e4a3fbec976b5bcfe02a2ff524",
        "e4b0ccbd24752faa604fdbeb176cfba3",
        "5243d4cb0e4a3fbec976b5bcfe02a2ff",
        "76cfba3e4b0ccbd24752faa604fdbeb1",
        "91d4bea9813f6fac5db3ee8f92c332f4",
        "5e923a97d53027edf58bb67dd1f25866",
        "fe02a2ff5243d4cb0e4a3fbec976b5bc",
        "545fea487a9961c947f7d92ed6b79fc0",
        "c332f491d4bea9813f6fac5db3ee8f92",
        "d4cb0e4a3fbec976b5bcfe02a2ff5243",
        "90f532c3928fefb25dad6f3f80a8bfd4",
        "ea9813f6fac5db3ee8f92c332f491d4b",
        "2c332f491d4bea9813f6fac5db3ee8f9",
        "58bb67dd1f258665e923a97d53027edf",
        "c947f7d92ed6b79fc0545fea487a9961",
        "a48ea5f54c09fb7d62ed9f747c961997",
        "961c947f7d92ed6b79fc0545fea487a9",
        "32c3928fefb25dad6f3f80a8bfd490f5",
        "db3ee8f92c332f491d4bea9813f6fac5",
        "8ea5f54c09fb7d62ed9f747c961997a4",
        "ea5f54c09fb7d62ed9f747c961997a48",
        "f54c09fb7d62ed9f747c961997a48ea5",
        "9fc0545fea487a9961c947f7d92ed6b7",
        "9961c947f7d92ed6b79fc0545fea487a",
        "a3fbec976b5bcfe02a2ff5243d4cb0e4",
        "bcfe02a2ff5243d4cb0e4a3fbec976b5",
        "2c3928fefb25dad6f3f80a8bfd490f53",
        "5f54c09fb7d62ed9f747c961997a48ea",
        "747c961997a48ea5f54c09fb7d62ed9f",
        "04fdbeb176cfba3e4b0ccbd24752faa6",
        "a6587251fdf64bb5ade7f01517fa921e",
        "2ed6b79fc0545fea487a9961c947f7d9",
        "a9961c947f7d92ed6b79fc0545fea487",
        "b25dad6f3f80a8bfd490f532c3928fef",
        "fb7d62ed9f747c961997a48ea5f54c09",
        "c0545fea487a9961c947f7d92ed6b79f",
    )
)
API_AES_IVS = tuple(
    bytes.fromhex(value)
    for value in (
        "f8598d383b3a01e4db69b8eb0a402390",
        "65a99b89a634fca3193c5212e5219378",
        "6376e8c14c960811e899e562c56c9480",
    )
)


def observed_aes_sequences() -> tuple[tuple[tuple[bytes, ...], tuple[bytes, ...]], ...]:
    material_root = GAME_DIR / "japanese-capture"
    material_paths = []
    selected_material_path: Path | None = None
    try:
        selected_material_path = session_directory() / "aes-material.json"
    except (FileNotFoundError, OSError):
        pass
    root_material_path = GAME_DIR / "aes-material.json"
    prioritized_material_paths = [root_material_path, selected_material_path]
    for prioritized_path in prioritized_material_paths:
        if prioritized_path is None or not prioritized_path.is_file():
            continue
        material_paths.append(prioritized_path)
    priority_count = len(material_paths)
    for material_path in material_root.rglob("aes-material.json"):
        if selected_material_path is not None and material_path == selected_material_path:
            continue
        if material_path not in material_paths:
            material_paths.append(material_path)
    historical_material_paths = []
    for material_path in material_paths[priority_count:]:
        try:
            historical_material_paths.append((material_path.stat().st_mtime, material_path))
        except OSError:
            continue
    material_paths = material_paths[:priority_count] + [
        material_path for _, material_path in sorted(historical_material_paths, reverse=True)
    ]
    sequences = []
    for material_path in material_paths:
        try:
            material = json.loads(material_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        material_keys = []
        material_ivs = []
        key_values = material.get("key_candidates") or ([material["key"]] if material.get("key") else [])
        iv_values = material.get("iv_candidates") or ([material["iv"]] if material.get("iv") else [])
        for value in key_values:
            try:
                key = bytes.fromhex(value)
            except (TypeError, ValueError):
                continue
            if key not in material_keys:
                material_keys.append(key)
        for value in iv_values:
            try:
                iv = bytes.fromhex(value)
            except (TypeError, ValueError):
                continue
            if iv not in material_ivs:
                material_ivs.append(iv)
        if material_keys and material_ivs:
            sequences.append((tuple(material_keys), tuple(material_ivs)))
    sequences.append((API_AES_KEYS, API_AES_IVS))
    return tuple(sequences)


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
SKIN_RESPONSE_KEY = bytes.fromhex("5243d4cb0e4a3fbec976b5bcfe02a2ff")
SKIN_RESPONSE_IV = bytes.fromhex("65a99b89a634fca3193c5212e5219378")
SKIN_KEY_WAIT_SECONDS = 3.0
SKIN_KEY_RETRY_INTERVAL = 0.1
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
        return Path(configured)

    root = GAME_DIR / "japanese-capture"
    configured_file = GAME_DIR / "offline-session.txt"
    if configured_file.exists():
        configured_value = configured_file.read_text(encoding="utf-8").strip()
        if configured_value:
            configured_path = Path(configured_value)
            return configured_path if configured_path.is_absolute() else root / configured_value

    sessions = sorted(root.glob("session-*"), key=lambda path: path.stat().st_mtime)
    if not sessions:
        raise FileNotFoundError(f"no capture sessions found in {root}")
    return sessions[-1]


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
    keys, ivs = observed_aes_candidates()
    for key in keys:
        for iv in ivs:
            try:
                compressed = pkcs7_unpad(aes_decrypt(data[1:], key, iv))
                plaintext = gzip.decompress(compressed)
                read_wire_fields(plaintext)
                return data[0], plaintext, key, iv
            except (RuntimeError, OSError, EOFError, ValueError):
                continue
    raise ValueError("could not decrypt API response")


def encrypt_api_response(marker: int, plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    compressed = gzip.compress(plaintext, mtime=0)
    return bytes([marker]) + aes_encrypt(pkcs7_pad(compressed), key, iv)


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
            if not any(inner_number == 1 and inner_type == 0 for inner_number, inner_type, _ in inner_fields):
                return False
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
        return b"", SKIN_RESPONSE_KEY, SKIN_RESPONSE_IV, SKIN_RESPONSE_MARKER
    if len(data) < 17 or (len(data) - 1) % 16:
        raise ValueError("encrypted request has an invalid size")
    for keys, ivs in observed_aes_sequences():
        for key_index, key in enumerate(keys):
            for iv in ivs:
                try:
                    plaintext = pkcs7_unpad(aes_decrypt(data[1:], key, iv))
                    if validator(plaintext):
                        if key_index + 1 < len(keys):
                            response_key = keys[key_index + 1]
                        else:
                            response_key = next(
                                (
                                    API_AES_KEYS[index + 1]
                                    for index, candidate in enumerate(API_AES_KEYS[:-1])
                                    if candidate == key
                                ),
                                SKIN_RESPONSE_KEY,
                            )
                        response_marker = SKIN_RESPONSE_MARKER
                        if response_path is not None:
                            captured_material = captured_response_material(response_path, key, iv)
                            if captured_material is not None:
                                response_key, iv, response_marker = captured_material
                        return plaintext, response_key, iv, response_marker
                except (RuntimeError, ValueError):
                    continue
    raise ValueError("could not decrypt request")


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
    chara_homes: list[bytes] | None = None,
    response_key: bytes = SKIN_RESPONSE_KEY,
    response_iv: bytes = SKIN_RESPONSE_IV,
    response_marker: int = SKIN_RESPONSE_MARKER,
) -> bytes:
    resources = bytearray()
    if profile is not None:
        resources.extend(write_field(39, 2, profile))
    for chara_home in chara_homes or []:
        resources.extend(write_field(61, 2, chara_home))
    plaintext = write_field(1, 2, bytes(resources))
    return bytes([response_marker]) + aes_encrypt(
        pkcs7_pad(gzip.compress(plaintext, mtime=0)),
        response_key,
        response_iv,
    )


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
    keys, ivs = observed_aes_candidates()
    for key in keys:
        for iv in ivs:
            try:
                compressed = pkcs7_unpad(aes_decrypt(data[1:], key, iv))
                return gzip.decompress(compressed)
            except (RuntimeError, OSError, EOFError, ValueError):
                continue
    raise ValueError("could not decrypt profile")


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


_CAPTURED_RESPONSE_MATERIALS: tuple[
    dict[tuple[str, bytes, bytes], tuple[bytes, bytes, int]],
    dict[str, tuple[bytes, bytes, int]],
] | None = None


def captured_response_material(
    response_path: str,
    request_key: bytes | None = None,
    request_iv: bytes | None = None,
) -> tuple[bytes, bytes, int] | None:
    global _CAPTURED_RESPONSE_MATERIALS
    if _CAPTURED_RESPONSE_MATERIALS is None:
        exact_materials: dict[tuple[str, bytes, bytes], tuple[bytes, bytes, int]] = {}
        default_materials: dict[str, tuple[bytes, bytes, int]] = {}
        validators = {
            "/character/skin_set": is_skin_request_plaintext,
            "/chara_home/register": is_home_register_request,
            "/profile/update_chara_home_favorite_character_list": is_favorite_request,
            "/profile/update_selected_home_id": is_selected_home_request,
        }
        keys, ivs = observed_aes_candidates()
        sequences = observed_aes_sequences()
        sessions = sorted(
            (path for path in (GAME_DIR / "japanese-capture").glob("session-*") if path.is_dir()),
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
                    default_materials.setdefault(
                        record.path,
                        (response_key or SKIN_RESPONSE_KEY, response_iv or SKIN_RESPONSE_IV, response_marker),
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


def make_skin_response(
    character_records: dict[int, bytes],
    character_id: int,
    skin_id: int | None,
    response_key: bytes = SKIN_RESPONSE_KEY,
    response_iv: bytes = SKIN_RESPONSE_IV,
    response_marker: int = SKIN_RESPONSE_MARKER,
) -> bytes:
    character = character_with_skin(character_records.get(character_id), character_id, skin_id)
    resources = write_field(2, 2, character)
    plaintext = write_field(1, 2, resources)
    compressed = gzip.compress(plaintext, mtime=0)
    return bytes([response_marker]) + aes_encrypt(
        pkcs7_pad(compressed),
        response_key,
        response_iv,
    )


class Replay:
    def __init__(self):
        self.session = session_directory()
        self.records = sorted(
            (parse_record(path) for path in self.session.glob("[0-9][0-9][0-9][0-9].txt")),
            key=lambda record: record.number,
        )
        self.used: set[int] = set()
        self.character_records: dict[int, bytes] | None = None
        self.home_state_loaded = False
        self.home_profile = b""
        self.home_records: dict[int, bytes] = {}
        self.home_favorite_character_ids: list[int] = []
        self.last_selected_home_field = 10
        self.expedition_special_reward_ids = expedition_special_reward_ids()
        self.expedition_special_reward_index = 0
        self.log_path = GAME_DIR / "offline-replay.log"
        self.log(f"loaded session={self.session} records={len(self.records)}")

    def log(self, message: str) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")

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
            response = make_skin_response(
                self.character_records,
                character_id,
                skin_id,
                response_key,
                response_iv,
                response_marker,
            )
            self.log(
                f"LOCAL-SKIN host={flow.request.host} method=POST path=/character/skin_set "
                f"status=200 character_id={character_id} skin_id={skin_id if skin_id is not None else 'default'}"
            )
            return response
        except (OSError, RuntimeError, ValueError, StopIteration) as error:
            self.log(f"SKIN-KEY-WAIT-FAILED path=/character/skin_set reason={type(error).__name__}:{error}")
            raise

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

    def home_response(self, flow: http.HTTPFlow) -> bytes:
        self.ensure_home_state()
        path = urlsplit(flow.request.pretty_url).path
        request_body = flow.request.raw_content or b""
        response_key = SKIN_RESPONSE_KEY
        response_iv = SKIN_RESPONSE_IV
        response_marker = SKIN_RESPONSE_MARKER

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
            return make_changed_resources_response(
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
            return make_changed_resources_response(
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
                captured_material = captured_response_material(path)
                if captured_material is not None:
                    response_key, response_iv, response_marker = captured_material
            return make_changed_resources_response(
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

    def respond(self, flow: http.HTTPFlow) -> None:
        path = urlsplit(flow.request.pretty_url).path
        method = flow.request.method.upper()
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
        if method == "POST" and path == EXPEDITION_REWARD_PATH:
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

        record = self.choose(flow)
        if record is None:
            flow.response = http.Response.make(
                503,
                b"",
                {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))},
            )
            return

        response_body = record.response_body
        if record.path == "/auth/sign_in" and record.status == 200:
            response_body = self.auth_response(response_body)
        if record.path == "/user/log_in" and record.status == 200:
            profile_path = GAME_DIR / "profile.bin"
            if profile_path.exists():
                response_body = profile_path.read_bytes()
                self.log(f"PROFILE path={profile_path} bytes={len(response_body)}")
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


replay = Replay()


def request(flow: http.HTTPFlow):
    original_host = flow.request.headers.get("x-offline-original-host", flow.request.host).lower()
    if original_host == "game.resleriana.jp":
        replay.respond(flow)
    elif flow.request.pretty_url.lower().split("?", 1)[0].endswith("/manifest.json"):
        manifest = GAME_DIR / "AtelierResleriana_Data" / "ABCache" / "manifest.json"
        replay.log(f"MANIFEST {flow.request.pretty_url}")
        flow.response = http.Response.make(200, manifest.read_text(encoding="utf-8"), {"Content-Type": "application/json; charset=utf-8"})
    elif ".resleriana.jp/" in flow.request.pretty_url.lower():
        replay.log(f"MISS-HOST {flow.request.pretty_url}")
        flow.response = http.Response.make(503, b"", {"Content-Type": "application/octet-stream", "x-server-timestamp": str(int(time.time()))})
