"""Starter strategy: equal weight over the assets that have a price so far. Replace it with your own."""


def weights(history):
    if len(history.close) == 0:
        return {}
    last = history.close.ffill().iloc[-1]
    names = [a for a in history.assets if a in last.index and last[a] == last[a]]   # x == x is False for NaN
    return {a: 1 / len(names) for a in names} if names else {}
