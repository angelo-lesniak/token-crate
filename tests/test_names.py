"""The rules every manifest kind and every comma-separated list share."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tokencrate import TokenCrateError, names


class SharedRuleTests(unittest.TestCase):
    def test_a_list_is_lenient_about_spacing_and_repeats_and_strict_about_names(self) -> None:
        self.assertEqual(names.parse_list("", "thing"), [])
        self.assertEqual(names.parse_list(" a, b ,,a,c", "thing"), ["a", "b", "c"])
        with self.assertRaisesRegex(TokenCrateError, "unsafe thing name: '../x'"):
            names.parse_list("a,../x", "thing")
        with self.assertRaisesRegex(TokenCrateError, "unsafe thing name: 'A'"):
            names.parse_list("A", "thing", re.compile(r"^[a-z]+$"))

    def test_the_reader_words_the_three_manifest_failures_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.toml"
            path.write_text("schema = 1\nknown = 1\n", encoding="utf-8")
            self.assertEqual(names.read_toml(path, {"schema", "known"}, "x"), {"schema": 1, "known": 1})
            with self.assertRaisesRegex(TokenCrateError, r"^x: unknown key\(s\): known$"):
                names.read_toml(path, {"schema"}, "x")
            path.write_text("schema = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(TokenCrateError, "^x: schema must be 1$"):
                names.read_toml(path, {"schema"}, "x")
            path.write_text("not toml", encoding="utf-8")
            with self.assertRaisesRegex(TokenCrateError, r"^x: cannot read the manifest \("):
                names.read_toml(path, {"schema"}, "x")
            with self.assertRaisesRegex(TokenCrateError, "cannot read the manifest"):
                names.read_toml(Path(directory) / "missing.toml", {"schema"}, "x")

    def test_descriptions_and_relative_paths(self) -> None:
        self.assertEqual(names.description({"description": " one line "}, "x"), "one line")
        for value in (None, "", " ", "two\nlines", 3):
            with self.assertRaisesRegex(TokenCrateError, "x: description must be one non-empty line"):
                names.description({"description": value}, "x")
        self.assertEqual(names.relative_path("skills/demo-1.0+a@b", "path", "x"), "skills/demo-1.0+a@b")
        for value in ("/abs", "../up", "a/../b", ".", "a b", "a#b", "a/", "", None):
            with self.assertRaisesRegex(TokenCrateError, "x: path must be a relative path"):
                names.relative_path(value, "path", "x")


if __name__ == "__main__":
    unittest.main()
