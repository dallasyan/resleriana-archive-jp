import hashlib
import gzip
import json
import os
import sys
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
REPLAY_MODE = os.environ.get("JAPANESE_REPLAY_MODE", "generated").strip().lower() == "replay"
HYBRID_MODE = os.environ.get("JAPANESE_REPLAY_MODE", "generated").strip().lower() == "hybrid"
HYBRID_HANDSHAKE_PATHS = {"/status", "/refund_info/get_country_code", "/auth/sign_in", "/user/log_in"}
HYBRID_INIT_PATHS = {
    "/login_bonus/receive",
    "/web_session/token",
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
    "/web_session/token",
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


def default_encrypted_empty_response() -> bytes:
    response_key, response_iv, response_marker = response_material()
    return encrypt_api_response(
        response_marker,
        b"",
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
    parties: list[bytes] | None = None,
    party_members: list[bytes] | None = None,
    equipment_presets: list[bytes] | None = None,
    chara_homes: list[bytes] | None = None,
    response_key: bytes | None = None,
    response_iv: bytes | None = None,
    response_marker: int | None = None,
) -> bytes:
    if response_key is None or response_iv is None or response_marker is None:
        response_key, response_iv, response_marker = response_material()
    plaintext = make_changed_resources_plaintext(
        profile=profile,
        characters=characters,
        parties=parties,
        party_members=party_members,
        equipment_presets=equipment_presets,
        chara_homes=chara_homes,
    )
    return bytes([response_marker]) + aes_encrypt(
        pkcs7_pad(gzip.compress(plaintext, mtime=0)),
        response_key,
        response_iv,
    )


def make_changed_resources_plaintext(
    profile: bytes | None = None,
    characters: list[bytes] | None = None,
    parties: list[bytes] | None = None,
    party_members: list[bytes] | None = None,
    equipment_presets: list[bytes] | None = None,
    chara_homes: list[bytes] | None = None,
) -> bytes:
    resources = bytearray()
    for character in characters or []:
        resources.extend(write_field(2, 2, character))
    for party in parties or []:
        resources.extend(write_field(9, 2, party))
    for party_member in party_members or []:
        resources.extend(write_field(24, 2, party_member))
    for equipment_preset in equipment_presets or []:
        resources.extend(write_field(26, 2, equipment_preset))
    if profile is not None:
        resources.extend(write_field(39, 2, profile))
    for chara_home in chara_homes or []:
        resources.extend(write_field(61, 2, chara_home))
    return write_field(1, 2, bytes(resources))


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
            "/web_session/token": is_api_message,
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
            "/equipment_preset/bulk_set": is_equipment_preset_request,
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
        self.log_path = GAME_DIR / "offline-replay.log"
        self.log(
            f"loaded session={self.session} records={len(self.records)} "
            f"capture_fallback={not bool(self.records)} mode={'replay' if REPLAY_MODE else 'generated'}"
        )
        if not self.records:
            self.log("CAPTURE-SESSION-MISSING using profile/default offline responses")

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
            "/equipment_preset/bulk_set": is_equipment_preset_request,
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

        if path == "/equipment_preset/bulk_set":
            preset_number = next(
                int(value)
                for number, wire_type, value in read_wire_fields(plaintext)
                if number == 1 and wire_type == 0
            )
            if self.equipment_preset_records is None:
                self.equipment_preset_records = load_profile_equipment_preset_records(GAME_DIR / "profile.bin")
            preset = self.equipment_preset_records.get(preset_number, write_field(1, 0, preset_number))
            for source_field, target_field in ((2, 3), (3, 4), (4, 5), (5, 6)):
                preset = replace_message_field_in_place(preset, target_field, message_field(plaintext, source_field))
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
        if path == "/character/equip":
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

    def changed_resources_encrypted_response(
        self,
        response_key: bytes,
        response_iv: bytes,
        response_marker: int,
        profile: bytes | None = None,
        characters: list[bytes] | None = None,
        parties: list[bytes] | None = None,
        party_members: list[bytes] | None = None,
        equipment_presets: list[bytes] | None = None,
        chara_homes: list[bytes] | None = None,
    ) -> bytes:
        plaintext = make_changed_resources_plaintext(
            profile=profile,
            characters=characters,
            parties=parties,
            party_members=party_members,
            equipment_presets=equipment_presets,
            chara_homes=chara_homes,
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
        return bytes([response_marker]) + aes_encrypt(
            pkcs7_pad(gzip.compress(make_exploration_start_response(progress), mtime=0)),
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
                response_key, response_iv, response_marker = response_material()
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
        if path in {
            "/login_bonus/receive",
            "/external_purchase/receive",
            "/web_session/token",
            EXPEDITION_REWARD_PATH,
        }:
            response_body = (
                default_login_bonus_response()
                if path == "/login_bonus/receive"
                else default_encrypted_empty_response()
            )
            flow.response = http.Response.make(
                200,
                response_body,
                {
                    "Content-Type": "application/octet-stream",
                    "X-Content-Encoding": "gzip",
                    "x-server-timestamp": timestamp,
                },
            )
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
            "/equipment_preset/bulk_set",
        }:
            try:
                response_body = self.party_response(flow)
            except (OSError, RuntimeError, ValueError, StopIteration) as error:
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
