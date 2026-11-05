"""The toy connector, but releasing step 5 sleeps for an hour: a run that is still going while a test reads its
output or kills it (tests/test_live_risks.py, risks 6-7)."""
import time

from tests.fixtures.toy_connector import ToyConnector


class SlowToy(ToyConnector):
    def release(self, step: int) -> None:
        if step == 5:
            time.sleep(3600)
        super().release(step)


def make_connector(cfg, data=None):
    return SlowToy(cfg, data)
