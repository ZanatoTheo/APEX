def count_unique(rows):
    """Return how many distinct rows there are; each row is a list, and order inside a row matters."""
    return len(set(rows))
