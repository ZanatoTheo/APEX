"""Offline tests for apex/llm_service.py: a local stub of the Responses API stands in for Meta's endpoint."""
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from apex import config, models
from apex.ledger import BlobStore
from apex.llm_service import API_KEY_ENV, LLMService, LLMServiceError
from apex.models import Budget, ModelClient, ModelError
from tests.test_llm_contract import contract_messages

KEY = "sk-test-SECRET"


def ok_body(text="hi", model="muse-spark-1.3", inp=12, out=5, before=()):
    return {"id": "resp_1", "object": "response", "status": "completed", "model": model,
            "output": [*before, {"type": "message", "role": "assistant",
                                 "content": [{"type": "output_text", "text": text, "annotations": []}]}],
            "usage": {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}}


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass   # the timeout test leaves the client gone before the stub answers


class StubAPI:
    """Records each request. Answers with the next queued (status, body), else self.status / self.body after
    self.delay seconds; with self.drip > 0 the body goes out one byte every `drip` seconds.
    The reply is fixed when the request arrives, so a slow handler never sees a later test's settings."""

    def __init__(self):
        self.requests = []
        self.queue = []
        self.reset()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                stub.requests.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(raw)})
                status, body, delay, drip = stub.next_reply()
                time.sleep(delay)
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for name, value in stub.headers_out.items():
                    self.send_header(name, value)
                self.end_headers()
                if drip:
                    for i in range(len(data)):
                        self.wfile.write(data[i:i + 1])
                        self.wfile.flush()
                        time.sleep(drip)
                else:
                    self.wfile.write(data)

            def do_GET(self):
                stub.requests.append({"method": "GET", "path": self.path, "headers": dict(self.headers), "body": None})
                status, body, _, _ = stub.next_reply()
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for name, value in stub.headers_out.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = _QuietServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def next_reply(self):
        if self.queue:
            status, body = self.queue.pop(0)
            return status, body, 0, 0
        return self.status, self.body, self.delay, self.drip

    def reset(self):
        self.status, self.body, self.delay, self.drip = 200, ok_body(), 0, 0
        self.headers_out = {}
        self.queue.clear()
        self.requests.clear()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class _StubCase(unittest.TestCase):
    """Stub server, config and key for the tests below (no tests of its own)."""
    @classmethod
    def setUpClass(cls):
        cls.stub = StubAPI()
        cls.cfg = config.load(overrides={"models": {
            "provider": "llm", "base_url": cls.stub.url, "request_timeout_s": 1,
            "subagent": {"model_id": "muse-spark-1.3"}, "mutation": {"model_id": "muse-code-test"}}})

    @classmethod
    def tearDownClass(cls):
        cls.stub.close()

    def setUp(self):
        self.stub.reset()
        env = mock.patch.dict(os.environ, {API_KEY_ENV: KEY})
        env.start()
        self.addCleanup(env.stop)
        self.service = LLMService(self.cfg)

    def call(self, role="subagent", messages=None, max_tokens=300):
        return self.service.complete(role, messages or contract_messages(), max_tokens)

    def assert_error(self, retryable):
        with self.assertRaises(LLMServiceError) as ctx:
            self.call()
        self.assertIs(ctx.exception.retryable, retryable)
        self.assertNotIn(KEY, str(ctx.exception))
        return ctx.exception


