def last_n(xs, n):
    """Return the last n items of xs (all of xs if n >= len(xs))."""
    if n <= 0:
        return []
    return xs[max(len(xs) - n + 1, 0):]
