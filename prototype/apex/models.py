"""Model access by role (CODE_STRUCTURE §6.3 ModelClient), with the token budget.

The real-model adapter is the one file the prototype leaves unwritten: apex/llm_service.py. Contract:

    class LLMService:
        def __init__(self, config: dict):
            # config is the full run config. config["models"][role]["model_id"] is the pinned model ID for each
            # role ("subagent", "mutation"); config["models"][role]["max_tokens"] caps the reply.
            # API keys come from environment variables only, never from the config.
        def complete(self, role: str, messages: list[dict], max_tokens: int) -> dict:
            # messages: [{"role": "system" | "user" | "assistant", "content": str}, ...]; the first message is
            #   the system prompt, and user/assistant messages may repeat (merge consecutive ones if the API needs it).
            # returns {"text": str, "model_id": str, "usage": {"input_tokens": int, "output_tokens": int}}
            #   model_id is the ID the API reports it served; usage is the API's own token counts.
            #   ModelClient requires model_id == the pinned ID exactly: pin the exact (e.g. dated) ID the API reports.
            # Raise any exception on transport or API errors: ModelClient retries, then marks the run infra_error.
            # Apply a request timeout (e.g. 120 s): the agent's run timeout is only checked between steps.

Select it with `python3 run.py run --model llm` (config models.provider = "llm").
"""
import importlib
import threading
import time
from dataclasses import dataclass

ROLES = ("subagent", "mutation")


class ModelError(Exception):
    """A model call failed for infrastructure reasons (never counted as an agent's L0 failure)."""


class BudgetExceeded(ModelError):
    pass


class LLMServiceMissing(ModelError):
    pass


@dataclass
class Completion:
    text: str
    model_id: str
    input_tokens: int
    output_tokens: int
    record_hash: str          # blob holding {role, request, response}

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class Budget:
    """Run-wide token cap with a reserve kept back for the final held-out runs (design §10 Budget)."""

    def __init__(self, tokens_total: int, holdout_reserve: int):
        self.tokens_total = tokens_total
        self.holdout_reserve = holdout_reserve
        self.spent = 0
        self.reserved = 0            # worst-case cost of calls in flight (concurrent workers)
        self.holdout_phase = False   # set by the loop before the final held-out evaluation
        self._lock = threading.Lock()

    @property
    def available(self) -> int:
        cap = self.tokens_total if self.holdout_phase else self.tokens_total - self.holdout_reserve
        return cap - self.spent - self.reserved

    def reserve(self, tokens: int):
        """Hold a call's worst case before it starts, so concurrent calls cannot overshoot the cap."""
        with self._lock:
            if tokens > self.available:
                raise BudgetExceeded(f"budget exhausted: {tokens} tokens requested, "
                                     f"{max(self.available, 0)} available")
            self.reserved += tokens

    def settle(self, reserved: int, actual: int):
        with self._lock:
            self.reserved -= reserved
            self.spent += actual


def load_service(cfg: dict):
    provider = cfg["models"]["provider"]
    if provider == "fake":
        from .fake_model import FakeModel
        return FakeModel(cfg)
    try:
        module = importlib.import_module("apex.llm_service")
    except ModuleNotFoundError as e:
        if e.name != "apex.llm_service":
            raise
        raise LLMServiceMissing(
            "apex/llm_service.py is missing. It is the one piece the prototype leaves for you to write: see "
            "'Adding llm_service.py' in README.md (or the contract at the top of apex/models.py).") from e
    for role in ROLES:
        model_id = cfg["models"][role]["model_id"]
        if model_id.startswith("fake-") or "<" in model_id:
            raise LLMServiceMissing(f"set models.{role}.model_id in your config (--config) to the real model ID to pin")
    return module.LLMService(cfg)


def _check_response(resp) -> tuple[str, str, int, int]:
    if not isinstance(resp, dict):
        raise ModelError(f"service returned {type(resp).__name__}, expected dict")
    text, model_id, usage = resp.get("text"), resp.get("model_id"), resp.get("usage")
    if not isinstance(text, str) or not isinstance(model_id, str) or not isinstance(usage, dict):
        raise ModelError("service response needs text (str), model_id (str) and usage (dict)")
    inp, out = usage.get("input_tokens"), usage.get("output_tokens")
    if not (isinstance(inp, int) and isinstance(out, int) and inp >= 0 and out >= 0):
        raise ModelError("usage needs non-negative integer input_tokens and output_tokens")
    return text, model_id, inp, out


class ModelClient:
    """Wraps a service: pin check, retries, every call recorded as a blob, every token charged."""

    def __init__(self, service, cfg: dict, blobs, budget: Budget, sleep=time.sleep):
        self.service = service
        self.cfg = cfg
        self.blobs = blobs
        self.budget = budget
        self._sleep = sleep

    def complete(self, role: str, messages: list[dict]) -> Completion:
        if role not in ROLES:
            raise ModelError(f"unknown role {role!r}")
        pin = self.cfg["models"][role]["model_id"]
        max_tokens = self.cfg["models"][role]["max_tokens"]
        hold = max_tokens + sum(len(m["content"]) for m in messages) // 4   # reply cap + prompt estimate
        self.budget.reserve(hold)
        actual = 0
        try:
            retries, backoff = self.cfg["models"]["retries"], self.cfg["models"]["retry_backoff_s"]
            last_error = None
            for attempt in range(retries + 1):
                try:
                    resp = self.service.complete(role, messages, max_tokens)
                    break
                except Exception as e:   # transport/API errors of any kind
                    last_error = e
                    if attempt < retries:
                        self._sleep(backoff * 2 ** attempt)
            else:
                raise ModelError(f"{role} call failed after {retries + 1} attempts: {last_error}")
            text, model_id, inp, out = _check_response(resp)
            actual = inp + out
        finally:
            self.budget.settle(hold, actual)
        record = {"role": role, "request": {"messages": messages, "max_tokens": max_tokens},
                  "response": {"text": text, "model_id": model_id,
                               "usage": {"input_tokens": inp, "output_tokens": out}}}
        record_hash = self.blobs.put(record)
        if model_id != pin:
            raise ModelError(f"model pin mismatch for {role}: served {model_id!r}, pinned {pin!r}")
        return Completion(text, model_id, inp, out, record_hash)
