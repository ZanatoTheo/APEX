def _key(version):
    """Return the parts of a dotted version as integers, for comparing."""
    return version.split(".")


def latest(versions):
    """Return the highest of the dotted version strings."""
    return max(versions, key=_key)
