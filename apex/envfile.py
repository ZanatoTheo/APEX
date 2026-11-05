"""Read .env (run.py and tools/live_calls.py load it; tests never do).

The one parser for .env, so every tool reads it the same way:
- lines are `KEY=VALUE`, optionally prefixed with `export `; blank lines and `#` comment lines are skipped;
- a UTF-8 BOM and CR line endings are ignored (files saved on Windows);
- one pair of matching quotes around a value is removed, and the quoted text is kept as is;
- in an unquoted value, ` #` starts a comment (as in bash); a `#` with no space before it is part of the value;
- a key given twice keeps its last value (as in bash).
`load` skips empty values and never overrides a variable already in the environment, so the shell wins over the file.
"""
import os
import re
from pathlib import Path

_LINE = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*")


def read(path) -> dict[str, str]:
    """Parse `path` into {name: value} without touching os.environ. A missing file gives {}."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    values = {}
    for line in text.splitlines():
        line = line.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _LINE.fullmatch(line)
        if not m:
            continue
        key, value = m.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


def load(path) -> list[str]:
    """Set the variables from `path` that aren't set yet; return their names (never their values)."""
    names = []
    for key, value in read(path).items():
        if not value or key in os.environ:
            continue
        os.environ[key] = value
        names.append(key)
    return names
