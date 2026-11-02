"""Test runner executed inside a workspace: `python3 testrunner.py <tests dir>` from the workspace root.

It runs unittest discovery and reports with one line, `APEX-RESULT <nonce> {"passed": n, "total": m}`.
The nonce arrives in an environment variable that is removed before any test code is imported, and the
process ends with os._exit, so atexit hooks in agent code cannot print after the real result. Code under
test still runs in this process and could tamper with unittest itself; that is accepted for the prototype (JC-33).
"""
import json
import os
import sys
import unittest


def main() -> None:
    nonce = os.environ.pop("APEX_RESULT_NONCE", "")
    start = sys.argv[1] if len(sys.argv) > 1 else "tests"
    sys.path.insert(0, os.getcwd())                       # so tests can import src.<module>
    try:
        suite = unittest.defaultTestLoader.discover(start, pattern="test*.py")
        result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
        bad = len(result.failures) + len(result.errors) + len(result.unexpectedSuccesses)
        payload = {"passed": result.testsRun - bad, "total": result.testsRun}
    except BaseException as e:                            # collection itself crashed
        print(f"test discovery failed: {type(e).__name__}: {e}", file=sys.stderr)
        payload, bad = {"passed": 0, "total": 0}, 1
    sys.stdout.flush()
    sys.stderr.flush()
    os.write(1, f"\nAPEX-RESULT {nonce} {json.dumps(payload)}\n".encode())
    os._exit(0 if bad == 0 and payload["total"] else 1)


if __name__ == "__main__":
    main()
