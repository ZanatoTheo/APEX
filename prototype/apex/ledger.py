"""Decision Ledger (design §8, CODE_STRUCTURE §5.1): hash-linked blocks in SQLite plus content-addressed blobs.

One Ledger object is the single writer. verify() works from the files alone, so it can run in another process.
"""
import datetime
import os
import re
import sqlite3
import threading
from pathlib import Path

from . import canonical

ROOT = "root"
GENESIS_PARENT = "0" * 64
ROOT_KINDS = {"genesis", "generation_event", "gate_version"}
KINDS = ROOT_KINDS | {"agent_run"}
BODY_KEYS = {"kind", "height", "timestamp", "parent_hash", "branch_id", "lamport_clock", "state_transitions"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS blocks (
    block_hash TEXT PRIMARY KEY, branch_id TEXT NOT NULL, kind TEXT NOT NULL, height INTEGER NOT NULL,
    lamport_clock INTEGER NOT NULL UNIQUE, parent_hash TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tips (branch_id TEXT PRIMARY KEY, block_hash TEXT NOT NULL);
"""


class LedgerError(Exception):
    pass


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class BlobStore:
    """Content-addressed store: <root>/<first two hex chars>/<sha256>. Each blob is the JCS bytes of its record."""

    def __init__(self, root: Path, create: bool = True):
        self.root = Path(root)
        if create:
            self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, h: str) -> Path:
        return self.root / h[:2] / h

    def put(self, record) -> str:
        data = canonical.dumps(record)
        h = canonical.sha256_hex(data)
        path = self._path(h)
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            tmp = path.with_name(f"{h}.{os.getpid()}.{threading.get_ident()}.tmp")   # unique per writer thread
            tmp.write_bytes(data)
            tmp.replace(path)
        return h

    def get(self, h: str):
        return canonical.loads(self._path(h).read_bytes())

    def has(self, h: str) -> bool:
        return isinstance(h, str) and HEX64.match(h) is not None and self._path(h).is_file()

    def problems(self) -> list[str]:
        out = []
        if not self.root.is_dir():
            return out
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and path.suffix != ".tmp" and canonical.sha256_hex(path.read_bytes()) != path.name:
                out.append(f"blob {self.root.name}/{path.name[:12]}…: content does not match its hash")
        return out


class Ledger:
    def __init__(self, run_dir: Path, now=utc_now):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.run_dir / "ledger.sqlite")
        self.db.executescript(SCHEMA)
        self.blobs = BlobStore(self.run_dir / "blobs")
        self.holdout_blobs = BlobStore(self.run_dir / "blobs-holdout")
        self.heads_file = self.run_dir / "heads.jsonl"
        self._now = now
        self._last_clock = self.db.execute("SELECT COALESCE(MAX(lamport_clock), 0) FROM blocks").fetchone()[0]

    def close(self):
        self.db.close()

    # -- reads ---------------------------------------------------------------
    def get_block(self, block_hash: str) -> dict:
        row = self.db.execute("SELECT body FROM blocks WHERE block_hash=?", (block_hash,)).fetchone()
        if row is None:
            raise LedgerError(f"unknown block {block_hash}")
        return {**canonical.loads(row[0]), "block_hash": block_hash}

    def blocks(self) -> list[dict]:
        rows = self.db.execute("SELECT block_hash, body FROM blocks ORDER BY lamport_clock").fetchall()
        return [{**canonical.loads(body), "block_hash": h} for h, body in rows]

    def tip(self, branch_id: str) -> str:
        row = self.db.execute("SELECT block_hash FROM tips WHERE branch_id=?", (branch_id,)).fetchone()
        if row is None:
            raise LedgerError(f"unknown branch {branch_id}")
        return row[0]

    def tips(self) -> dict[str, str]:
        return dict(self.db.execute("SELECT branch_id, block_hash FROM tips ORDER BY branch_id"))

    # -- writes (single writer) ----------------------------------------------
    def _insert(self, body: dict) -> dict:
        h = canonical.hash_obj(body)   # check I-JSON and hash the block without its block_hash
        with self.db:
            self.db.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?)",
                            (h, body["branch_id"], body["kind"], body["height"], body["lamport_clock"],
                             body["parent_hash"], canonical.dumps(body).decode("utf-8")))
            self.db.execute("INSERT OR REPLACE INTO tips VALUES (?,?)", (body["branch_id"], h))
        self._last_clock = body["lamport_clock"]
        return {**body, "block_hash": h}

    def _check_transitions(self, branch_id: str, transitions: list[dict]):
        for t in transitions:
            if not isinstance(t.get("action"), str) or not isinstance(t.get("result_hash"), str):
                raise LedgerError(f"transition needs string action and result_hash: {t}")
            if not (self.blobs.has(t["result_hash"]) or self.holdout_blobs.has(t["result_hash"])):
                raise LedgerError(f"result_hash {t['result_hash'][:12]}… is not in any blob store")
            if branch_id != ROOT and not isinstance(t.get("agent_id"), str):
                raise LedgerError("agent_run transitions need an agent_id")

    def genesis(self, transitions: list[dict]) -> dict:
        if self.db.execute("SELECT 1 FROM blocks LIMIT 1").fetchone():
            raise LedgerError("ledger already has a genesis block")
        self._check_transitions(ROOT, transitions)
        return self._insert({"kind": "genesis", "height": 0, "timestamp": self._now(),
                             "parent_hash": GENESIS_PARENT, "branch_id": ROOT,
                             "lamport_clock": self._last_clock + 1, "state_transitions": transitions})

    def fork(self, parent_tip: str, agent_id: str) -> str:
        self.get_block(parent_tip)
        branch_id = canonical.sha256_hex((parent_tip + agent_id).encode("utf-8"))
        if self.db.execute("SELECT 1 FROM tips WHERE branch_id=?", (branch_id,)).fetchone():
            raise LedgerError(f"branch {branch_id[:12]}… already exists")
        with self.db:
            self.db.execute("INSERT INTO tips VALUES (?,?)", (branch_id, parent_tip))
        return branch_id

    def append(self, kind: str, branch_id: str, transitions: list[dict]) -> dict:
        if kind not in KINDS or kind == "genesis":
            raise LedgerError(f"cannot append a block of kind {kind!r}")
        if (kind in ROOT_KINDS) != (branch_id == ROOT):
            raise LedgerError(f"{kind} blocks belong {'on' if kind in ROOT_KINDS else 'off'} the root branch")
        parent = self.get_block(self.tip(branch_id))
        self._check_transitions(branch_id, transitions)
        return self._insert({"kind": kind, "height": parent["height"] + 1, "timestamp": self._now(),
                             "parent_hash": parent["block_hash"], "branch_id": branch_id,
                             "lamport_clock": max(parent["lamport_clock"], self._last_clock) + 1,
                             "state_transitions": transitions})

    def publish_heads(self, generation) -> dict:
        """Publish every branch head outside the ledger (design §8); verify() compares against these."""
        entry = {"generation": generation, "tips": self.tips()}
        with self.heads_file.open("ab") as f:
            f.write(canonical.dumps(entry) + b"\n")
        return entry


# -- verification ----------------------------------------------------------------------------------------------

def verify(run_dir: Path, heads_file: Path | None = None, required_genesis_actions=()) -> list[str]:
    """Return a list of problems; an empty list means the run verifies. Never raises and never writes.

    heads_file defaults to <run_dir>/heads.jsonl. Pass a copy kept elsewhere to detect a rewrite of the
    whole run directory (the prototype keeps heads inside the run, JC-36).
    """
    try:
        return _verify(Path(run_dir), Path(heads_file) if heads_file else Path(run_dir) / "heads.jsonl",
                       set(required_genesis_actions))
    except Exception as e:   # last-resort net: malformed data must be reported, not crash the verifier
        return [f"verify aborted on malformed data: {type(e).__name__}: {e}"]


def _body_problem(body) -> str | None:
    if not isinstance(body, dict) or set(body) != BODY_KEYS:
        return "fields do not match the block schema"
    types = {"kind": str, "height": int, "timestamp": str, "parent_hash": str, "branch_id": str,
             "lamport_clock": int, "state_transitions": list}
    for key, typ in types.items():
        if not isinstance(body[key], typ) or isinstance(body[key], bool):
            return f"field {key} has the wrong type"
    if not HEX64.match(body["parent_hash"]):
        return "parent_hash is not 64 hex characters"
    for t in body["state_transitions"]:
        if not isinstance(t, dict) or not isinstance(t.get("action"), str) or not isinstance(t.get("result_hash"), str):
            return "a transition lacks a string action or result_hash"
    return None


def _verify(run_dir: Path, heads_path: Path, required_genesis_actions: set) -> list[str]:
    db_path = run_dir / "ledger.sqlite"
    if not db_path.is_file():
        return [f"no ledger at {db_path}"]
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT block_hash, branch_id, kind, height, lamport_clock, parent_hash, body "
                          "FROM blocks ORDER BY lamport_clock").fetchall()
        tips_table = dict(db.execute("SELECT branch_id, block_hash FROM tips"))
    finally:
        db.close()
    problems: list[str] = []
    blobs = BlobStore(run_dir / "blobs", create=False)
    holdout = BlobStore(run_dir / "blobs-holdout", create=False)

    blocks: dict[str, dict] = {}
    for h, branch_id, kind, height, clock, parent_hash, text in rows:
        try:
            body = canonical.loads(text)
        except canonical.CanonicalError as e:
            problems.append(f"block {str(h)[:12]}…: not canonical I-JSON ({e})")
            continue
        bad = _body_problem(body)
        if bad:
            problems.append(f"block {str(h)[:12]}…: {bad}")
            continue
        if canonical.hash_obj(body) != h:
            problems.append(f"block {str(h)[:12]}…: hash mismatch (content was edited)")
            continue   # an edited block is not trusted for the structural checks below
        if (branch_id, kind, height, clock, parent_hash) != (body["branch_id"], body["kind"], body["height"],
                                                             body["lamport_clock"], body["parent_hash"]):
            problems.append(f"block {h[:12]}…: index columns disagree with the block body")
        blocks[h] = body

    # Single writer: clocks are exactly 1..N, i.e. each block's clock = writer's last value + 1 (design §8).
    clocks = sorted(b["lamport_clock"] for b in blocks.values())
    if len(problems) == 0 and clocks != list(range(1, len(clocks) + 1)):
        problems.append("lamport clocks are not the consecutive sequence a single writer produces")

    genesis = [h for h, b in blocks.items() if b["kind"] == "genesis"]
    if len(genesis) != 1:
        problems.append(f"expected exactly one genesis block, found {len(genesis)}")
    else:
        recorded = {t["action"] for t in blocks[genesis[0]]["state_transitions"]}
        for action in sorted(required_genesis_actions - recorded):
            problems.append(f"genesis does not record {action!r}")

    branch_agent: dict[str, str] = {}
    children_on_branch: set[tuple[str, str]] = set()
    for h, b in sorted(blocks.items(), key=lambda kv: kv[1]["lamport_clock"]):
        if b["kind"] not in KINDS:
            problems.append(f"block {h[:12]}…: unknown kind {b['kind']!r}")
        if b["kind"] == "genesis":
            if (b["height"], b["parent_hash"], b["branch_id"]) != (0, GENESIS_PARENT, ROOT):
                problems.append(f"genesis {h[:12]}…: wrong height, parent or branch")
        else:
            parent = blocks.get(b["parent_hash"])
            if parent is None:
                problems.append(f"block {h[:12]}…: parent {b['parent_hash'][:12]}… does not exist")
                continue
            if b["height"] != parent["height"] + 1:
                problems.append(f"block {h[:12]}…: height is not parent height + 1")
            if b["lamport_clock"] <= parent["lamport_clock"]:
                problems.append(f"block {h[:12]}…: lamport_clock not greater than the parent's")
            if (b["kind"] in ROOT_KINDS) != (b["branch_id"] == ROOT):
                problems.append(f"block {h[:12]}…: {b['kind']} on the wrong branch")
            if parent["branch_id"] != b["branch_id"]:
                if b["branch_id"] in branch_agent:
                    problems.append(f"branch {b['branch_id'][:12]}…: forked more than once")
                agent_id = (b["state_transitions"][:1] or [{}])[0].get("agent_id", "")
                agent_id = agent_id if isinstance(agent_id, str) else ""
                branch_agent[b["branch_id"]] = agent_id
                if b["branch_id"] != canonical.sha256_hex((b["parent_hash"] + agent_id).encode("utf-8")):
                    problems.append(f"block {h[:12]}…: branch_id is not sha256(parent_hash ‖ agent_id)")
            else:
                key = (b["branch_id"], b["parent_hash"])
                if key in children_on_branch:
                    problems.append(f"branch {b['branch_id'][:12]}…: two blocks share a parent (not linear)")
                children_on_branch.add(key)
            if b["branch_id"] in branch_agent:      # unknown when the branch's first block was already flagged
                for t in b["state_transitions"]:
                    if t.get("agent_id") != branch_agent.get(b["branch_id"]):
                        problems.append(f"block {h[:12]}…: transition agent_id differs from the branch's agent")
                        break
        for t in b["state_transitions"]:
            if not (blobs.has(t["result_hash"]) or holdout.has(t["result_hash"])):
                problems.append(f"block {h[:12]}…: result_hash {t['result_hash'][:12]}… has no stored content")

    problems += blobs.problems() + holdout.problems()

    # The tips table must name each branch's highest block (or the fork point for an empty branch).
    computed = {}
    for h, b in sorted(blocks.items(), key=lambda kv: kv[1]["lamport_clock"]):
        computed[b["branch_id"]] = h
    for branch_id, tip in tips_table.items():
        expected = computed.get(branch_id)
        if expected is not None and tip != expected:
            problems.append(f"tips: branch {str(branch_id)[:12]}… points at {str(tip)[:12]}…, not its last block")
        if expected is None and tip not in blocks:
            problems.append(f"tips: empty branch {str(branch_id)[:12]}… forks from a missing block")
    for branch_id in computed.keys() - tips_table.keys():
        problems.append(f"tips: branch {branch_id[:12]}… is missing from the tips table")

    problems += _check_heads(heads_path, blocks, tips_table)
    return problems


def _is_ancestor(blocks: dict, ancestor: str, descendant: str) -> bool:
    h, seen = descendant, set()
    while h in blocks and h not in seen:   # seen: a corrupted ledger could contain a parent cycle
        if h == ancestor:
            return True
        seen.add(h)
        h = blocks[h]["parent_hash"]
    return False


def _check_heads(path: Path, blocks: dict, tips: dict) -> list[str]:
    """Every published head must still be in the ledger, on the path to its branch's current tip."""
    if not path.is_file():
        return [f"heads: no published heads file at {path}"]
    problems, entries = [], []
    for n, line in enumerate(path.read_bytes().splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = canonical.loads(line)
        except canonical.CanonicalError as e:
            problems.append(f"heads: line {n} is not valid JSON ({e})")
            continue
        if (not isinstance(entry, dict) or not isinstance(entry.get("tips"), dict)
                or not all(isinstance(v, str) for v in entry["tips"].values())):
            problems.append(f"heads: line {n} is not a {{generation, tips}} record")
            continue
        entries.append(entry)
    if not entries:
        return problems + ["heads: no usable published heads"]
    for entry in entries:
        g = entry.get("generation")
        for branch_id, head in entry["tips"].items():
            if head not in blocks:
                problems.append(f"heads: generation {g} head {head[:12]}… of branch {branch_id[:12]}… "
                                f"is not in the ledger (rewritten history?)")
            elif branch_id not in tips or not _is_ancestor(blocks, head, tips[branch_id]):
                problems.append(f"heads: generation {g} head {head[:12]}… is not an ancestor of the current tip")
    if entries[-1]["tips"] != tips:
        problems.append("heads: the last published heads do not match the current tips")
    return problems
