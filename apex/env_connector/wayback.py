"""wayback_fetch: archived web pages dated on or before the released step's end.

Only the Wayback Machine, only hosts on ALLOWED_HOSTS (a host or a subdomain of it), only snapshots whose
timestamp is <= as_of, fetched raw (`id_`) with no redirect followed. Errors are ToolErrors the agent can read.
`http(url) -> (status, headers, text)` can be passed in; tests never touch the network.
"""
import json
import re
from datetime import timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit

from apex.tools.files import ToolError

ALLOWED_HOSTS = (
    # central banks and statistics
    "federalreserve.gov", "ecb.europa.eu", "bls.gov", "bea.gov", "eia.gov", "treasury.gov",
    # financial news
    "reuters.com", "cnbc.com", "marketwatch.com", "finance.yahoo.com", "apnews.com",
    # crypto news
    "coindesk.com", "cointelegraph.com", "theblock.co",
)
MAX_CHARS = 12_000
TIMEOUT_S = 20
_NETLOC = re.compile(r"[A-Za-z0-9.-]+(:\d{1,5})?")      # no user@, no backslash, no %-escapes, ASCII only


def _default_http(url: str):
    import httpx
    r = httpx.get(url, timeout=TIMEOUT_S, follow_redirects=False, headers={"User-Agent": "apex-research/1.0"})
    return r.status_code, dict(r.headers), r.text


def allowed(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or not host or not _NETLOC.fullmatch(parts.netloc):
        return False
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


class _Text(HTMLParser):
    _SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _text(html: str) -> str:
    p = _Text()
    p.feed(html)
    return re.sub(r"\s+", " ", " ".join(p.parts)).strip()


def _get(http, url: str):
    try:
        return http(url)
    except Exception as e:                       # network errors, timeouts: the agent reads the reason
        raise ToolError(f"wayback request failed: {type(e).__name__}: {e}"[:300]) from None


def fetch(url: str, as_of: str, http=None, cache: dict | None = None) -> str:
    """The latest archived snapshot of `url` dated on or before `as_of` (YYYY-MM-DD), as plain text. `cache`: the
    caller's own {(original, timestamp): text} (a connector keeps one per run)."""
    if not isinstance(url, str) or not allowed(url):
        raise ToolError("url must be http(s) on an allowed host: " + ", ".join(ALLOWED_HOSTS))
    http = http or _default_http
    day = as_of.replace("-", "")
    cdx = ("https://web.archive.org/cdx/search/cdx?url=" + quote(url, safe="") + f"&to={day}235959"
           "&output=json&fl=timestamp,original,statuscode&filter=statuscode:200")
    status, _, body = _get(http, cdx)
    if status != 200:
        raise ToolError(f"wayback index answered {status}")
    try:
        rows = json.loads(body or "[]")
    except ValueError:
        raise ToolError("wayback index answer was not JSON") from None
    if not isinstance(rows, list):
        raise ToolError(f"wayback index answer was not a list: {str(rows)[:200]}")
    rows = [r for r in rows[1:] if isinstance(r, list) and len(r) >= 2 and isinstance(r[0], str)
            and isinstance(r[1], str) and r[0][:8].isdigit() and r[0][:8] <= day and allowed(r[1])]
    if not rows:
        raise ToolError(f"no snapshot of {url} on or before {as_of}")
    ts, original = max(rows, key=lambda r: r[0])[:2]
    key = (original, ts)
    if cache is not None and key in cache:
        return cache[key]
    status, headers, body = _get(http, f"https://web.archive.org/web/{ts}id_/{original}")
    if status != 200:
        raise ToolError(f"snapshot {ts} answered {status} (redirects are not followed)")
    memento = {k.lower(): v for k, v in (headers or {}).items()}.get("memento-datetime")
    if memento:
        try:
            dt = parsedate_to_datetime(memento)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            when = dt.astimezone(timezone.utc).strftime("%Y%m%d")
        except (TypeError, ValueError, IndexError):
            when = None
        if when is None or when > day:
            raise ToolError(f"snapshot is dated after {as_of}; refused")
    text = f"snapshot {ts} of {original}\n\n{_text(body or '')[:MAX_CHARS]}"
    if cache is not None:
        cache[key] = text
    return text
