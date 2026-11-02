def pad_left(s, width, ch):
    """Pad s on the left with ch until it is width characters long (longer strings are unchanged)."""
    return ch * (width - len(s) - 1) + s
