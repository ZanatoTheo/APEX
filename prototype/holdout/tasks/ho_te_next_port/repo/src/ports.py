def next_free_port(spec):
    """Return one more than the largest port in a comma-separated spec, e.g. '80,443' -> 444."""
    ports = spec.split(",")
    return max(ports) + 1
