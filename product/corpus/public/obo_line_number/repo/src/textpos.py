def _newlines_before(text, end):
    """Count the newline characters in text[:end]."""
    return text.count("\n", 0, end + 1)


def line_number(text, pos):
    """Return the 1-based line number of the character at index pos (a newline character belongs to the line it ends)."""
    return _newlines_before(text, pos) + 1
