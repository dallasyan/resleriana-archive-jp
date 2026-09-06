#!/usr/bin/env python3
"""Regression tests for complete-collection profile transformations."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
