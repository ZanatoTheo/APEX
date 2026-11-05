"""File tools kept inside one agent's folder.

Every path is relative to the folder and must still be inside it after symlinks are followed. The tools only
read or change regular files (a FIFO or device made by a script could hang the host), never change a file with
several hard links (it could be an alias of a protected file), and never read more of a file than they return.
Protected files (the agent's own log) can be read but not changed; run_script also mounts them read-only.
"""
import os
import stat
from pathlib import Path, PurePosixPath


class ToolError(Exception):
    """A tool refused or failed; the message goes back to the agent as "error: <message>"."""


def cut(text: str, limit: int) -> str:
    """Cut `text` to `limit` chars, saying how much was left out."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n… [{len(text) - limit} more chars cut]"


def read_head(fd: int, limit_chars: int) -> str:
    """Read at most about `limit_chars` chars from an open file: never the whole of a big file."""
    size = os.fstat(fd).st_size
    raw = os.read(fd, limit_chars * 4 + 4)
    text = raw.decode("utf-8", errors="replace")
    if size <= len(raw):
        return cut(text, limit_chars)
    kept = text[:limit_chars]
    return f"{kept}\n… [{size - len(kept.encode('utf-8'))} more bytes cut]"


def folder_bytes(root: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            st = os.lstat(os.path.join(dirpath, name))
            if stat.S_ISREG(st.st_mode):
                total += st.st_size
    return total


PROTECTED = ("log.jsonl", "axioms.md")      # an agent's axioms are set by Op. Orch and Mutation, not by itself


class Workspace:
    def __init__(self, root, cfg: dict, protected=PROTECTED):
        self.root = Path(root)
        self.cfg = cfg
        self.limits = cfg["tools"]
        self.protected = set(protected)

    # ---- paths ----------------------------------------------------------------------------------------------
    def _resolve(self, rel) -> Path:
        if not isinstance(rel, str) or not rel.strip():
            raise ToolError("path must be a non-empty path relative to your folder")
        if PurePosixPath(rel).is_absolute() or Path(rel).is_absolute():
            raise ToolError(f"path {rel} must be relative to your folder, not absolute")
        base = self.root.resolve()
        p = (base / rel).resolve()          # follows symlinks, so a link pointing out lands outside
        if p != base and base not in p.parents:
            raise ToolError(f"path {rel} is outside your folder")
        return p

    def _rel(self, p: Path) -> str:
        return p.relative_to(self.root.resolve()).as_posix()

    def _writable(self, rel) -> Path:
        p = self._resolve(rel)
        if p == self.root.resolve():
            raise ToolError("that is your folder itself, not a file")
        if self._rel(p) in self.protected:
            raise ToolError(f"{rel} is read-only")
        return p

    def _existing_regular(self, p: Path, rel: str, changing: bool) -> os.stat_result:
        if not os.path.lexists(p):
            raise ToolError(f"no file {rel}")
        st = os.stat(p)
        if stat.S_ISDIR(st.st_mode):
            raise ToolError(f"{rel} is a folder")
        if not stat.S_ISREG(st.st_mode):
            raise ToolError(f"{rel} is not a regular file")
        if changing and st.st_nlink > 1:
            raise ToolError(f"{rel} has several hard links; refusing to change it")
        return st

    def _check_size(self, content: str, rel: str) -> None:
        if len(content) > self.limits["max_file_chars"]:
            raise ToolError(f"{rel} would have {len(content)} chars; the limit is {self.limits['max_file_chars']}")

    def _write_bytes(self, p: Path, content: str) -> None:
        # O_NONBLOCK: if a FIFO appears between the check and the open, fail instead of hanging.
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NONBLOCK | os.O_NOFOLLOW, 0o644)
        try:
            os.write(fd, content.encode("utf-8"))
        finally:
            os.close(fd)

    # ---- operations -----------------------------------------------------------------------------------------
    def write(self, rel, content: str) -> str:
        p = self._writable(rel)
        self._check_size(content, rel)
        if os.path.lexists(p):
            self._existing_regular(p, rel, changing=True)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._write_bytes(p, content)
        return f"wrote {rel} ({len(content)} chars)"

    def edit(self, rel, old: str, new: str) -> str:
        p = self._writable(rel)
        st = self._existing_regular(p, rel, changing=True)
        if st.st_size > self.limits["max_file_chars"] * 4:
            raise ToolError(f"{rel} is too large to edit ({st.st_size} bytes)")
        if not old:
            raise ToolError("old text must not be empty")
        text = p.read_bytes().decode("utf-8", errors="replace")
        n = text.count(old)
        if n == 0:
            raise ToolError(f"old text not found in {rel}")
        if n > 1:
            raise ToolError(f"old text found {n} times in {rel}; give a longer piece that occurs once")
        result = text.replace(old, new, 1)
        self._check_size(result, rel)
        self._write_bytes(p, result)
        return f"edited {rel}"

    def delete(self, rel) -> str:
        """Removes the entry itself: a symlink is unlinked, never its target."""
        if not isinstance(rel, str) or PurePosixPath(rel).name in ("", ".", ".."):
            raise ToolError(f"cannot delete {rel!r}")
        parent = self._resolve(str(PurePosixPath(rel).parent))
        entry = parent / PurePosixPath(rel).name
        if not os.path.lexists(entry):
            raise ToolError(f"no file {rel}")
        if self._rel(entry) in self.protected:
            raise ToolError(f"{rel} is read-only")
        if entry.is_dir() and not entry.is_symlink():
            raise ToolError(f"{rel} is a folder; only files can be deleted")
        os.unlink(entry)
        return f"deleted {rel}"

    def read(self, rel) -> str:
        p = self._resolve(rel)
        self._existing_regular(p, rel, changing=False)
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
        try:
            return read_head(fd, self.limits["max_read_chars"])
        finally:
            os.close(fd)

    def list(self, rel: str = ".") -> str:
        d = self._resolve(rel)
        if not d.is_dir():
            raise ToolError(f"no folder {rel}")
        base = self.root.resolve()
        entries = []
        for dirpath, _dirs, files in os.walk(d, followlinks=False):
            for name in files:
                full = Path(dirpath) / name
                st = os.lstat(full)
                if stat.S_ISREG(st.st_mode):
                    entries.append((full.relative_to(base).as_posix(), st.st_size))
        entries.sort()
        cap = self.limits["max_list_entries"]
        lines = [f"{name} ({size} bytes)" for name, size in entries[:cap]]
        if len(entries) > cap:
            lines.append(f"… {len(entries) - cap} more")
        return "\n".join(lines) if lines else "(no files)"
