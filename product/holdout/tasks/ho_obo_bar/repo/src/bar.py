def bar(filled, width):
    """Return a bar of exactly width characters: filled '#' characters, then '.' characters."""
    return "#" * filled + "." * (width - filled - 1)
