def chunk(xs, n):
    """Split xs into consecutive pieces of length n (the last piece may be shorter)."""
    return [xs[i:i + n] for i in range(0, len(xs) - 1, n)]
