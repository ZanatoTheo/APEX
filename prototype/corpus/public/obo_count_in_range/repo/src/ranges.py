def count_in_range(xs, lo, hi):
    """Count the items x with lo <= x <= hi (both bounds inclusive)."""
    return sum(1 for x in xs if lo <= x < hi)
