"""The cleaner: removes facts about the task's data from agents' files between cycles.

After the last cycle the operation wraps back to the first step, so an agent that kept data in its files would know
the future. For every agent entering the next cycle, in order:
1. it makes the agent's tree readable and writable to itself (a script may have chmod-ed things);
2. it deletes the data file (and any other name for it);
3. it deletes entries that are data as a whole: names or link targets matching a pattern, special files, files with
   several hard links, files that are not UTF-8, too big, matching the connector's file_globs, or dense with pattern
   matches (axioms.md is never deleted whole);
4. it replaces each pattern match with a marker [cleaned <id>];
5. a small model finds further facts (verbatim quotes, never overlapping a marker), replaced the same way.
Every deletion is logged with its original (whole files as blobs) under <run>/hidden/cleaner/, outside every agent
folder, so Op. Orch can undo it. What can't be removed is logged and raised as CleanerError: data never survives
silently.
"""
import fnmatch
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

from . import prompts
from .budget import CapReached
from .jsonreply import ask_json
from .tools.files import ToolError, Workspace

_AXIOMS = "axioms.md"
_MARKER = re.compile(r"\[cleaned c\d+-\d{4,}\]")
_ID = re.compile(r"c(\d+)-(\d+)")


class CleanerError(Exception):
    """An undo was refused, or something could not be cleaned."""


def _read_bytes(path, limit: int | None = None) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"{path} is not a regular file")
        chunks, size = [], 0
        while limit is None or size <= limit:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _write_text(path, text: str) -> None:
    """Rewrite an existing regular file in place, never through a link. Host-side: no agent size cap."""
    fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"{path} is not a regular file")
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def _spans(text: str, patterns) -> list[tuple[int, int]]:
    """Every non-empty match of every pattern, overlaps merged, left to right."""
    raw = sorted((m.start(), m.end()) for p in patterns for m in p.finditer(text) if m.end() > m.start())
    merged = []
    for start, end in raw:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _free_at(text: str, quote: str, start: int = 0) -> int:
    """The first occurrence of `quote` at or after `start` that doesn't touch a marker, or -1."""
    markers = [(m.start(), m.end()) for m in _MARKER.finditer(text)]
    idx = text.find(quote, start)
    while idx != -1:
        end = idx + len(quote)
        if not any(s < end and idx < e for s, e in markers):
            return idx
        idx = text.find(quote, idx + 1)
    return -1


def _compiles(text: str) -> bool:
    try:
        compile(text, "<agent file>", "exec")
        return True
    except (SyntaxError, ValueError):
        return False


