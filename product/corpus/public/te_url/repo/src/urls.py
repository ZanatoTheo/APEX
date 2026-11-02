def _query(params):
    """Return 'k=v' pairs sorted by key and joined by '&'."""
    return "&".join(k + "=" + v for k, v in sorted(params.items()))


def url(path, params):
    """Return path, plus '?' and the query string when params is not empty."""
    return path + ("?" + _query(params) if params else "")
