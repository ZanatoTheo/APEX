def _to_int(s):
    """Parse a numeric string that may have spaces around it."""
    return s.strip()


def elapsed(start, end):
    """Return end - start for two numeric strings."""
    return _to_int(end) - _to_int(start)
