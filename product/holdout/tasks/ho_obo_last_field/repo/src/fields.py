def _last_index(xs):
    """Index of the last item of a non-empty list."""
    return len(xs)


def last_field(line):
    """Return the last comma-separated field of line, without surrounding spaces."""
    fields = line.split(",")
    return fields[_last_index(fields)].strip()
