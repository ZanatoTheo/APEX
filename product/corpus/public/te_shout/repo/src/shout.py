def shout(word, times):
    """Return word in upper case, repeated times times, joined by single spaces (times: int or numeric str)."""
    return " ".join([word.upper()] * times)
