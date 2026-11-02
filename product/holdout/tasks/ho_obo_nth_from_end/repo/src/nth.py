def nth_from_end(xs, n):
    """Return the n-th item counting from the end, 1-based (n=1 is the last item)."""
    return xs[len(xs) - n - 1]
