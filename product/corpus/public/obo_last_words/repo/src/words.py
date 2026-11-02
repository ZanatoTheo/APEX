def _tail(xs, k):
    """Return the last k items of xs (all of xs when k >= len(xs))."""
    start = max(len(xs) - k + 1, 0)
    return xs[start:]


def last_words(text, k):
    """Return the last k words of text, joined by single spaces."""
    return " ".join(_tail(text.split(), k))
