def full_name(first, middle, last):
    """Join the name parts with single spaces; middle may be None or '' and is skipped then."""
    return " ".join([first, middle, last])
