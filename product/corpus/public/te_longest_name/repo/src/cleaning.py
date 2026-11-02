def _clean(name):
    """Return name without surrounding spaces."""
    name.strip()


def longest_name(names):
    """Return the length of the longest name, ignoring surrounding spaces."""
    return max(len(_clean(n)) for n in names)
