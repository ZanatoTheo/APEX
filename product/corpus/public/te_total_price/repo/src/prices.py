def total_price(rows):
    """Sum the prices in (name, price) rows read from a CSV, where price is a string such as '12'."""
    return sum(price for _, price in rows)
