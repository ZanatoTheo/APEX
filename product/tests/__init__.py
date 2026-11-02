import tempfile
from pathlib import Path

# Keep every temporary file inside the prototype (the workspace is frozen to APEX/).
_TMP = Path(__file__).resolve().parent.parent / ".tmp"
_TMP.mkdir(exist_ok=True)
tempfile.tempdir = str(_TMP)
