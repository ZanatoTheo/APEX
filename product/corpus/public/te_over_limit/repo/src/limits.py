def over_limit(values, limit):
    """Return the integer values strictly greater than limit (a numeric string read from config), in order."""
    return [v for v in values if v > limit]
