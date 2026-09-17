"""Decrypt and unpack Japanese game network capture files."""

from __future__ import annotations

import argparse
import gzip
import json
import string
from pathlib import Path
from typing import Iterable

from Crypto.Cipher import AES


AES_IV = bytes.fromhex("65a99b89a634fca3193c5212e5219378")


def rotate_key(seed: bytes, count: int) -> bytes:
    value = int.from_bytes(seed, "big")
    value = ((value << count) & ((1 << 128) - 1)) | (value >> (128 - count))
    return value.to_bytes(16, "big")


AES_KEYS = tuple(
    rotate_key(seed, rotation)
    for seed in (
        bytes.fromhex("487a9961c947f7d92ed6b79fc0545fea"),
        bytes.fromhex("ea5f54c09fb7d62ed9f747c961997a48"),
    )
    for rotation in range(128)
)


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
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


def read_wire_fields(data: bytes) -> list[tuple[int, int, object]]:
    fields: list[tuple[int, int, object]] = []
    offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if number <= 0:
            raise ValueError("invalid protobuf field number")
        if wire == 0:
            value, offset = read_varint(data, offset)
        elif wire == 1:
            value = data[offset:offset + 8]
            if len(value) != 8:
                raise ValueError("truncated fixed64 field")
            offset += 8
        elif wire == 2:
            length, offset = read_varint(data, offset)
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


def printable_text(value: bytes) -> str | None:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text or any(character not in string.printable and not character.isspace() for character in text):
        return None
    return text


def format_fields(data: bytes, prefix: str = "", depth: int = 0) -> list[str]:
    fields = read_wire_fields(data)
    lines: list[str] = []
    indent = "  " * depth
    for number, wire, value in fields:
        path = f"{prefix}{number}"
        if wire == 0:
            lines.append(f"{indent}{path} varint={value}")
            continue
        if wire == 1 or wire == 5:
            lines.append(f"{indent}{path} fixed{64 if wire == 1 else 32}={bytes(value).hex()}")
            continue

        payload = bytes(value)
        text = printable_text(payload)
        if text is not None:
            lines.append(f"{indent}{path} string={text!r}")
            continue

        lines.append(f"{indent}{path} bytes={len(payload)} hex={payload.hex()}")
        try:
            lines.extend(format_fields(payload, f"{path}.", depth + 1))
        except ValueError:
            pass
    return lines


def decrypt_payload(data: bytes) -> tuple[bytes, int]:
    if len(data) < 17 or (len(data) - 1) % AES.block_size:
        raise ValueError("not a marker-prefixed AES payload")
    marker = data[0]
    key = AES_KEYS[marker]
    padded = AES.new(key, AES.MODE_CBC, AES_IV).decrypt(data[1:])
    padding = padded[-1]
    if not 0 < padding <= AES.block_size or padded[-padding:] != bytes([padding]) * padding:
        raise ValueError("invalid PKCS#7 padding")
    compressed = padded[:-padding]
    try:
        return gzip.decompress(compressed), marker
    except (OSError, EOFError):
        return compressed, marker


def output_paths(source: Path, output_root: Path | None) -> tuple[Path, Path]:
    if output_root is not None:
        output = output_root / source.name
    else:
        output = source.with_name(f"{source.stem}.decrypted.bin")
    unpacked = output.with_suffix(output.suffix + ".protobuf.txt")
    return output, unpacked


def process_file(source: Path, output_root: Path | None) -> None:
    output, unpacked = output_paths(source, output_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    try:
        plaintext, marker = decrypt_payload(data)
        output.write_bytes(plaintext)
        try:
            lines = [f"marker=0x{marker:02x}", f"plaintext_bytes={len(plaintext)}"]
            lines.extend(format_fields(plaintext))
        except ValueError:
            lines = []
        if lines:
            unpacked.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"DECRYPTED {source} marker=0x{marker:02x} bytes={len(plaintext)}")
    except (IndexError, ValueError):
        output.write_bytes(data)
        print(f"COPIED {source} bytes={len(data)} (not an encrypted protobuf payload)")


def process_folder(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.iterdir()):
        if path.is_dir():
            process_folder(path, destination / path.name)
        elif path.suffix.lower() == ".bin":
            process_file(path, destination)
        else:
            target = destination / path.name
            target.write_bytes(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="encrypted capture file or capture directory")
    parser.add_argument("--output", type=Path, help="output file or directory")
    args = parser.parse_args()
    source = args.input.resolve()
    if not source.exists():
        parser.error(f"input does not exist: {source}")
    if source.is_dir():
        destination = args.output or source.with_name(f"decrypted-{source.name}")
        process_folder(source, destination)
        print(f"WROTE {destination}")
    else:
        process_file(source, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
