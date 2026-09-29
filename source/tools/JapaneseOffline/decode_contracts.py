"""Decode protobuf FileDescriptorProto dumps into .proto text and a FileDescriptorSet.

Reads the `*.bin` files written by the ContractDump BepInEx plugin (each one
a serialized FileDescriptorProto) and emits one `.proto` file per input plus
a combined `descriptor-set.pb`. With `--merge <existing.pb>`, files from an
existing set (e.g. profile-descriptors.pb) are kept when not overridden.

Usage:
    python decode_contracts.py <contract-dump-dir> <output-dir> [--merge existing.pb]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from google.protobuf import descriptor_pb2, text_format
except ImportError:
    print("missing google.protobuf; install the profile-editor requirements first", file=sys.stderr)
    raise SystemExit(2)


TYPE_NAMES = {
    1: "double",
    2: "float",
    3: "int64",
    4: "uint64",
    5: "int32",
    6: "fixed64",
    7: "fixed32",
    8: "bool",
    9: "string",
    10: "group",
    11: "message",
    12: "bytes",
    13: "uint32",
    14: "enum",
    15: "sfixed32",
    16: "sfixed64",
    17: "sint32",
    18: "sint64",
}


def field_type(field) -> str:
    kind = TYPE_NAMES.get(int(field.type), "bytes")
    if int(field.type) in (11, 14):
        return field.type_name.lstrip(".")
    return kind


def emit_message(message, indent: int, lines: list[str]) -> None:
    pad = "  " * indent
    lines.append(f"{pad}message {message.name} {{")
    oneofs: dict[int, list] = {}
    plain = []
    for field in message.field:
        if field.HasField("oneof_index"):
            oneofs.setdefault(int(field.oneof_index), []).append(field)
        else:
            plain.append(field)
    for field in plain:
        label = "repeated " if int(field.label) == 3 else ""
        lines.append(f"{pad}  {label}{field_type(field)} {field.name} = {int(field.number)};")
    for index, group in sorted(oneofs.items()):
        name = message.oneof_decl[index].name if index < len(message.oneof_decl) else f"oneof_{index}"
        lines.append(f"{pad}  oneof {name} {{")
        for field in group:
            label = "repeated " if int(field.label) == 3 else ""
            lines.append(f"{pad}    {label}{field_type(field)} {field.name} = {int(field.number)};")
        lines.append(f"{pad}  }}")
    for nested in message.nested_type:
        emit_message(nested, indent + 1, lines)
    for enum in message.enum_type:
        emit_enum(enum, indent + 1, lines)
    lines.append(f"{pad}}}")


def emit_enum(enum, indent: int, lines: list[str]) -> None:
    pad = "  " * indent
    lines.append(f"{pad}enum {enum.name} {{")
    for value in enum.value:
        lines.append(f"{pad}  {value.name} = {int(value.number)};")
    lines.append(f"{pad}}}")


def emit_proto(fd) -> str:
    lines: list[str] = []
    if fd.syntax:
        lines.append(f'syntax = "{fd.syntax}";')
    if fd.package:
        lines.append(f"package {fd.package};")
    lines.append("")
    for dependency in fd.dependency:
        lines.append(f'import "{dependency}";')
    if fd.dependency:
        lines.append("")
    for message in fd.message_type:
        emit_message(message, 0, lines)
        lines.append("")
    for enum in fd.enum_type:
        emit_enum(enum, 0, lines)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--merge", type=Path, default=None)
    args = parser.parse_args()

    files: dict[str, object] = {}
    covered: set[str] = set()
    for path in sorted(args.input.glob("*.bin")):
        fd = descriptor_pb2.FileDescriptorProto()
        fd.ParseFromString(path.read_bytes())
        files[fd.name or path.stem] = fd
        covered.add(path.stem)
    for path in sorted(args.input.glob("*.txt")):
        if path.name in ("fields.txt", "manifest.txt", "debug.txt"):
            continue
        if path.stem in covered:
            continue
        fd = descriptor_pb2.FileDescriptorProto()
        try:
            text_format.Parse(path.read_text(encoding="utf-8"), fd)
        except Exception as error:
            print(f"skip {path.name}: {error}", file=sys.stderr)
            continue
        files[fd.name or path.stem] = fd
    if args.merge is not None:
        existing = descriptor_pb2.FileDescriptorSet()
        existing.ParseFromString(args.merge.read_bytes())
        for fd in existing.file:
            files.setdefault(fd.name, fd)
    args.output.mkdir(parents=True, exist_ok=True)
    ordered = [files[key] for key in sorted(files)]
    combined = descriptor_pb2.FileDescriptorSet()
    combined.file.extend(ordered)
    (args.output / "descriptor-set.pb").write_bytes(combined.SerializeToString())
    for fd in ordered:
        stem = Path(fd.name).name.replace(".proto", "") if fd.name else "unknown"
        (args.output / f"{stem}.proto").write_text(emit_proto(fd), encoding="utf-8")
    print(f"WROTE {args.output} files={len(ordered)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
