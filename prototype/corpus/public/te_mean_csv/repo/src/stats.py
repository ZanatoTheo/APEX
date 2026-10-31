def mean_of_csv(line):
    """Return the floor of the mean of a comma-separated line of integers, e.g. '1,2,3' -> 2."""
    parts = line.split(",")
    return sum(parts) // len(parts)
