"""Task Ingress (CODE_STRUCTURE §3 tasks/corpus.py): load and hash public tasks, sample batches.

This module never opens the holdout directory; evaluation.py is its only reader (JC-36).
"""
import fnmatch
import json
from dataclasses import dataclass
from pathlib import Path

from . import canonical

TASK_KEYS = {"id", "distribution", "prompt", "editable_paths", "test_command"}
OPTIONAL_KEYS = {"difficulty"}
# Difficulty tiers (operator metadata only; never shown to a model):
#   plain    the prompt states the wrong and the right output
#   symptom  the prompt gives only the symptom
#   indirect the bug sits in a helper that the named function calls
DIFFICULTIES = ("plain", "symptom", "indirect")


class CorpusError(Exception):
    pass


@dataclass(frozen=True)
class Task:
    id: str
    distribution: str
    prompt: str
    editable_paths: tuple
    test_command: tuple
    root: Path
    difficulty: str = "plain"

    @property
    def repo_dir(self) -> Path:
        return self.root / "repo"

    @property
    def tests_dir(self) -> Path:
        return self.root / "tests"

    def editable_files(self) -> list[str]:
        files = [p.relative_to(self.repo_dir).as_posix() for p in self.repo_dir.rglob("*") if p.is_file()]
        return sorted(f for f in files if any(fnmatch.fnmatchcase(f, pat) for pat in self.editable_paths))


def load_task(root: Path) -> Task:
    root = Path(root)
    try:
        meta = json.loads((root / "task.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CorpusError(f"{root}: cannot read task.json ({e})") from e
    if not TASK_KEYS <= set(meta) <= TASK_KEYS | OPTIONAL_KEYS:
        raise CorpusError(f"{root}: task.json keys {sorted(meta)}: need {sorted(TASK_KEYS)}, "
                          f"optional {sorted(OPTIONAL_KEYS)}")
    if meta.get("difficulty", "plain") not in DIFFICULTIES:
        raise CorpusError(f"{root}: difficulty must be one of {', '.join(DIFFICULTIES)}")
    for key in ("id", "distribution", "prompt"):
        if not isinstance(meta[key], str) or not meta[key]:
            raise CorpusError(f"{root}: {key} must be a non-empty string")
    for key in ("editable_paths", "test_command"):
        if not isinstance(meta[key], list) or not meta[key] or not all(isinstance(x, str) for x in meta[key]):
            raise CorpusError(f"{root}: {key} must be a non-empty list of strings")
    if meta["id"] != root.name:
        raise CorpusError(f"{root}: id {meta['id']!r} does not match the directory name")
    if not (root / "repo").is_dir() or not (root / "tests").is_dir():
        raise CorpusError(f"{root}: needs repo/ and tests/")
    return Task(meta["id"], meta["distribution"], meta["prompt"], tuple(meta["editable_paths"]),
                tuple(meta["test_command"]), root, meta.get("difficulty", "plain"))


def load_tasks(directory: Path) -> list[Task]:
    directory = Path(directory)
    if not directory.is_dir():
        raise CorpusError(f"no task directory at {directory}")
    return [load_task(p) for p in sorted(directory.iterdir()) if p.is_dir()]


def load_public(corpus_dir: Path) -> list[Task]:
    return load_tasks(Path(corpus_dir) / "public")


def dir_hashes(root: Path) -> dict[str, str]:
    """sha256 of every file under root, keyed by its POSIX path relative to root."""
    root = Path(root)
    return {p.relative_to(root).as_posix(): canonical.sha256_hex(p.read_bytes())
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def manifest(tasks: list[Task]) -> dict:
    """Recorded in Genesis so a changed task is detectable (design §8)."""
    return {"tasks": {t.id: {"distribution": t.distribution, "files": dir_hashes(t.root)} for t in tasks}}


def sample(tasks: list[Task], k: int, rng) -> list[Task]:
    if not 0 < k <= len(tasks):
        raise CorpusError(f"batch size {k} must be between 1 and the {len(tasks)} public tasks")
    return sorted(rng.sample(tasks, k), key=lambda t: t.id)
