def page_count(total_items, per_page):
    """Number of pages needed to show total_items items, per_page items per page."""
    return total_items // per_page
