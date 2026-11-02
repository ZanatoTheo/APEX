import json
import tempfile
import unittest
from pathlib import Path

from apex import corpus, sandbox
from apex.sandbox import Limits, Workspace, parse_unittest, patch_problems

PROTO = Path(__file__).resolve().parent.parent
TASK = corpus.load_task(PROTO / "corpus" / "public" / "obo_window_sum")
FIX = (PROTO / "oracle" / "obo_window_sum.diff").read_text()


def edit_diff(path, old="x = 1", new="x = 2"):
    return f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-{old}\n+{new}\n"


class PatchPolicyTest(unittest.TestCase):
    def assertRejected(self, diff, fragment):
        _, problems = patch_problems(diff, TASK.editable_paths)
        self.assertTrue(any(fragment in p for p in problems), problems)

    def test_rejects_tests_dir(self):
        self.assertRejected(edit_diff("tests/test_window.py"), "denied path")

    def test_rejects_root_and_nested_conftest(self):
        self.assertRejected(edit_diff("conftest.py"), "denied path")
        self.assertRejected(edit_diff("src/conftest.py"), "denied path")   # matches src/*.py but is denied
        self.assertRejected(edit_diff("src/deep/sitecustomize.py"), "denied path")
        self.assertRejected(edit_diff("src/evil.pth"), "denied path")

    def test_rejects_rename_and_mode_and_binary(self):
        rename = ("diff --git a/src/window.py b/src/w2.py\nsimilarity index 100%\n"
                  "rename from src/window.py\nrename to src/w2.py\n")
        self.assertRejected(rename, "forbidden hunk")
        self.assertRejected("diff --git a/src/window.py b/src/window.py\nold mode 100644\nnew mode 120000\n",
                            "forbidden hunk")
        self.assertRejected("Binary files a/src/x.py and b/src/x.py differ\n", "forbidden hunk")

    def test_rejects_unprefixed_and_quoted_paths(self):
        # git apply -p1 would turn "src/tests/test_window.py" into "tests/test_window.py".
        self.assertRejected("--- src/tests/test_window.py\n+++ src/tests/test_window.py\n@@ -1 +1 @@\n-a\n+b\n",
                            "must start with a/ or b/")
        self.assertRejected('--- "a/src/window.py"\n+++ "b/src/window.py"\n@@ -1 +1 @@\n-a\n+b\n', "quoted path")
        self.assertRejected("diff --git a/tests/test_window.py b/tests/test_window.py\n", "denied path")

    def test_rejects_outside_editable_and_unsafe_paths(self):
        self.assertRejected(edit_diff("README.md"), "outside editable_paths")
        self.assertRejected(edit_diff("src/../tests/x.py"), "unsafe path")
        self.assertRejected("--- /dev/null\n+++ b/src/new.py\n@@ -0,0 +1 @@\n+x\n", "creating or deleting")
        self.assertRejected("", "empty patch")
        self.assertRejected("just prose, no headers", "no file headers")

    def test_accepts_oracle_fix(self):
        paths, problems = patch_problems(FIX, TASK.editable_paths)
        self.assertEqual((paths, problems), (["src/window.py"], []))


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fix_applies_and_diff_round_trips(self):
        with Workspace.for_task(TASK, self.work) as ws:
            self.assertEqual(ws.run_tests().status, "fail")
            self.assertEqual(ws.write_patch(FIX).status, "applied")
            self.assertEqual(ws.run_tests().status, "pass")
            self.assertEqual(ws.diff(), FIX)
            self.assertEqual(ws.tests_hash(), ws.original_tests_hash)

    def test_patch_that_does_not_apply_is_rejected(self):
        with Workspace.for_task(TASK, self.work) as ws:
            r = ws.write_patch(edit_diff("src/window.py", "no such line", "x"))
            self.assertEqual(r.status, "rejected")
            self.assertIn("does not apply", r.output)
            self.assertEqual(ws.diff(), "")

    def test_read_file_stays_inside_workspace(self):
        with Workspace.for_task(TASK, self.work) as ws:
            self.assertEqual(ws.read_file("src/window.py").status, "ok")
            self.assertEqual(ws.read_file("tests/test_window.py").status, "ok")
            for bad in ("../ledger.sqlite", "/etc/passwd", "src/../../x", "nope.py", "", None):
                self.assertEqual(ws.read_file(bad).status, "error", bad)

    def test_tests_are_read_only(self):
        with Workspace.for_task(TASK, self.work) as ws:
            with self.assertRaises(PermissionError):
                (ws.dir / "tests" / "test_window.py").write_text("")

    def test_fake_summary_from_agent_code_is_ignored(self):
        with Workspace.for_task(TASK, self.work) as ws:
            evil = ("import atexit, sys\n"
                    "print('APEX-RESULT guess {\"passed\": 3, \"total\": 3}')\n"
                    "atexit.register(lambda: print('Ran 3 tests in 0.0s\\n\\nOK', file=sys.stderr))\n")
            src = ws.dir / "src" / "window.py"
            src.write_text(evil + src.read_text())
            r = ws.run_tests()
            self.assertEqual(r.status, "fail")
            self.assertEqual(r.data, {"passed": 1, "total": 3})

    def test_tampered_tests_are_a_violation(self):
        with Workspace.for_task(TASK, self.work) as ws:
            t = ws.dir / "tests" / "test_window.py"
            t.parent.chmod(0o755)
            t.chmod(0o644)
            t.write_text("import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n")
            r = ws.run_tests()
            self.assertIn("tests modified", ws.violations)
            self.assertEqual(r.data["passed"], 0)

    def test_agent_workspace_has_no_hidden_tests(self):
        with Workspace.for_task(TASK, self.work) as ws:
            names = {p.name for p in ws.dir.rglob("*")}
        self.assertNotIn("test_window_hidden.py", names)

    def test_timeout_is_a_violation(self):
        root = self.work / "sleepy"
        (root / "repo" / "src").mkdir(parents=True)
        (root / "repo" / "src" / "m.py").write_text("x = 1\n")
        (root / "tests").mkdir()
        (root / "tests" / "test_sleep.py").write_text(
            "import time, unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        time.sleep(60)\n")
        (root / "task.json").write_text(json.dumps({
            "id": "sleepy", "distribution": "x", "prompt": "p", "editable_paths": ["src/*.py"],
            "test_command": ["python3", "-m", "unittest", "discover", "-s", "tests"]}))
        task = corpus.load_task(root)
        with Workspace.for_task(task, self.work / "w", Limits(timeout_s=1)) as ws:
            r = ws.run_tests()
            self.assertEqual(r.status, "timeout")
            self.assertEqual(ws.violations, ["timeout"])
            self.assertEqual(r.data["passed"], 0)


class ParseTest(unittest.TestCase):
    def test_parse_unittest_summaries(self):
        self.assertEqual(parse_unittest("...\nRan 3 tests in 0.001s\n\nOK\n"), (3, 3))
        self.assertEqual(parse_unittest("Ran 3 tests in 0.0s\n\nFAILED (failures=1, errors=1)\n"), (1, 3))
        self.assertEqual(parse_unittest("Ran 1 test in 0.0s\n\nOK (skipped=1)\n"), (1, 1))
        self.assertEqual(parse_unittest("Traceback ... no summary"), (0, 0))

    def test_truncate_keeps_head_and_tail(self):
        text = "a" * 20000 + "TAIL"
        out = sandbox._truncate(text, 1000)
        self.assertTrue(out.startswith("a") and out.endswith("TAIL") and len(out) < 1100)


if __name__ == "__main__":
    unittest.main()
