"""
English must behave exactly as it did before Spanish was added.

golden/en.json is what the six text tools printed for the battery in en_battery.py when
they were the untouched upstream scripts (commit a6fb7a4 of this repository, upstream main
at d03c56b). This replays the battery against today's scripts and demands the same exit
codes, stdout, stderr and output files, character for character.

If this fails after a deliberate change to English behaviour, that is a decision to take on
purpose: do not regenerate the golden file from edited scripts (see make_golden.py).
"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.abspath(os.path.join(HERE, "..", "..", ".claude", "skills"))
sys.path.insert(0, HERE)

import en_battery  # noqa: E402


class EnglishUnchanged(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "golden", "en.json"), encoding="utf-8") as fh:
            cls.golden = json.load(fh)
        cls.current = en_battery.transcript(SKILLS)

    def test_same_cases(self):
        self.assertEqual(sorted(self.golden), sorted(self.current))
        self.assertGreaterEqual(len(self.golden), 30)

    def test_every_case_is_identical(self):
        for name, expected in self.golden.items():
            with self.subTest(case=name):
                self.assertEqual(expected, self.current[name])

    def test_english_json_has_no_language_key(self):
        """Spanish adds a "lang" key. English output must never carry one."""
        for name, entry in self.current.items():
            if "--json" in name or name.endswith("-json"):
                with self.subTest(case=name):
                    self.assertNotIn('"lang"', entry["stdout"])


if __name__ == "__main__":
    unittest.main()