class Cleaner:
    def __init__(self, cfg: dict, budget, model, hidden_dir):
        self.cfg, self.budget, self.model = cfg, budget, model
        self.c = cfg["cleaner"]
        self.dir = Path(hidden_dir) / "cleaner"
        self.blobs = self.dir / "blobs"
        self.records: dict[str, dict] = {}
        self.undone: set[str] = set()
        self.counters: dict[int, int] = {}
        self._load()

    # ---- log ------------------------------------------------------------------------------------------------
    def _load(self) -> None:
        """Pick up an earlier instance's log, so ids stay unique in a run and its deletions can be undone."""
        path = self.dir / "deletions.jsonl"
        if not path.exists():
            return
        for line in path.read_text(errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            if e.get("event") == "deletion" and isinstance(e.get("id"), str):
                self.records[e["id"]] = e
                m = _ID.fullmatch(e["id"])
                if m:
                    cyc, n = int(m.group(1)), int(m.group(2))
                    self.counters[cyc] = max(self.counters.get(cyc, 0), n)
            elif e.get("event") == "undo":
                self.undone.add(e.get("id"))

    def _event(self, entry: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / "deletions.jsonl", "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def _next_id(self, cycle: int) -> str:
        n = self.counters.get(cycle, 0) + 1
        self.counters[cycle] = n
        return f"c{cycle}-{n:04d}"

    def _rec(self, did, cycle, agent, rel, kind, source, reason, original, undoable=True) -> dict:
        rec = {"event": "deletion", "id": did, "cycle": cycle, "agent": agent.id, "agent_dir": str(agent.dir),
               "file": rel, "kind": kind, "source": source, "reason": reason,
               "marker": f"[cleaned {did}]" if kind == "span" else None, "broke_code": False,
               "original": original, "undoable": undoable}
        self.records[did] = rec
        return rec

    # ---- whole entries --------------------------------------------------------------------------------------
    def _delete_whole(self, s, rel, full, source, reason, kind="whole_file") -> None:
        """Copy a regular file to a blob (in chunks, never overwriting a blob), then unlink it."""
        did = self._next_id(s["cycle"])
        blob = self.blobs / did
        try:
            self.blobs.mkdir(parents=True, exist_ok=True)
            src = os.open(full, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            try:
                if not stat.S_ISREG(os.fstat(src).st_mode):
                    raise OSError("not a regular file")
                dst = os.open(blob, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    head = b""
                    while chunk := os.read(src, 1 << 20):
                        if len(head) < 2000:
                            head += chunk[: 2000 - len(head)]
                        os.write(dst, chunk)
                finally:
                    os.close(dst)
            finally:
                os.close(src)
            os.unlink(full)
        except OSError as e:
            blob.unlink(missing_ok=True)
            s["failures"].append(f"{rel}: {e}")
            return
        rec = self._rec(did, s["cycle"], s["agent"], rel, kind, source, reason,
                        head.decode("utf-8", errors="replace"))
        rec["blob"] = str(blob)
        s["out"].append(rec)

    def _remove_entry(self, s, rel, full, source, reason, kind="whole_file") -> None:
        """A link or special file: it holds no bytes of its own to keep, so it can't be undone."""
        try:
            what = f"(link to {os.readlink(full)})" if os.path.islink(full) else "(special file)"
            os.unlink(full)
        except OSError as e:
            s["failures"].append(f"{rel}: {e}")
            return
        s["out"].append(self._rec(self._next_id(s["cycle"]), s["cycle"], s["agent"], rel, kind, source, reason,
                                  what, undoable=False))

    def _unlock(self, root: Path, failures: list) -> None:
        """Give ourselves read/write on the agent's tree (same user as its scripts), so nothing hides by mode."""
        def note(err):
            failures.append(f"{err.filename}: {err.strerror}")
        try:
            os.chmod(root, 0o755)
        except OSError as e:
            failures.append(f"{root}: {e.strerror}")
        for dirpath, dirs, names in os.walk(root, topdown=True, onerror=note, followlinks=False):
            for name in dirs + names:
                p = os.path.join(dirpath, name)
                try:
                    st = os.lstat(p)
                    if stat.S_ISDIR(st.st_mode):
                        os.chmod(p, 0o755)       # before os.walk lists it
                    elif stat.S_ISREG(st.st_mode) and st.st_mode & 0o600 != 0o600:
                        os.chmod(p, (st.st_mode & 0o7777) | 0o600)
                except OSError as e:
                    failures.append(f"{p}: {e.strerror}")

    def _entries(self, root: Path):
        """(rel, path, lstat) of every non-folder entry, folder links included, sorted."""
        out = []
        for dirpath, dirs, names in os.walk(root, followlinks=False):
            dirs.sort()
            for name in sorted(names) + [d for d in dirs if os.path.islink(os.path.join(dirpath, d))]:
                full = Path(dirpath) / name
                try:
                    out.append((full.relative_to(root).as_posix(), full, os.lstat(full)))
                except OSError:
                    continue
        return out

    # ---- cleaning -------------------------------------------------------------------------------------------
    def clean(self, cycle: int, agent, rules: dict, model_pass: bool = True) -> list[dict]:
        s = {"cycle": cycle, "agent": agent, "out": [], "failures": [], "before_py": {}, "axioms": False}
        try:
            self._clean(s, rules, model_pass)
        finally:
            self._finish(s)
        if s["failures"]:
            raise CleanerError(f"could not clean {agent.id}: " + "; ".join(s["failures"][:10]))
        return s["out"]

    def _finish(self, s) -> None:
        agent = s["agent"]
        for rel, original in s["before_py"].items():
            try:
                now = _read_bytes(agent.dir / rel).decode("utf-8", errors="replace")
            except OSError:
                continue
            if _compiles(original) and not _compiles(now):
                for rec in s["out"]:
                    if rec["file"] == rel and rec["kind"] == "span":
                        rec["broke_code"] = True
        if s["axioms"]:
            try:
                agent.axioms = (agent.dir / _AXIOMS).read_text(errors="replace")
            except OSError:
                pass
        for rec in s["out"]:
            self._event(rec)
        for failure in s["failures"]:
            self._event({"event": "not_cleaned", "cycle": s["cycle"], "agent": agent.id, "what": failure})

    def _clean(self, s, rules: dict, model_pass: bool) -> None:
        agent, cycle = s["agent"], s["cycle"]
        limit = self.cfg["tools"]["max_file_chars"]
        patterns = [re.compile(p) for p in rules.get("patterns", [])]
        globs = list(rules.get("file_globs", []))
        data_file = rules["data_file"]
        self._unlock(agent.dir, s["failures"])

        # the data file, and any other name for it
        data_inode = None
        data_path = agent.dir / data_file
        if os.path.lexists(data_path):
            st = os.lstat(data_path)
            if stat.S_ISREG(st.st_mode):
                data_inode = (st.st_dev, st.st_ino)
                self._delete_whole(s, data_file, data_path, "rule", "the data file is deleted each cycle", "data_file")
            elif not stat.S_ISDIR(st.st_mode):
                self._remove_entry(s, data_file, data_path, "rule", "the data file's name", "data_file")

        texts: dict[str, str] = {}
        for rel, full, st in self._entries(agent.dir):
            mode = st.st_mode
            if stat.S_ISLNK(mode):
                try:
                    target = os.readlink(full)
                except OSError:
                    target = ""
                if any(p.search(rel) or p.search(target) for p in patterns):
                    self._remove_entry(s, rel, full, "name", "a data fact in a link's name or target")
                continue
            if not stat.S_ISREG(mode):
                self._remove_entry(s, rel, full, "special", "not a regular file")
                continue
            is_axioms = rel == _AXIOMS
            name = PurePosixPath(rel).name
            if not is_axioms:
                source = ("name" if any(p.search(rel) for p in patterns)
                          else "rule" if data_inode == (st.st_dev, st.st_ino)
                          else "hardlink" if st.st_nlink > 1
                          else "big" if st.st_size > limit * 4
                          else "glob" if any(fnmatch.fnmatch(name, g) or fnmatch.fnmatch(rel, g) for g in globs)
                          else None)
                if source:
                    self._delete_whole(s, rel, full, source, f"data as a whole ({source})")
                    continue
            try:
                raw = _read_bytes(full, None if is_axioms else limit * 4)
            except OSError as e:
                s["failures"].append(f"{rel}: {e}")
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                if not is_axioms:
                    self._delete_whole(s, rel, full, "binary", "data as a whole (binary)")
                    continue
                text = raw.decode("utf-8", errors="replace")
            spans = _spans(text, patterns)
            covered = sum(e - b for b, e in spans)
            if not is_axioms and text and (covered / len(text) >= self.c["dense_share"]
                                           or len(spans) > self.c["max_matches_per_file"]):
                self._delete_whole(s, rel, full, "dense", "data as a whole (dense)")
                continue
            if spans:
                parts, last, recs = [], 0, []
                for b, e in spans:
                    did = self._next_id(cycle)
                    recs.append(self._rec(did, cycle, agent, rel, "span", "pattern", "matches a data pattern",
                                          text[b:e]))
                    parts += [text[last:b], recs[-1]["marker"]]
                    last = e
                parts.append(text[last:])
                if not self._rewrite(s, rel, full, text, "".join(parts), recs, is_axioms):
                    continue
                text = "".join(parts)
            texts[rel] = text

        if model_pass and texts:
            self._model_pass(s, rules, texts)

    def _rewrite(self, s, rel, full, old: str, new: str, recs: list, is_axioms: bool) -> bool:
        try:
            _write_text(full, new)
        except OSError as e:
            for rec in recs:
                self.records.pop(rec["id"], None)
            if is_axioms:
                s["failures"].append(f"{rel}: {e}")
            else:
                self._delete_whole(s, rel, full, "dense", "could not be rewritten")
            return False
        s["out"] += recs
        if rel.endswith(".py"):
            s["before_py"].setdefault(rel, old)
        s["axioms"] |= rel == _AXIOMS
        return True

    def _model_pass(self, s, rules: dict, texts: dict) -> None:
        agent, cycle = s["agent"], s["cycle"]
        shown, parts, total, skipped = [], [], 0, []
        for rel in sorted(texts):
            part = f"=== {rel} ===\n{texts[rel]}"
            if total + len(part) > self.c["files_chars"]:
                skipped.append(rel)
                continue
            shown.append(rel)
            parts.append(part)
            total += len(part) + 2
        if skipped:
            self._event({"event": "not_model_checked", "cycle": cycle, "agent": agent.id, "files": skipped})
        if not shown:
            return

        def check(obj):
            facts = obj.get("facts")
            if not isinstance(facts, list):
                return "facts must be a list"
            for i, f in enumerate(facts):
                if not isinstance(f, dict) or f.get("file") not in shown:
                    return f"facts[{i}].file must be one of the files shown"
                q = f.get("quote")
                if not isinstance(q, str) or not 1 <= len(q) <= 500:
                    return f"facts[{i}].quote must be 1-500 chars of the file"
                if _free_at(texts[f["file"]], q) == -1:
                    return (f"facts[{i}].quote must occur verbatim in {f['file']}, outside any [cleaned …] "
                            "marker")
            return None

        messages = [{"role": "system", "content": prompts.cleaner_system()},
                    {"role": "user", "content": prompts.cleaner_message(rules, "\n\n".join(parts))}]
        try:
            obj = ask_json(self.budget, self.model, "cleaner", messages, check, self.c["output_tokens"])
        except CapReached as e:
            self._event({"event": "model_pass_failed", "cycle": cycle, "agent": agent.id, "error": str(e)[:300]})
            raise
        except Exception as e:
            self._event({"event": "model_pass_failed", "cycle": cycle, "agent": agent.id,
                         "error": f"{type(e).__name__}: {e}"[:300]})
            return

        new_texts, new_recs = {}, {}
        for f in obj["facts"]:
            rel, quote = f["file"], f["quote"]
            text = new_texts.get(rel, texts[rel])
            idx = _free_at(text, quote)
            while idx != -1:
                did = self._next_id(cycle)
                rec = self._rec(did, cycle, agent, rel, "span", "model", str(f.get("reason", ""))[:300], quote)
                text = text[:idx] + rec["marker"] + text[idx + len(quote):]
                new_recs.setdefault(rel, []).append(rec)
                idx = _free_at(text, quote, idx + len(rec["marker"]))
            new_texts[rel] = text
        for rel, text in new_texts.items():
            if text != texts[rel]:
                self._rewrite(s, rel, agent.dir / rel, texts[rel], text, new_recs.get(rel, []), rel == _AXIOMS)

    def clean_all(self, cycle: int, agents, rules: dict) -> list[dict]:
        """Clean every agent entering the next cycle. After a budget stop the rest still get every step but the
        model pass; the first stop (or cleaning failure) is raised at the end."""
        out, seen, error = [], set(), None
        for agent in agents:
            try:
                self.clean(cycle, agent, rules, model_pass=not isinstance(error, CapReached))
            except (CapReached, CleanerError) as e:
                if error is None or isinstance(e, CapReached):
                    error = e
            for rec in self.records.values():
                if rec["agent"] == agent.id and rec["cycle"] == cycle and rec["id"] not in seen:
                    seen.add(rec["id"])
                    out.append(rec)
        if error is not None:
            raise error
        return out

    # ---- undo -----------------------------------------------------------------------------------------------
    def undo(self, deletion_id: str) -> str:
        rec = self.records.get(deletion_id)
        if rec is None:
            raise CleanerError(f"no deletion {deletion_id}")
        if deletion_id in self.undone:
            raise CleanerError(f"{deletion_id} was already undone")
        if not rec.get("undoable", True):
            raise CleanerError(f"{deletion_id} removed a link or special file; it can't be undone")
        if rec["kind"] == "data_file" or rec["source"] in ("rule", "glob"):   # the connector's own rules say: data
            raise CleanerError(f"{deletion_id} is data by the task's rules ({rec['source']}); it can't be undone")
        root = Path(rec["agent_dir"])
        ws = Workspace(root, self.cfg, protected=())
        rel = rec["file"]
        try:
            if rec["kind"] == "span":
                path = ws._resolve(rel)                      # a link pointing out is refused here
                ws._existing_regular(path, rel, changing=True)
                text = _read_bytes(path).decode("utf-8")
                if text.count(rec["marker"]) != 1:
                    raise CleanerError(f"{rel} no longer holds {rec['marker']} exactly once")
                _write_text(path, text.replace(rec["marker"], rec["original"], 1))
            else:
                entry = root / rel
                if os.path.lexists(entry):
                    raise CleanerError(f"{rel} exists again; not overwriting it")
                parent = ws._resolve(str(PurePosixPath(rel).parent))
                parent.mkdir(parents=True, exist_ok=True)
                data = Path(rec["blob"]).read_bytes()
                fd = os.open(parent / PurePosixPath(rel).name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o644)
                try:
                    os.write(fd, data)
                finally:
                    os.close(fd)
        except (ToolError, OSError, UnicodeDecodeError, KeyError) as e:
            raise CleanerError(f"cannot undo {deletion_id}: {e}") from None
        self.undone.add(deletion_id)
        self._event({"event": "undo", "id": deletion_id})
        return f"restored {deletion_id} in {rec['agent']}/{rel}"
