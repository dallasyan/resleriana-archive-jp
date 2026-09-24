"""Create a synthetic pre-tutorial starter profile from a fresh signup capture."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def locate_profile_editor() -> Path:
    for parent in Path(__file__).resolve().parents:
        for name in ("JapaneseProfileEditor", "profile-editor"):
            candidate = parent / name
            if (candidate / "profile_editor.py").is_file():
                return candidate
    raise FileNotFoundError("could not locate profile_editor.py")


PROFILE_EDITOR = locate_profile_editor()
sys.path.insert(0, str(PROFILE_EDITOR))
import profile_editor  # noqa: E402

STARTER_CREATED_AT = datetime(2026, 9, 24, tzinfo=timezone.utc)


def sanitize_starter_profile(
    encrypted_profile: bytes,
    player_name: str = "Offline",
) -> tuple[bytes, int]:
    if not player_name.strip():
        raise ValueError("starter profile name must not be empty")
    plaintext, marker, key, iv = profile_editor.decrypt_with_candidates(encrypted_profile, [], [])
    pool = profile_editor.load_descriptor_pool(PROFILE_EDITOR / "profile-descriptors.pb")
    message = profile_editor.parse_message(plaintext, pool)
    if message.resources.status.tutorial_step != 0 or message.resources.status.rank != 1:
        raise ValueError("input profile is not a fresh pre-tutorial profile")
    if len(message.resources.characters) != 1:
        raise ValueError("input profile must contain the fresh signup starter character only")

    profile = message.resources.profile
    profile.name = player_name
    profile.memo = ""
    message.resources.status.ClearField("birth_year")
    message.resources.status.ClearField("birth_month")
    message.created_at.seconds = int(STARTER_CREATED_AT.timestamp())
    message.created_at.nanos = 0

    sanitized = message.SerializeToString()
    return profile_editor.encrypt_profile(sanitized, key, iv, marker), marker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="encrypted profile.bin from a new, pre-tutorial signup")
    parser.add_argument("output", type=Path, help="destination for the synthetic starter-profile.bin")
    parser.add_argument("--name", default="Offline", help="synthetic in-game display name")
    parser.add_argument("--force", action="store_true", help="replace an existing output file")
    args = parser.parse_args()

    source = args.input.resolve()
    destination = args.output.resolve()
    if source == destination:
        parser.error("input and output must be different files")
    if destination.exists() and not args.force:
        parser.error("output already exists; pass --force to replace it")

    encrypted, marker = sanitize_starter_profile(source.read_bytes(), args.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_bytes(encrypted)
    temporary.replace(destination)
    print(f"WROTE synthetic pre-tutorial profile marker={marker} bytes={len(encrypted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
