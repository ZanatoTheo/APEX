def _ints(line):
    """Return the integers of a comma-separated line, as a list."""
    return map(int, line.split(","))


def count_above_mean(line):
    """Count the integers of a comma-separated line that are strictly above their mean."""
    xs = _ints(line)
    mean = sum(xs) / len(xs)
    return sum(x > mean for x in xs)
