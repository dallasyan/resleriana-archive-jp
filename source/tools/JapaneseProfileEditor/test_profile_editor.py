#!/usr/bin/env python3
"""Regression tests for complete-collection profile transformations."""

from __future__ import annotations

import sys
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


EDITOR_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(EDITOR_ROOT))

import profile_editor  # noqa: E402


MASTER_ROOT = EDITOR_ROOT.parents[1] / "resleriana-db-main" / "data" / "master" / "jp"


class CompleteCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = profile_editor.load_descriptor_pool(EDITOR_ROOT / "profile-descriptors.pb")

    def new_message(self):
        return profile_editor.parse_message(b"", self.pool)

    def test_complete_collection_populates_all_progression_states(self):
        message = self.new_message()
        stats = profile_editor.apply_complete_collection(message, MASTER_ROOT)

        self.assertEqual(len(message.resources.characters), 216)
        self.assertEqual(len(message.resources.memorias), 279)
        self.assertEqual(len(message.resources.communication_states), 23)
        self.assertEqual(len(message.resources.character_story_states), 62)
        self.assertEqual(stats[0], 216)
        self.assertEqual(stats[2], 279)
        self.assertEqual(stats[4], 23)
        self.assertEqual(stats[7], 62)

        characters = {character.character_id: character for character in message.resources.characters}
        evolved = characters[10101]
        self.assertEqual(evolved.rarity, 8)
        self.assertTrue(evolved.is_normal1_skill_evolved)
        self.assertTrue(evolved.is_normal2_skill_evolved)
        self.assertTrue(evolved.is_burst_skill_evolved)
        unevolved_rarity8 = characters[10199]
        self.assertEqual(unevolved_rarity8.rarity, 8)
        self.assertFalse(unevolved_rarity8.is_normal1_skill_evolved)
        self.assertFalse(unevolved_rarity8.is_normal2_skill_evolved)
        self.assertFalse(unevolved_rarity8.is_burst_skill_evolved)
        five_star = characters[10102]
        self.assertLess(five_star.rarity, 8)
        self.assertFalse(five_star.is_normal1_skill_evolved)
        self.assertFalse(five_star.is_normal2_skill_evolved)
        self.assertFalse(five_star.is_burst_skill_evolved)
        self.assertEqual(characters[10101].exp, 65212424)
        self.assertEqual(characters[10101].growboard_level_limit, 90)
        self.assertEqual(characters[10101].level_limit_increase_value, 10)
        self.assertEqual(characters[10101].growboard_current_page, 16)
        self.assertEqual(characters[10101].growboard_ex_current_page, 3)

        branch = next(
            state for state in message.resources.character_story_states
            if state.character_story_id == 6801002
        )
        self.assertEqual(branch.clear_count, 2)
        self.assertEqual(list(branch.condition_states), [2, 3])

        communication = next(
            state for state in message.resources.communication_states
            if state.character_id == 43101
        )
        self.assertEqual(list(communication.released_story_numbers), [1, 2, 3, 4, 5])
        self.assertEqual(list(communication.cleared_story_numbers), [1, 2, 3, 4, 5])
        self.assertEqual(communication.reward_scene_id.value, 1335101)

        max_memoria_exp = max(
            int(record["exp"])
            for record in profile_editor.load_master_records(MASTER_ROOT, "memoria_level")
        )
        self.assertTrue(all(memoria.exp == max_memoria_exp for memoria in message.resources.memorias))
        self.assertTrue(all(memoria.limit_break == 4 for memoria in message.resources.memorias))

    def test_existing_records_are_upgraded_without_duplicates(self):
        message = self.new_message()
        character = message.resources.characters.add()
        character.character_id = 10101
        character.rarity = 1
        character.exp = 0

        memoria = message.resources.memorias.add()
        memoria.entity_id = 1
        memoria.memoria_id = 10001
        memoria.exp = 0
        memoria.limit_break = 0

        story = message.resources.character_story_states.add()
        story.character_story_id = 6801002
        story.clear_count = 1
        story.condition_states.append(2)

        communication = message.resources.communication_states.add()
        communication.character_id = 43101
        communication.released_story_numbers.append(1)
        communication.cleared_story_numbers.append(1)

        first = profile_editor.apply_complete_collection(message, MASTER_ROOT)
        second = profile_editor.apply_complete_collection(message, MASTER_ROOT)

        self.assertEqual(len(message.resources.characters), 216)
        self.assertEqual(len(message.resources.memorias), 279)
        self.assertEqual(len(message.resources.character_story_states), 62)
        self.assertEqual(len(message.resources.communication_states), 23)
        self.assertGreater(first[1], 0)
        self.assertGreater(first[3], 0)
        self.assertGreater(first[5], 0)
        self.assertGreater(first[8], 0)
        self.assertEqual(second[0], 0)
        self.assertEqual(second[1], 0)
        self.assertEqual(second[2], 0)
        self.assertEqual(second[3], 0)
        self.assertEqual(second[4], 0)
        self.assertEqual(second[5], 0)
        self.assertEqual(second[7], 0)
        self.assertEqual(second[8], 0)


class ContractProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.fields_path = self.root / "fields.txt"
        self.fields_path.write_text(
            "\n".join(
                (
                    "message blend.api.UserLogInResponse (api/user.proto)",
                    "  Message resources = 1 (blend.model.Resources)",
                    "",
                    "message blend.model.Resources (model/resources.proto)",
                    "  Message profile = 39 (blend.model.Profile)",
                    "  Message quest_states = 22 (blend.model.QuestState)",
                    "  Message revived_events = 40 (blend.model.RevivedEvent)",
                    "",
                    "message blend.model.Profile (model/profile.proto)",
                    "  String name = 1 ()",
                    "  String memo = 2 ()",
                    "  Message favorite_party_character1_id = 4 (google.protobuf.Int32Value)",
                    "  Int32 favorite_battle_tool_entity_ids = 9 ()",
                    "  Enum test_ranks = 10 (blend.enum.profile_test.Rank)",
                    "",
                    "enum blend.enum.profile_test.Rank",
                    "  first = 0",
                    "  second = 1",
                    "",
                    "message google.protobuf.Int32Value (google/protobuf/wrappers.proto)",
                    "  Int32 value = 1 ()",
                    "",
                    "message blend.model.QuestState (model/quest_state.proto)",
                    "  Int32 quest_id = 1 ()",
                    "  Int32 clear_count = 2 ()",
                    "",
                    "message blend.model.RevivedEvent (model/revived_event.proto)",
                    "  Int32 event_id = 1 ()",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        self.db = profile_editor.load_contract_db(self.fields_path)

    def profile_wire(self):
        message = {
            "$message": "blend.api.UserLogInResponse",
            "resources": {
                "$message": "blend.model.Resources",
                "profile": {
                    "$message": "blend.model.Profile",
                    "name": "Before",
                    "favorite_party_character1_id": {
                        "$message": "google.protobuf.Int32Value",
                        "value": 8,
                    },
                    "favorite_battle_tool_entity_ids": [10],
                    "test_ranks": {"$packed": [1, 0]},
                },
                "quest_states": [
                    {"$message": "blend.model.QuestState", "quest_id": 11, "clear_count": 1}
                ],
                "revived_events": [
                    {"$message": "blend.model.RevivedEvent", "event_id": 5}
                ],
            },
        }
        return profile_editor.contract_codec.encode_message(
            self.db,
            profile_editor.TOP_LEVEL_MESSAGE,
            message,
        )

    def test_contract_edits_wrappers_repeated_fields_and_unknown_wire_data(self):
        unknown = profile_editor.contract_codec._write_varint((200 << 3) | 0)
        unknown += profile_editor.contract_codec._write_varint(17)
        payload = self.profile_wire() + unknown
        message = profile_editor.parse_contract_message(payload, self.db)

        profile_editor.apply_contract_set(self.db, message, "resources.profile.name=Offline Player")
        profile_editor.apply_contract_set(
            self.db,
            message,
            "resources.profile.favorite_party_character1_id.value=55",
        )
        profile_editor.apply_contract_set(
            self.db,
            message,
            "resources.profile.favorite_battle_tool_entity_ids[0]=73",
        )
        profile_editor.apply_contract_set(
            self.db,
            message,
            "resources.profile.test_ranks[1]=second",
        )

        encoded = profile_editor.contract_codec.encode_message(
            self.db,
            profile_editor.TOP_LEVEL_MESSAGE,
            message,
        )
        decoded = profile_editor.parse_contract_message(encoded, self.db)
        edited_profile = decoded["resources"]["profile"]
        self.assertEqual(edited_profile["name"], "Offline Player")
        self.assertEqual(edited_profile["favorite_party_character1_id"]["value"], 55)
        self.assertEqual(edited_profile["favorite_battle_tool_entity_ids"], 73)
        self.assertEqual(edited_profile["test_ranks"], {"$packed": [1, 1]})
        self.assertEqual(decoded["unknown"], [{"number": 200, "wire": 0, "hex": "17"}])

    def test_contract_state_manifest_upserts_without_duplicate_records(self):
        message = profile_editor.parse_contract_message(self.profile_wire(), self.db)
        manifest_path = self.root / "states.json"
        manifest_path.write_text(
            json.dumps({"quest_states": {"11": 3, "12": 2}, "revived_events": [5, 6]}),
            encoding="utf-8",
        )

        added_quests, added_events = profile_editor.apply_contract_state_file(
            self.db,
            message,
            manifest_path,
        )

        resources = message["resources"]
        self.assertEqual((added_quests, added_events), (1, 1))
        self.assertEqual(
            [(state["quest_id"], state["clear_count"]) for state in resources["quest_states"]],
            [(11, 3), (12, 2)],
        )
        self.assertEqual([event["event_id"] for event in resources["revived_events"]], [5, 6])

    def test_edit_command_uses_latest_contract_and_preserves_unknown_fields(self):
        latest_fields = profile_editor.default_contract_fields_path()
        latest_db = profile_editor.load_contract_db(latest_fields)
        message = {
            "$message": profile_editor.TOP_LEVEL_MESSAGE,
            "resources": {
                "$message": "blend.model.Resources",
                "profile": {
                    "$message": "blend.model.Profile",
                    "name": "Before",
                },
            },
        }
        protobuf_data = profile_editor.contract_codec.encode_message(
            latest_db,
            profile_editor.TOP_LEVEL_MESSAGE,
            message,
        )
        protobuf_data += profile_editor.contract_codec._write_varint((200 << 3) | 0)
        protobuf_data += profile_editor.contract_codec._write_varint(17)
        marker = 37
        profile_path = self.root / "profile.bin"
        output_path = self.root / "profile-edited.bin"
        profile_path.write_bytes(
            profile_editor.encrypt_profile(
                protobuf_data,
                profile_editor.JAPANESE_AES_KEYS[marker],
                profile_editor.JAPANESE_AES_IV,
                marker,
            )
        )

        with patch(
            "sys.argv",
            [
                "profile_editor.py",
                "edit",
                str(profile_path),
                str(output_path),
                "--contract-fields",
                str(latest_fields),
                "--set",
                "resources.profile.name=Edited",
            ],
        ):
            self.assertEqual(profile_editor.main(), 0)

        edited_plaintext, edited_marker, _, _ = profile_editor.decrypt_with_candidates(
            output_path.read_bytes(),
            [profile_editor.SHARE_PROFILE_KEY],
            [profile_editor.SHARE_PROFILE_IV],
        )
        edited_message = profile_editor.parse_contract_message(edited_plaintext, latest_db)
        self.assertEqual(edited_marker, marker)
        self.assertEqual(edited_message["resources"]["profile"]["name"], "Edited")
        self.assertEqual(edited_message["unknown"], [{"number": 200, "wire": 0, "hex": "17"}])

    def test_bundled_editor_loads_its_contract_schema(self):
        executable = EDITOR_ROOT / "dist" / "ProfileEditor.exe"
        if not executable.is_file():
            self.skipTest("bundled ProfileEditor.exe has not been built")
        latest_fields = profile_editor.default_contract_fields_path()
        latest_db = profile_editor.load_contract_db(latest_fields)
        message = {
            "$message": profile_editor.TOP_LEVEL_MESSAGE,
            "resources": {
                "$message": "blend.model.Resources",
                "profile": {
                    "$message": "blend.model.Profile",
                    "name": "Bundled Test",
                },
            },
        }
        protobuf_data = profile_editor.contract_codec.encode_message(
            latest_db,
            profile_editor.TOP_LEVEL_MESSAGE,
            message,
        )
        marker = 61
        profile_path = self.root / "bundled-profile.bin"
        json_path = self.root / "bundled-profile.json"
        profile_path.write_bytes(
            profile_editor.encrypt_profile(
                protobuf_data,
                profile_editor.JAPANESE_AES_KEYS[marker],
                profile_editor.JAPANESE_AES_IV,
                marker,
            )
        )

        completed = subprocess.run(
            [str(executable), "export", str(profile_path), str(json_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertIn("wrote", completed.stdout)
        exported = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(exported["resources"]["profile"]["name"], "Bundled Test")


if __name__ == "__main__":
    unittest.main()