class LLMServiceTest(_StubCase):
    # ---- setup ----------------------------------------------------------------------------------------------
    def test_missing_key_is_a_clear_error(self):
        for value in (None, ""):
            with mock.patch.dict(os.environ):
                os.environ.pop(API_KEY_ENV, None)
                if value is not None:
                    os.environ[API_KEY_ENV] = value
                with self.assertRaises(LLMServiceError) as ctx:
                    LLMService(self.cfg)
                self.assertIn("MODEL_API_KEY", str(ctx.exception))

    def test_load_service_returns_the_real_service(self):
        self.assertIsInstance(models.load_service(self.cfg), LLMService)

    # ---- request --------------------------------------------------------------------------------------------
    def test_request_shape(self):
        msgs = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "task"},
                {"role": "assistant", "content": '{"outcome": "read_file"}'}, {"role": "user", "content": "out"}]
        self.call("subagent", msgs, 321)
        req = self.stub.requests[-1]
        self.assertEqual(req["path"], "/responses")
        self.assertEqual(req["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertEqual(req["headers"]["Content-Type"], "application/json")
        self.assertEqual(req["body"], {"model": "muse-spark-1.3", "instructions": "SYS", "input": msgs[1:],
                                       "max_output_tokens": 321, "store": False})
        self.stub.body = ok_body(model="muse-code-test")
        self.call("mutation", msgs, 50)
        self.assertEqual(self.stub.requests[-1]["body"]["model"], "muse-code-test")

    def test_key_whitespace_is_stripped(self):
        with mock.patch.dict(os.environ, {API_KEY_ENV: f"  {KEY}\r\n"}):
            LLMService(self.cfg).complete("subagent", contract_messages(), 10)
        self.assertEqual(self.stub.requests[-1]["headers"]["Authorization"], f"Bearer {KEY}")

    def test_redirects_are_refused_and_the_key_stays_home(self):
        other = StubAPI()
        self.addCleanup(other.close)
        self.stub.status, self.stub.body = 302, b""
        self.stub.headers_out = {"Location": other.url + "/responses"}
        err = self.assert_error(retryable=False)
        self.assertIn("302", str(err))
        self.assertEqual(other.requests, [])

    def test_long_error_text_is_scrubbed_before_it_is_cut(self):
        self.stub.status, self.stub.body = 401, {"error": {"message": "x" * 295 + KEY}}
        self.assertNotIn(KEY[:5], str(self.assert_error(retryable=False)))

    def test_trailing_slash_in_base_url(self):
        cfg = config.load(overrides={"models": {"provider": "llm", "base_url": self.stub.url + "/",
                                                "subagent": {"model_id": "muse-spark-1.3"}}})
        LLMService(cfg).complete("subagent", contract_messages(), 10)
        self.assertEqual(self.stub.requests[-1]["path"], "/responses")

    # ---- reply ----------------------------------------------------------------------------------------------
    def test_reply_mapping(self):
        self.stub.body = ok_body(text='{"outcome": "give_up", "args": {}}', inp=40, out=9)
        self.assertEqual(self.call(), {"text": '{"outcome": "give_up", "args": {}}', "model_id": "muse-spark-1.3",
                                       "usage": {"input_tokens": 40, "output_tokens": 9}})

    def test_reasoning_items_skipped_and_text_parts_joined(self):
        body = ok_body(before=[{"type": "reasoning", "id": "rs_1", "summary": []}])
        body["output"][-1]["content"] = [{"type": "output_text", "text": "ab"}, {"type": "output_text", "text": "cd"}]
        self.stub.body = body
        self.assertEqual(self.call()["text"], "abcd")

    def test_incomplete_reply_gives_partial_or_empty_text(self):
        body = ok_body()
        body.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"},
                    output=[{"type": "reasoning", "id": "rs_1", "summary": []}])
        self.stub.body = body
        self.assertEqual(self.call()["text"], "")
        body = ok_body(text='{"outc')
        body.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        self.stub.body = body
        self.assertEqual(self.call()["text"], '{"outc')

    def test_malformed_replies_raise(self):
        no_output = ok_body(); del no_output["output"]
        no_usage = ok_body(); del no_usage["usage"]
        no_model = ok_body(); del no_model["model"]
        float_tokens = ok_body(); float_tokens["usage"]["input_tokens"] = 1.5
        bool_tokens = ok_body(); bool_tokens["usage"]["output_tokens"] = True
        negative = ok_body(); negative["usage"]["output_tokens"] = -1
        failed = ok_body(); failed.update(status="failed", error={"code": "server_error", "message": "boom"})
        for body in (b"not json", b"[1, 2]", no_output, no_usage, no_model, float_tokens, bool_tokens, negative,
                     failed):
            with self.subTest(body=body):
                self.stub.body = body
                self.assert_error(retryable=True)

    # ---- errors ---------------------------------------------------------------------------------------------
    def test_server_errors_are_retryable(self):
        for status in (500, 429, 503):
            with self.subTest(status=status):
                self.stub.status, self.stub.body = status, {"error": {"message": "overloaded, try later"}}
                err = self.assert_error(retryable=True)
                self.assertIn(str(status), str(err))
                self.assertIn("overloaded", str(err))

    def test_client_errors_are_not_retryable(self):
        for status in (400, 401, 403, 404, 422):
            with self.subTest(status=status):
                self.stub.status, self.stub.body = status, {"error": {"message": "bad request"}}
                self.assertIn(str(status), str(self.assert_error(retryable=False)))

    def test_error_body_that_is_not_json(self):
        self.stub.status, self.stub.body = 502, b"<html>Bad gateway</html>"
        self.assertIn("502", str(self.assert_error(retryable=True)))

    def test_timeout_is_retryable(self):
        self.stub.delay = 1.5
        self.assertIn("timed out", str(self.assert_error(retryable=True)))

    def test_slow_drip_body_hits_the_total_deadline(self):
        self.stub.body = ok_body(text="x" * 200)          # ~400 bytes at 0.05 s each: ~20 s without a deadline
        self.stub.drip = 0.05
        start = time.monotonic()
        self.assertIn("timed out", str(self.assert_error(retryable=True)))
        self.assertLess(time.monotonic() - start, 3)

    def test_connection_refused_is_retryable(self):
        with socket.socket() as s:                        # a port that nothing listens on
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        cfg = config.load(overrides={"models": {"provider": "llm", "base_url": f"http://127.0.0.1:{port}",
                                                "request_timeout_s": 1}})
        with self.assertRaises(LLMServiceError) as ctx:
            LLMService(cfg).complete("subagent", contract_messages(), 10)
        self.assertTrue(ctx.exception.retryable)

    def test_key_echoed_by_the_api_is_scrubbed(self):
        self.stub.status, self.stub.body = 401, {"error": {"message": f"invalid key {KEY}"}}
        self.assertIn("***", str(self.assert_error(retryable=False)))
        failed = ok_body()
        failed.update(status="failed", error={"message": f"bad token {KEY}"})
        self.stub.status, self.stub.body = 200, failed
        self.assertIn("***", str(self.assert_error(retryable=True)))

    def test_retry_after_a_server_error_succeeds(self):
        self.stub.queue = [(503, {"error": {"message": "busy"}})]
        with tempfile.TemporaryDirectory() as tmp:
            client = ModelClient(self.service, self.cfg, BlobStore(Path(tmp)), Budget(10**7, 0), sleep=lambda s: None)
            c = client.complete("subagent", contract_messages())
        self.assertEqual((c.text, c.tokens), ("hi", 17))
        self.assertEqual(len(self.stub.requests), 2)

    # ---- through ModelClient --------------------------------------------------------------------------------
    def test_recorded_blob_never_holds_the_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            blobs = BlobStore(Path(tmp))
            c = ModelClient(self.service, self.cfg, blobs, Budget(10**7, 0)).complete("subagent", contract_messages())
            self.assertTrue(blobs.has(c.record_hash))
            self.assertEqual(c.tokens, 17)
            files = [p for p in Path(tmp).rglob("*") if p.is_file()]
            self.assertTrue(files)
            for p in files:
                self.assertNotIn(KEY.encode(), p.read_bytes())

    def test_served_model_must_match_the_pin(self):
        self.stub.body = ok_body(model="muse-spark-1.4")
        with tempfile.TemporaryDirectory() as tmp:
            client = ModelClient(self.service, self.cfg, BlobStore(Path(tmp)), Budget(10**7, 0))
            with self.assertRaises(ModelError) as ctx:
                client.complete("subagent", contract_messages())
        self.assertIn("pin mismatch", str(ctx.exception))


class ListModelsTest(_StubCase):
    """GET {base_url}/models: helps find the exact model IDs to pin. Inherits the stub and the key setup."""

    def test_lists_sorted_ids(self):
        self.stub.body = {"object": "list", "data": [{"id": "muse-spark-1.3", "object": "model"},
                                                     {"id": "muse-code-1.0", "object": "model"}]}
        self.assertEqual(self.service.list_models(), ["muse-code-1.0", "muse-spark-1.3"])
        req = self.stub.requests[-1]
        self.assertEqual((req["method"], req["path"]), ("GET", "/models"))
        self.assertEqual(req["headers"]["Authorization"], f"Bearer {KEY}")

    def test_http_error_and_bad_shape(self):
        self.stub.status, self.stub.body = 401, {"error": {"message": "invalid key"}}
        with self.assertRaises(LLMServiceError) as ctx:
            self.service.list_models()
        self.assertFalse(ctx.exception.retryable)
        for body in ({}, {"data": "x"}, {"data": [{"name": "no id"}]}):
            with self.subTest(body=body):
                self.stub.status, self.stub.body = 200, body
                with self.assertRaises(LLMServiceError):
                    self.service.list_models()


class ConfigKeysTest(unittest.TestCase):
    def test_defaults_point_at_meta(self):
        cfg = config.load()
        self.assertEqual(cfg["models"]["base_url"], "https://api.meta.ai/v1")
        self.assertEqual(cfg["models"]["request_timeout_s"], 120)

    def test_base_url_must_be_https_or_local(self):
        for url in ("http://api.meta.ai/v1", "ftp://x", "api.meta.ai/v1", "http://127.0.0.1.evil.com",
                    "https://api.meta.ai/v1\n", " https://api.meta.ai/v1", "https://api.meta.ai/v1 x"):
            with self.subTest(url=url), self.assertRaises(config.ConfigError):
                config.load(overrides={"models": {"base_url": url}})
        for url in ("https://api.meta.ai/v1", "http://127.0.0.1:8080", "http://localhost:1/v1"):
            config.load(overrides={"models": {"base_url": url}})

    def test_timeout_must_be_positive(self):
        with self.assertRaises(config.ConfigError):
            config.load(overrides={"models": {"request_timeout_s": 0}})


if __name__ == "__main__":
    unittest.main()
