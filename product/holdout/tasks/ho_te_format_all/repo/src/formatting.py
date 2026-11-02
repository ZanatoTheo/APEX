def format_all(values, template):
    """Fill template (a str.format template such as '<{}>') with each value; return the list of results."""
    return [template(v) for v in values]
