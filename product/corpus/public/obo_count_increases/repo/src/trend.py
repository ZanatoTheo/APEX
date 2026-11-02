def _pairs(xs):
    """Return every pair of neighbouring items (xs[i], xs[i + 1])."""
    return [(xs[i], xs[i + 1]) for i in range(len(xs) - 2)]


def count_increases(xs):
    """Count how many items are larger than the item just before them."""
    return sum(b > a for a, b in _pairs(xs))
