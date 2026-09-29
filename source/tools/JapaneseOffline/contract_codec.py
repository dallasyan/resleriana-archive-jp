"""Schema-aware protobuf codec driven by contract-dump fields.txt.

fields.txt lists every client message as ``message <full.name> (<file>)``
followed by ``<Kind> <name> = <number> (<type>)`` lines, plus ``enum``
blocks mapping names to numbers. This module turns that dump into:

- a contract database: message field names/numbers/kinds and enum values,
- a decoder: wire bytes to named nested dicts (repeated fields become
  lists, unknown fields are preserved verbatim),
- an encoder: named dicts back to identical wire bytes.

Scope notes: the dump carries no ``repeated`` markers, so repetition is
inferred from the wire (multiple emissions of one number). Scalar kinds
present in the dump are Bool, Double, Enum, Float, Int32, Int64, Message,
and String; anything else raises a clear error instead of guessing.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path


MESSAGE_RE = re.compile(r"^message (\S+) \((\S+)\)$")
ENUM_RE = re.compile(r"^enum (\S+)$")
FIELD_RE = re.compile(r"^  ([A-Za-z][A-Za-z0-9]*) ([a-z_][a-zA-Z0-9_]*) = ([0-9]+)(?: \((.*)\))?$")
ENUM_VALUE_RE = re.compile(r"^  ([a-z_][a-zA-Z0-9_]*) = ([0-9]+)$")

VARINT_KINDS = {"Int32", "Int64", "Bool", "Enum"}


class ContractDB:
    """Parsed fields.txt: messages, enums, and source files."""

    def __init__(self) -> None:
        self.messages: dict[str, dict[int, dict]] = {}
        self.message_files: dict[str, str] = {}
        self.enums: dict[str, dict[int, str]] = {}
        self.enum_names: dict[str, dict[str, int]] = {}


def parse_fields_txt(path: str | Path) -> ContractDB:
    """Parse a contract-dump fields.txt file into a ContractDB."""
    db = ContractDB()
    current_message: str | None = None
    current_enum: str | None = None
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line:
            current_message = None
            current_enum = None
            continue
        message = MESSAGE_RE.match(line)
        if message:
            current_message = message.group(1)
            current_enum = None
            db.messages.setdefault(current_message, {})
            db.message_files[current_message] = message.group(2)
            continue
        enum = ENUM_RE.match(line)
        if enum:
            current_enum = enum.group(1)
            current_message = None
            db.enums.setdefault(current_enum, {})
            db.enum_names.setdefault(current_enum, {})
            continue
        if current_enum is not None:
            value = ENUM_VALUE_RE.match(line)
            if not value:
                raise ValueError(f"cannot parse enum value line: {raw_line!r}")
            db.enums[current_enum][int(value.group(2))] = value.group(1)
            db.enum_names[current_enum][value.group(1)] = int(value.group(2))
            continue
        if current_message is not None:
            field = FIELD_RE.match(line)
            if not field:
                raise ValueError(f"cannot parse field line: {raw_line!r}")
            kind, name, number = field.group(1), field.group(2), int(field.group(3))
            type_name = (field.group(4) or "").strip()
            db.messages[current_message][number] = {
                "name": name,
                "kind": kind,
                "type": type_name,
            }
            continue
        raise ValueError(f"line outside message/enum block: {raw_line!r}")
    return db


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            raise ValueError("varint is too long")
    raise ValueError("truncated varint")


def _write_varint(value: int) -> bytes:
    value = int(value) & ((1 << 64) - 1)
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _wire_fields(data: bytes) -> list[tuple[int, int, object]]:
    fields: list[tuple[int, int, object]] = []
    offset = 0
    while offset < len(data):
        tag, offset = _read_varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if number <= 0:
            raise ValueError("invalid protobuf field number")
        if wire == 0:
            value, offset = _read_varint(data, offset)
        elif wire == 1:
            value = data[offset:offset + 8]
            if len(value) != 8:
                raise ValueError("truncated fixed64 field")
            offset += 8
        elif wire == 2:
            length, offset = _read_varint(data, offset)
            value = data[offset:offset + length]
            if len(value) != length:
                raise ValueError("truncated length-delimited field")
            offset += length
        elif wire == 5:
            value = data[offset:offset + 4]
            if len(value) != 4:
                raise ValueError("truncated fixed32 field")
            offset += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        fields.append((number, wire, value))
    return fields


def _decode_scalar(kind: str, wire: int, value: object):
    if wire == 0:
        return int(value)
    if wire == 2 and kind in VARINT_KINDS:
        # Packed repeated scalars: preserve the packed form so re-encoding
        # reproduces the original bytes exactly.
        payload = bytes(value)
        items: list[int] = []
        offset = 0
        try:
            while offset < len(payload):
                item, offset = _read_varint(payload, offset)
                items.append(item)
        except ValueError:
            return {"$bytes": payload.hex()}
        if offset == len(payload):
            return {"$packed": items}
        return {"$bytes": payload.hex()}
    if wire == 5:
        raw = bytes(value)
        if kind == "Float":
            return struct.unpack("<f", raw)[0]
        return raw.hex()
    if wire == 1:
        raw = bytes(value)
        if kind == "Double":
            return struct.unpack("<d", raw)[0]
        return raw.hex()
    raw = bytes(value)
    if kind == "String":
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return {"$bytes": raw.hex()}
    return {"$bytes": raw.hex()}


def decode_message(db: ContractDB, message_name: str, data: bytes) -> dict:
    """Decode wire bytes with the named contract message.

    Returns ``{"$message": name, <field>: value, ..., "unknown": [...]}``.
    Repeated fields accumulate into lists. Nested messages decode
    recursively when their type is known, otherwise they are kept as
    ``{"$bytes": hex}`` with a generic nested dump attempt omitted.
    Unknown field numbers are preserved under ``unknown`` as
    ``{"number": n, "wire": w, "hex": h}`` for lossless re-encoding.
    """
    schema = db.messages.get(message_name)
    if schema is None:
        raise ValueError(f"unknown contract message: {message_name}")
    node: dict = {"$message": message_name}
    unknown: list[dict] = []
    for number, wire, value in _wire_fields(data):
        field = schema.get(number)
        if field is None:
            raw = value if isinstance(value, int) else bytes(value).hex()
            unknown.append({"number": number, "wire": wire, "hex": raw if isinstance(raw, str) else f"{raw}"})
            continue
        name, kind, type_name = field["name"], field["kind"], field["type"]
        if kind == "Message" and wire == 2:
            payload = bytes(value)
            if type_name in db.messages:
                decoded = decode_message(db, type_name, payload)
            else:
                decoded = {"$message": type_name, "$bytes": payload.hex()}
        elif kind == "Enum" and wire == 0:
            number_value = int(value)
            names = db.enums.get(type_name, {})
            decoded = {"value": number_value, "name": names.get(number_value)}
        else:
            decoded = _decode_scalar(kind, wire, value)
        if name in node:
            existing = node[name]
            if isinstance(existing, list):
                existing.append(decoded)
            else:
                node[name] = [existing, decoded]
        else:
            node[name] = decoded
    if unknown:
        node["unknown"] = unknown
    return node


def _encode_scalar(kind: str, type_name: str, db: ContractDB, value: object) -> tuple[int, object]:
    if kind in ("Int32", "Int64", "Bool"):
        if isinstance(value, dict) and "$packed" in value:
            payload = b"".join(_write_varint(int(item)) for item in value["$packed"])
            return 2, payload
        return 0, _write_varint(int(value))
    if kind == "Enum":
        if isinstance(value, dict) and "$packed" in value:
            payload = b"".join(_write_varint(int(item)) for item in value["$packed"])
            return 2, payload
        if isinstance(value, dict):
            number = value.get("value")
            if number is None and value.get("name") is not None:
                number = db.enum_names.get(type_name, {}).get(value["name"])
            if number is None:
                raise ValueError(f"cannot encode enum value: {value!r}")
            return 0, _write_varint(int(number))
        return 0, _write_varint(int(value))
    if kind == "String":
        if isinstance(value, dict) and "$bytes" in value:
            return 2, bytes.fromhex(value["$bytes"])
        if not isinstance(value, str):
            raise ValueError(f"cannot encode string value: {value!r}")
        return 2, value.encode("utf-8")
    if kind == "Float":
        return 5, struct.pack("<f", float(value))
    if kind == "Double":
        return 1, struct.pack("<d", float(value))
    raise ValueError(f"unsupported scalar kind for encoding: {kind}")


def _encode_field(db: ContractDB, message_name: str, number: int, value: object) -> bytes:
    field = db.messages[message_name][number]
    kind, type_name = field["kind"], field["type"]
    chunks = []
    values = value if isinstance(value, list) else [value]
    for item in values:
        if kind == "Message":
            if not isinstance(item, dict):
                raise ValueError(f"cannot encode message field {field['name']}: {item!r}")
            if "$bytes" in item and len(item) == 2 and "$message" in item:
                payload = bytes.fromhex(item["$bytes"])
            else:
                nested = item.get("$message", type_name)
                payload = encode_message(db, nested, item)
            chunks.append(_write_varint((number << 3) | 2) + _write_varint(len(payload)) + payload)
        else:
            wire, payload = _encode_scalar(kind, type_name, db, item)
            if wire == 0:
                chunks.append(_write_varint(number << 3) + payload)
            elif wire == 2:
                chunks.append(_write_varint((number << 3) | 2) + _write_varint(len(payload)) + payload)
            elif wire == 5:
                chunks.append(_write_varint((number << 3) | 5) + payload)
            else:
                chunks.append(_write_varint((number << 3) | 1) + payload)
    return b"".join(chunks)


def encode_message(db: ContractDB, message_name: str, node: dict) -> bytes:
    """Encode a decoded node back to wire bytes for the named message."""
    schema = db.messages.get(message_name)
    if schema is None:
        raise ValueError(f"unknown contract message: {message_name}")
    if node.get("$message", message_name) != message_name:
        raise ValueError(f"node message {node.get('$message')!r} does not match {message_name!r}")
    by_name = {field["name"]: number for number, field in schema.items()}
    out = bytearray()
    for name, value in node.items():
        if name in ("$message", "unknown"):
            continue
        if name not in by_name:
            raise ValueError(f"unknown field {name!r} for {message_name}")
        out.extend(_encode_field(db, message_name, by_name[name], value))
    for item in node.get("unknown") or []:
        number, wire = int(item["number"]), int(item["wire"])
        raw = item["hex"]
        if wire == 0:
            out.extend(_write_varint(number << 3) + _write_varint(int(raw)))
        elif wire in (1, 5):
            payload = bytes.fromhex(raw)
            out.extend(_write_varint((number << 3) | wire) + payload)
        else:
            payload = bytes.fromhex(raw)
            out.extend(_write_varint((number << 3) | wire) + _write_varint(len(payload)) + payload)
    return bytes(out)


def enum_name(db: ContractDB, enum_type: str, number: int) -> str | None:
    """Map an enum number to its contract name, if known."""
    return db.enums.get(enum_type, {}).get(int(number))
