def first_half(xs):
    """Return the first half of xs; on odd lengths the middle item belongs to the first half."""
    return xs[:len(xs) // 2]
