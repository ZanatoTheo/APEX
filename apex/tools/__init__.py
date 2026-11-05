"""The core tools every agent gets. spawn_subagents and finish come with the agent loop;
a connector adds its own tools to the same ToolSet."""
from .files import ToolError, Workspace
from .registry import Tool, ToolSet
from .sandbox import run_script

_PATH = {"type": "string", "description": "Path relative to your folder."}


def core_toolset(workspace: Workspace, cfg: dict, ro_files: dict | None = None) -> ToolSet:
    """`ro_files`: {sandbox path: host file} every run_script mounts read-only (a connector's script_files)."""
    ws = workspace
    ro = dict(ro_files or {})

    def script(args):
        extra = args.get("args", [])
        if not all(isinstance(a, str) for a in extra):
            raise ToolError("args must be a list of strings")
        r = run_script(ws.root, cfg, args["path"], extra, ro_files=ro)
        # plain text, not JSON: a cut output stays readable (JSON cut in the middle would not parse)
        return (f"exit_code: {r['exit_code']}\ntimed_out: {str(r['timed_out']).lower()}\n"
                f"--- stdout ---\n{r['stdout']}\n--- stderr ---\n{r['stderr']}")

    obj = lambda props, req: {"type": "object", "properties": props, "required": req}
    return ToolSet(cfg, [
        Tool("write_file", "Create or replace a file in your folder.",
             obj({"path": _PATH, "content": {"type": "string"}}, ["path", "content"]),
             lambda a: ws.write(a["path"], a["content"])),
        Tool("edit_file", "Replace one exact, unique piece of text in a file.",
             obj({"path": _PATH, "old": {"type": "string"}, "new": {"type": "string"}}, ["path", "old", "new"]),
             lambda a: ws.edit(a["path"], a["old"], a["new"])),
        Tool("delete_file", "Delete a file in your folder.", obj({"path": _PATH}, ["path"]),
             lambda a: ws.delete(a["path"])),
        Tool("read_file", "Read a file in your folder.", obj({"path": _PATH}, ["path"]),
             lambda a: ws.read(a["path"])),
        Tool("list_files", "List the files in your folder (or a subfolder), with sizes.",
             obj({"path": _PATH}, []), lambda a: ws.list(a.get("path", "."))),
        Tool("run_script", "Run a Python file from your folder in a sandbox (no network; only your folder is "
             "visible and writable; numpy and pandas are available). Returns exit_code, stdout, stderr, timed_out.",
             obj({"path": _PATH, "args": {"type": "array", "items": {"type": "string"}}}, ["path"]), script),
    ])


__all__ = ["Tool", "ToolError", "ToolSet", "Workspace", "core_toolset", "run_script"]
