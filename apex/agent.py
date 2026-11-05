"""An agent's state and folder. It does not run anything: call_agent does.

Folder: axioms.md, notes.md, the connector's starter files and data file. axioms.md is read-only to the agent: Op.
Orch and Mutation set its axioms, and an agent changing them would hide what is being tested.
The log is outside the folder, at <logs_root>/<id>.jsonl: it holds released data, and after the wrap back to the
first step an agent reading it would know the whole loop.
"""
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .tools.files import PROTECTED, cut

_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
INTERPRETATION = "interpretation.md"
INTERPRETATION_HEADER = ("# Interpretation of my axioms\n(Empty. For each axis: what your axiom means in practice: "
                         "the concrete signals, formulas and parameters, and where your code applies them.)\n")
def interpretation_stub(axioms: str) -> str:
    """interpretation.md as a new agent gets it: one "## <axis>" section per heading of its axioms."""
    heads = [line[3:].strip() for line in axioms.splitlines() if line.startswith("## ")]
    if not heads:
        return INTERPRETATION_HEADER
    return ("# Interpretation of my axioms\nOne section per axiom: what it means in practice (the concrete signals, "
            "formulas and parameters) and where your code applies it. This file is your own memory: edit it as you "
            "learn.\n\n" + "\n\n".join(f"## {h}\n(empty)" for h in heads) + "\n")


DATA_HEADER = "# Data facts\nFacts about the task's data go here and only here. This file is deleted at each cycle end.\n"


def _decode_head(raw: bytes, was_cut: bool) -> str:
    """UTF-8 text, or "(binary, N bytes)". A read window that ends inside a character is not binary."""
    for drop in (range(4) if was_cut else range(1)):
        try:
            return raw[: len(raw) - drop].decode("utf-8")
        except UnicodeDecodeError:
            continue
    return f"(binary, {len(raw)}+ bytes)" if was_cut else f"(binary, {len(raw)} bytes)"


def _safe_rel(rel) -> bool:
    """A plain relative path inside the folder that isn't a protected name."""
    if not isinstance(rel, str) or not rel.strip():
        return False
    pp = PurePosixPath(rel)
    return not pp.is_absolute() and ".." not in pp.parts and pp.as_posix() not in PROTECTED


@dataclass
class Agent:
    id: str
    dir: Path
    log_path: Path
    axioms: str
    data_file: str = "data.md"
    generation: int = 0
    parents: list = field(default_factory=list)

    @classmethod
    def create(cls, agents_root, logs_root, agent_id: str, axioms: str, files: dict, data_file: str = "data.md",
               generation: int = 0, parents=()) -> "Agent":
        if not isinstance(agent_id, str) or not _ID.fullmatch(agent_id):
            raise ValueError(f"bad agent id {agent_id!r}: use 1-40 of a-z, 0-9 and -")
        folder = Path(agents_root) / agent_id
        log_path = Path(logs_root) / f"{agent_id}.jsonl"
        if folder.exists() or log_path.exists():
            raise ValueError(f"agent {agent_id} already has a folder or a log: ids are unique in a run")
        if not _safe_rel(data_file):
            raise ValueError(f"bad data file name {data_file!r}")
        checked = {}
        for rel, content in dict(files).items():
            if not _safe_rel(rel) or not isinstance(content, str):
                raise ValueError(f"bad starter file {rel!r}")
            checked[PurePosixPath(rel).as_posix()] = content
        folder.mkdir(parents=True)
        for rel, content in checked.items():
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / rel).write_text(content)
        (folder / "axioms.md").write_text(axioms)
        if "notes.md" not in checked:
            (folder / "notes.md").write_text("")
        if INTERPRETATION not in checked:
            (folder / INTERPRETATION).write_text(interpretation_stub(axioms))
        if data_file not in checked:
            (folder / data_file).write_text(DATA_HEADER)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("")
        return cls(agent_id, folder, log_path, axioms, data_file, generation, list(parents))

    def files_text(self, max_chars: int, skip=("axioms.md",)) -> str:
        """Every regular file of the folder as '=== path ===\n<text>', cut to max_chars in all."""
        parts, total = [], 0
        for dirpath, _dirs, names in sorted(os.walk(self.dir, followlinks=False)):
            for name in sorted(names):
                full = Path(dirpath) / name
                rel = full.relative_to(self.dir).as_posix()
                if rel in skip or full.is_symlink() or not full.is_file():
                    continue
                try:
                    with open(full, "rb") as f:
                        raw = f.read(max_chars * 4 + 4)
                    body = _decode_head(raw, full.stat().st_size > len(raw))
                except OSError as e:
                    body = f"(unreadable: {e.strerror})"
                part = f"=== {rel} ===\n{body}"
                parts.append(part)
                total += len(part)
                if total >= max_chars:                # stop the whole walk, not just this folder
                    return cut("\n\n".join(parts), max_chars)
        return cut("\n\n".join(parts), max_chars)

    def work_files(self, max_chars: int, max_total: int | None = None, skipped: list | None = None) -> dict:
        """{path: text} of the folder's regular UTF-8 files, for a child agent to start from: each up to
        max_chars, all together up to max_total (default 10 x max_chars). Protected files and links are left
        out; anything else left out is named in `skipped` with the reason."""
        max_total = max_total if max_total is not None else max_chars * 10
        skipped = skipped if skipped is not None else []
        out, total = {}, 0
        for dirpath, dirs, names in os.walk(self.dir, followlinks=False):
            dirs.sort()
            for name in sorted(names):
                full = Path(dirpath) / name
                rel = full.relative_to(self.dir).as_posix()
                if not _safe_rel(rel) or full.is_symlink() or not full.is_file():
                    continue
                try:
                    if full.stat().st_size > max_chars * 4:
                        skipped.append(f"{rel}: too big")
                        continue
                    text = full.read_bytes().decode("utf-8")
                except UnicodeDecodeError:
                    skipped.append(f"{rel}: not UTF-8 text")
                    continue
                except OSError as e:
                    skipped.append(f"{rel}: {e.strerror}")
                    continue
                if len(text) > max_chars:
                    skipped.append(f"{rel}: too big")
                elif total + len(text) > max_total:
                    skipped.append(f"{rel}: over the total for a child's files")
                else:
                    out[rel] = text
                    total += len(text)
        return out

    def step_summaries(self, limit: int = 20) -> list[dict]:
        """The last `limit` steps as {step, ended_by, summary}, from the log's end events."""
        out = []
        try:
            lines = self.log_path.read_text(errors="replace").splitlines()
        except OSError:
            return out
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("event") == "end":
                out.append({"step": e.get("step"), "ended_by": e.get("ended_by"), "summary": e.get("summary")})
        return out[-limit:]

    def log(self, entry: dict) -> None:
        line = json.dumps(entry, default=str) + "\n"
        fd = os.open(self.log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
