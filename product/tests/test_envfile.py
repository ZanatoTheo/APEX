"""apex/envfile.py: loading product/.env without overriding the real environment."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apex import envfile


class EnvFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / ".env"
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for name in ("APEX_T_A", "APEX_T_B", "APEX_T_C", "APEX_T_D", "APEX_T_E", "APEX_T_EMPTY", "APEX_T_SET"):
            os.environ.pop(name, None)

    def write(self, text: str):
        self.path.write_text(text, encoding="utf-8")

    def test_parses_values_comments_quotes_and_export(self):
        self.write("# comment\n\nAPEX_T_A=plain\nexport APEX_T_B=exported\nAPEX_T_C='single quoted'\n"
                   'APEX_T_D="double # not a comment"\n  APEX_T_E = spaced  \n')
        names = envfile.load(self.path)
        self.assertEqual(names, ["APEX_T_A", "APEX_T_B", "APEX_T_C", "APEX_T_D", "APEX_T_E"])
        self.assertEqual(os.environ["APEX_T_A"], "plain")
        self.assertEqual(os.environ["APEX_T_B"], "exported")
        self.assertEqual(os.environ["APEX_T_C"], "single quoted")
        self.assertEqual(os.environ["APEX_T_D"], "double # not a comment")
        self.assertEqual(os.environ["APEX_T_E"], "spaced")

    def test_empty_values_are_skipped(self):
        self.write("APEX_T_EMPTY=\nAPEX_T_A=x\n")
        self.assertEqual(envfile.load(self.path), ["APEX_T_A"])
        self.assertNotIn("APEX_T_EMPTY", os.environ)

    def test_never_overrides_the_environment(self):
        os.environ["APEX_T_SET"] = "from shell"
        self.write("APEX_T_SET=from file\n")
        self.assertEqual(envfile.load(self.path), [])
        self.assertEqual(os.environ["APEX_T_SET"], "from shell")

    def test_bad_lines_are_ignored(self):
        self.write("not a pair\n1BAD=x\nAPEX T=x\n=x\nAPEX_T_A=ok\n")
        self.assertEqual(envfile.load(self.path), ["APEX_T_A"])

    def test_bom_and_crlf(self):
        self.path.write_bytes("﻿APEX_T_A=first\r\nAPEX_T_B=second\r\n".encode("utf-8"))
        self.assertEqual(envfile.load(self.path), ["APEX_T_A", "APEX_T_B"])
        self.assertEqual((os.environ["APEX_T_A"], os.environ["APEX_T_B"]), ("first", "second"))

    def test_inline_comment_on_unquoted_value(self):
        self.write("APEX_T_A=value # a note\nAPEX_T_B=a#b\nAPEX_T_C='quoted # kept'\n")
        envfile.load(self.path)
        self.assertEqual(os.environ["APEX_T_A"], "value")
        self.assertEqual(os.environ["APEX_T_B"], "a#b")          # no space before '#': part of the value (as bash)
        self.assertEqual(os.environ["APEX_T_C"], "quoted # kept")

    def test_last_value_wins(self):
        self.write("APEX_T_A=one\nAPEX_T_A=two\n")
        self.assertEqual(envfile.load(self.path), ["APEX_T_A"])
        self.assertEqual(os.environ["APEX_T_A"], "two")

    def test_read_does_not_touch_the_environment(self):
        self.write("APEX_T_A=x\n")
        self.assertEqual(envfile.read(self.path), {"APEX_T_A": "x"})
        self.assertNotIn("APEX_T_A", os.environ)

    def test_missing_file(self):
        self.assertEqual(envfile.load(self.path), [])


if __name__ == "__main__":
    unittest.main()
