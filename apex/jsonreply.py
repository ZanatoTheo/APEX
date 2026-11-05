"""Ask a model for one JSON object, check it, retry once. Used by Op. Orch, Eval and Mutation.

The object is read from the whole reply, else the first fenced json block, else the span from the first { to the last
}. If it is missing or `check` names a problem, the model gets its reply back with that problem and one more try. A
second problem raises ReplyError. Budget and model errors pass through.
"""
import json
import re

_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n\s*```", re.S)


class ReplyError(Exception):
    """A model's reply was still not valid after one retry."""


_DECODER = json.JSONDecoder()
_MAX_STARTS = 200                    # '{' positions tried, so a long reply full of braces stays cheap


def _loads_dict(text: str):
    try:
        obj = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return obj if isinstance(obj, dict) else None


def extract_json(text: str):
    """The JSON object in a reply: the whole text, else the first fenced block, else the first '{' at which a
    whole object parses (prose with braces around it, or a second object after it, is ignored). Never raises."""
    if not isinstance(text, str):
        return None
    obj = _loads_dict(text.strip())
    if obj is None and (m := _FENCE.search(text)):
        obj = _loads_dict(m.group(1))
    start = text.find("{")
    tries = 0
    while obj is None and start != -1 and tries < _MAX_STARTS:
        tries += 1
        try:
            found, _end = _DECODER.raw_decode(text, start)
            obj = found if isinstance(found, dict) else None
        except (ValueError, RecursionError):
            pass
        start = text.find("{", start + 1)
    return obj


def ask_json(budget, model, role: str, messages: list, check, max_output_tokens: int) -> dict:
    """budget.call → extract_json → check(obj) (a problem string, or None). One retry that shows the problem.
    CapReached and LLMError pass through to the caller."""
    messages = list(messages)
    problem = None
    for attempt in range(2):
        reply = budget.call(model, role, messages, max_output_tokens=max_output_tokens)
        obj = extract_json(reply["text"])
        try:
            problem = "reply is not a JSON object" if obj is None else check(obj)
        except Exception as e:               # e.g. OverflowError on a 400-digit number
            problem = f"a value could not be read ({type(e).__name__}: {str(e)[:100]})"
        if problem is None:
            return obj
        messages += [{"role": "assistant", "content": reply["text"] or "(empty)"},
                     {"role": "user", "content": f"Your reply was not valid: {problem}. "
                                                 "Reply again with only the JSON object."}]
    raise ReplyError(f"{role} reply not valid after a retry: {problem}")
