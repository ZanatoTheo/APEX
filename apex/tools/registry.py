"""ToolSet: the tools offered to a model, and the one place that runs a model's tool call.

`run` never raises for an agent's mistake (bad JSON, unknown tool, wrong arguments, a handler error): it answers
with an "error: …" output the agent can read and act on.
"""
import json
from dataclasses import dataclass
from typing import Callable

from .files import ToolError, cut

_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
}
_ARTICLE = {"string": "a string", "integer": "an integer", "number": "a number", "boolean": "a boolean",
            "object": "an object", "array": "an array"}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict                     # JSON schema of the arguments object
    handler: Callable[[dict], object]    # returns the output (str, or anything JSON-able)


class ToolSet:
    def __init__(self, cfg: dict, tools=()):
        self.cfg = cfg
        self._tools: dict[str, Tool] = {}
        self.merge(tools)

    def add(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"a tool named {tool.name} is already in this set")
        self._tools[tool.name] = tool

    def merge(self, tools) -> None:
        for tool in (tools._tools.values() if isinstance(tools, ToolSet) else tools):
            self.add(tool)

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[dict]:
        return [{"type": "function", "name": t.name, "description": t.description, "parameters": t.parameters}
                for t in self._tools.values()]

    def _check_args(self, tool: Tool, args: dict) -> str | None:
        schema = tool.parameters or {}
        for key in schema.get("required", []):
            if key not in args:
                return f"argument {key} is required"
        for key, value in args.items():
            kind = schema.get("properties", {}).get(key, {}).get("type")
            if kind in _TYPES and not _TYPES[kind](value):
                return f"argument {key} must be {_ARTICLE[kind]}"
        return None

    def _answer(self, call) -> str:
        if not isinstance(call, dict):
            return "error: a tool call must be an object"
        if call.get("error"):
            return f"error: your arguments were not valid JSON ({call['error']}); send a JSON object."
        name = call.get("name")
        tool = self._tools.get(name) if isinstance(name, str) else None
        if tool is None:
            return f"error: no tool named {name}"
        args = call.get("arguments")
        args = {} if args is None else args
        if not isinstance(args, dict):
            return "error: arguments must be a JSON object"
        problem = self._check_args(tool, args)
        if problem:
            return f"error: {problem}"
        try:
            out = tool.handler(args)
        except ToolError as e:
            return f"error: {e}"
        except Exception as e:           # never crash the agent loop on a tool's failure
            return f"error: {type(e).__name__}: {e}"
        return out if isinstance(out, str) else json.dumps(out)

    def run(self, call: dict) -> dict:
        """One tool call ({call_id, name, arguments, error}) → its function_call_output item. Never raises."""
        try:
            answer = self._answer(call)
        except Exception as e:           # anything not caught inside, e.g. a result json.dumps can't encode
            answer = f"error: {type(e).__name__}: {e}"
        output = cut(answer, self.cfg["tools"]["max_tool_output_chars"])
        call_id = call.get("call_id") if isinstance(call, dict) else None
        return {"type": "function_call_output", "call_id": call_id, "output": output}
