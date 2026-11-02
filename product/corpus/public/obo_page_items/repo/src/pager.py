def _offset(n, size):
    """Index of the first item on page n (pages are 1-based)."""
    return n * size


def page(items, n, size):
    """Return page n (1-based) of items, size items per page."""
    start = _offset(n, size)
    return items[start:start + size]
