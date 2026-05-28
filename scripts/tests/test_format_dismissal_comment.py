"""Unit tests for format-dismissal-comment.py — verifies the 280-character
cap, run-URL preservation, and correct unicode-character (not byte) accounting."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _helpers import load  # noqa: E402


fmt = load("format-dismissal-comment.py")


RUN_URL = "https://github.com/infinum/android-sportino-3/actions/runs/12345678901"


class TestCompose(unittest.TestCase):
    def test_short_passes_through_with_suffix(self):
        result = fmt.compose(
            "Safe everywhere reachable — 19 occurrences, all in build tooling.",
            "Configs: foo, bar",
            RUN_URL,
        )
        self.assertIn("Safe everywhere reachable", result)
        self.assertIn("[Configs: foo, bar]", result)
        self.assertIn(f"(see {RUN_URL})", result)
        self.assertLessEqual(len(result), fmt.MAX_CHARS)

    def test_empty_detail_omits_brackets(self):
        result = fmt.compose("Short reason.", "", RUN_URL)
        self.assertNotIn("[", result)
        self.assertIn("Short reason.", result)
        self.assertIn(f"(see {RUN_URL})", result)

    def test_oversize_truncates_body_keeps_url(self):
        # 350-char reason guarantees truncation
        long_reason = "x" * 350
        result = fmt.compose(long_reason, "", RUN_URL)
        self.assertEqual(len(result), fmt.MAX_CHARS)
        # The URL must be intact for the audit trail
        self.assertIn(f"(see {RUN_URL})", result)
        # The truncation marker is present
        self.assertIn("…", result)

    def test_oversize_with_unicode_counts_characters_not_bytes(self):
        # Each em-dash is 3 bytes in UTF-8 but 1 character. We pad with em-dashes
        # to a length that would exceed MAX_CHARS in bytes but not in chars,
        # to confirm we're counting unicode characters.
        emdashes = "—" * 200  # 200 chars, 600 bytes
        result = fmt.compose(emdashes, "", RUN_URL)
        self.assertLessEqual(len(result), fmt.MAX_CHARS)
        # Make sure we're counting CHARS not bytes — the input is 200 chars
        # plus URL suffix (~52 chars) = ~252, under the 280 cap. So no
        # truncation should happen here even though byte length is 600+.
        self.assertNotIn("…", result)

    def test_truncation_does_not_break_multibyte_chars(self):
        # Heavy unicode input that forces truncation
        long_unicode = "—" * 350  # 350 chars, exceeds 280
        result = fmt.compose(long_unicode, "", RUN_URL)
        self.assertEqual(len(result), fmt.MAX_CHARS)
        # Every character before the suffix must be a valid em-dash or the
        # ellipsis — never a half-encoded byte
        body_part = result.split(" (see ")[0]
        for ch in body_part:
            self.assertIn(ch, "—…")

    def test_no_url_omits_suffix(self):
        result = fmt.compose("Just a reason.", "", "")
        self.assertEqual(result, "Just a reason.")

    def test_reason_and_detail_joined_with_brackets(self):
        result = fmt.compose("Primary part.", "extra info", "")
        self.assertIn("Primary part.", result)
        self.assertIn("[extra info]", result)


if __name__ == "__main__":
    unittest.main()
