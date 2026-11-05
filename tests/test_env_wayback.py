"""Wayback fetches dated on or before the released step's end, with fake HTTP.
No test here touches the network."""
import json

import httpx
import pytest

from apex.env_connector.wayback import MAX_CHARS, fetch
from apex.tools.files import ToolError

HEADER = ["timestamp", "original", "statuscode"]


class FakeHTTP:
    def __init__(self, stamps=("20250101120000", "20250104090000", "20250109080000"), page=None, fail=None):
        self.rows = [[s, "https://www.reuters.com/x", "200"] for s in stamps]
        self.page = page or (200, {}, "<html><script>bad()</script><style>.x{}</style><p>Hello</p>  world</html>")
        self.fail = fail
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            raise self.fail
        if "/cdx/search/cdx" in url:
            return 200, {}, json.dumps([HEADER] + self.rows)
        return self.page


def test_latest_snapshot_on_or_before_t():
    http = FakeHTTP()
    text = fetch("https://www.reuters.com/x", "2025-01-05", http=http)
    assert "to=20250105235959" in http.urls[0]
    assert "/web/20250104090000id_/https://www.reuters.com/x" in http.urls[1]
    assert text.startswith("snapshot 20250104090000 of https://www.reuters.com/x")
    assert "Hello world" in text and "bad()" not in text and ".x{}" not in text


def test_only_later_rows_refused():
    http = FakeHTTP(stamps=("20250109080000",))
    with pytest.raises(ToolError, match="no snapshot"):
        fetch("https://www.reuters.com/x", "2025-01-05", http=http)
    assert len(http.urls) == 1                                          # never fetched the late page


@pytest.mark.parametrize("url", ["https://evilreuters.com/x", "ftp://reuters.com/x", "https://example.com/",
                                 "https://reuters.com.evil.io/x", "not a url"])
def test_host_not_allowed_makes_no_request(url):
    http = FakeHTTP()
    with pytest.raises(ToolError):
        fetch(url, "2025-01-05", http=http)
    assert http.urls == []


def test_subdomain_allowed():
    assert "Hello" in fetch("https://www.federalreserve.gov/news", "2025-01-05", http=FakeHTTP())


def test_redirect_not_followed():
    http = FakeHTTP(page=(302, {"Location": "https://web.archive.org/web/2026/x"}, ""))
    with pytest.raises(ToolError, match="302"):
        fetch("https://www.reuters.com/x", "2025-01-05", http=http)
    assert len(http.urls) == 2


def test_late_memento_refused():
    http = FakeHTTP(page=(200, {"Memento-Datetime": "Fri, 10 Jan 2025 12:00:00 GMT"}, "<p>later</p>"))
    with pytest.raises(ToolError, match="after"):
        fetch("https://www.reuters.com/x", "2025-01-05", http=http)


def test_text_is_cut():
    http = FakeHTTP(page=(200, {}, "<p>" + "a" * 50_000 + "</p>"))
    text = fetch("https://www.reuters.com/x", "2025-01-05", http=http)
    assert len(text) <= MAX_CHARS + 200


def test_network_error_is_text():
    http = FakeHTTP(fail=httpx.ConnectError("boom"))
    with pytest.raises(ToolError, match="ConnectError"):
        fetch("https://www.reuters.com/x", "2025-01-05", http=http)


# ---- changes after the review ----------------------------------------------------------------------------------
@pytest.mark.parametrize("url", ["https://evil.com\\@reuters.com/x", "https://evil.com%2F@reuters.com/x",
                                 "https://user@reuters.com/x", "https://coindeKsk.com/x",
                                 "https://reuters.com。evil.io/x"])
def test_host_tricks_refused(url):
    http = FakeHTTP()
    with pytest.raises(ToolError):
        fetch(url, "2025-01-05", http=http)
    assert http.urls == []


def test_memento_offset_is_read_in_utc():
    http = FakeHTTP(page=(200, {"Memento-Datetime": "Sun, 05 Jan 2025 23:30:00 -0500"}, "<p>x</p>"))
    with pytest.raises(ToolError, match="after"):                       # 6 Jan 04:30 UTC
        fetch("https://www.reuters.com/x", "2025-01-05", http=http)


def test_cdx_object_is_a_tool_error():
    class Obj(FakeHTTP):
        def __call__(self, url):
            self.urls.append(url)
            return 200, {}, '{"error": "rate limited"}'
    with pytest.raises(ToolError):
        fetch("https://www.reuters.com/x", "2025-01-05", http=Obj())
