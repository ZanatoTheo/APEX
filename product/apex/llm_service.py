"""LLMService for Meta's models behind an OpenAI-style Responses API (the contract is at the top of apex/models.py).

One POST to {models.base_url}/responses per call (default https://api.meta.ai/v1), standard library only:
    {"model": <pinned id for the role>, "instructions": <system prompt>, "input": [<other messages>],
     "max_output_tokens": <cap>, "store": false}
The reply text is the `output_text` parts of the `message` items in `output` (reasoning items are skipped).

The API key comes only from $MODEL_API_KEY. It is sent in the Authorization header and never put in the config,
a blob, the ledger or an error message. Retries live in ModelClient; this class makes exactly one attempt.
"""
import http.client
import json
import os
import time
import urllib.error
import urllib.request

from .models import ROLES

API_KEY_ENV = "MODEL_API_KEY"
NON_RETRYABLE = frozenset({400, 401, 403, 404, 422})   # the same request can never succeed
_ERROR_BODY_LIMIT = 2048
_MAX_BODY = 8 * 1024 * 1024
_CHUNK = 65536


class LLMServiceError(Exception):
    """A failed call. ModelClient retries it unless `retryable` is False, then marks the run infra_error."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would resend the Authorization header to wherever it points."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None   # urllib then raises HTTPError with the 3xx code


class LLMService:
    def __init__(self, config: dict):
        models = config["models"]
        key = (os.environ.get(API_KEY_ENV) or "").strip()   # a CR from a Windows-saved .env would break the header
        if not key:
            raise LLMServiceError(f"set the {API_KEY_ENV} environment variable to your Meta API key",
                                  retryable=False)
        self._key = key
        self._opener = urllib.request.build_opener(_NoRedirect())
        self._base = models["base_url"].rstrip("/")
        self._timeout = models["request_timeout_s"]
        self._model = {role: models[role]["model_id"] for role in ROLES}

    def complete(self, role: str, messages: list[dict], max_tokens: int) -> dict:
        return self._parse(self._request("POST", "/responses", self._request_body(role, messages, max_tokens)))

    def list_models(self) -> list[str]:
        """GET {base_url}/models (OpenAI-style {"data": [{"id": …}]}): the IDs this key can use, sorted."""
        data = self._request("GET", "/models")
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list) or not all(isinstance(i, dict) and isinstance(i.get("id"), str) for i in items):
            raise LLMServiceError("the models reply has no `data` list of objects with an `id`")
        return sorted(i["id"] for i in items)

    # ---- request ------------------------------------------------------------------------------------------------
    def _request_body(self, role: str, messages: list[dict], max_tokens: int) -> dict:
        body = {"model": self._model[role]}
        rest = messages
        if messages and messages[0]["role"] == "system":
            body["instructions"] = messages[0]["content"]
            rest = messages[1:]
        body["input"] = [{"role": m["role"], "content": m["content"]} for m in rest]
        body["max_output_tokens"] = max_tokens
        body["store"] = False
        return body

    def _request(self, method: str, path: str, body: dict | None = None):
        url = self._base + path
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        # request_timeout_s bounds the whole call, not just each socket read: the body is read in chunks and the
        # deadline is checked between them. Worst case ≈ 2 × request_timeout_s (one blocked read after the deadline).
        deadline = time.monotonic() + self._timeout
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                raw = self._read_body(resp, deadline, _MAX_BODY)
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:
                raise LLMServiceError(f"HTTP {e.code}: redirect refused (the key is only sent to {self._base})",
                                      retryable=False) from None
            raise LLMServiceError(f"HTTP {e.code}: {self._error_message(e, deadline)}",
                                  retryable=e.code not in NON_RETRYABLE) from None
        except (OSError, http.client.HTTPException) as e:   # URLError, timeouts, resets, truncated replies
            raise LLMServiceError(f"{method} {url} failed: {type(e).__name__}: {self._clean(str(e))}") from None
        except ValueError as e:   # e.g. an invalid URL or header value: the same request can never work
            raise LLMServiceError(f"cannot send the request: {self._clean(str(e))}", retryable=False) from None
        try:
            return json.loads(raw)
        except ValueError:
            raise LLMServiceError(f"reply is not JSON: {self._clean(raw[:200].decode('utf-8', 'replace'))}") from None

    def _read_body(self, stream, deadline: float, limit: int, truncate: bool = False) -> bytes:
        chunks, size = [], 0
        while True:
            if time.monotonic() > deadline:
                raise LLMServiceError(f"timed out: no complete reply within {self._timeout} s")
            chunk = stream.read1(_CHUNK)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            size += len(chunk)
            if size >= limit:
                if truncate:
                    return b"".join(chunks)[:limit]
                raise LLMServiceError(f"reply is larger than {limit} bytes")

    def _error_message(self, err: urllib.error.HTTPError, deadline: float) -> str:
        try:
            raw = self._read_body(err.fp, deadline, _ERROR_BODY_LIMIT, truncate=True).decode("utf-8", "replace")
        except Exception:
            raw = ""
        msg = raw
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                inner = data.get("error", data)
                if isinstance(inner, dict):
                    msg = str(inner.get("message") or inner)
                else:
                    msg = str(inner)
        except ValueError:
            pass
        return self._clean(msg.strip() or str(err.reason or "") or "no details")[:300]   # clean first, then cut

    def _clean(self, text: str) -> str:
        """Remove the key (raw or repr-escaped, as in a ValueError's message) in case an error echoes it back."""
        text = text.replace(self._key, "***")
        escaped = repr(self._key)[1:-1]
        return text.replace(escaped, "***") if escaped != self._key else text

    # ---- reply --------------------------------------------------------------------------------------------------
    def _parse(self, data) -> dict:
        if not isinstance(data, dict):
            raise LLMServiceError(f"reply is a {type(data).__name__}, expected an object")
        if data.get("status") == "failed" or data.get("error"):
            err = data.get("error")
            detail = err.get("message") if isinstance(err, dict) else err
            raise LLMServiceError(f"response failed: {self._clean(str(detail))[:300]}")
        model_id, output, usage = data.get("model"), data.get("output"), data.get("usage")
        if not isinstance(model_id, str) or not model_id:
            raise LLMServiceError("reply has no model")
        if not isinstance(output, list):
            raise LLMServiceError("reply has no output list")
        if not isinstance(usage, dict):
            raise LLMServiceError("reply has no usage")
        counts = {}
        for key in ("input_tokens", "output_tokens"):
            value = usage.get(key)
            if type(value) is not int or value < 0:
                raise LLMServiceError(f"usage.{key} must be a non-negative integer, got {value!r}")
            counts[key] = value
        parts = []
        for item in output:
            if isinstance(item, dict) and item.get("type") == "message" and isinstance(item.get("content"), list):
                parts += [p["text"] for p in item["content"]
                          if isinstance(p, dict) and p.get("type") == "output_text" and isinstance(p.get("text"), str)]
        # status "incomplete" (e.g. max_output_tokens) keeps whatever text arrived, possibly "": the agent turns an
        # unusable reply into an `error` outcome, and the tokens are still charged.
        return {"text": "".join(parts), "model_id": model_id, "usage": counts}
