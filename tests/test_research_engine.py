import pandas as pd
import pytest

from daytrade import backtest, data
from daytrade.research.engine import Det, Exit, Universe, detect, run

pytestmark = pytest.mark.skipif(not len(data.load("SPY", "1m")), reason="no archived data")


def test_engine_defaults_reproduce_locked_backtest():
    """The research engine at default switches must equal the locked strategy, trade for trade."""
    ref = backtest.run()
    ref = ref[ref["status"] == "traded"]
    U = Universe()
    got = run(U, detect(U, Det()), Exit())
    key = ["ticker", "day", "direction"]
    a = ref[key + ["r_net"]].assign(day=lambda x: x["day"].astype(str)).sort_values(key + ["r_net"])
    b = got[key + ["r_net"]].assign(day=lambda x: x["day"].astype(str)).sort_values(key + ["r_net"])
    assert len(a) == len(b)
    assert (a[key].to_numpy() == b[key].to_numpy()).all()
    assert a["r_net"].to_numpy() == pytest.approx(b["r_net"].to_numpy(), abs=1e-9)
    assert isinstance(got, pd.DataFrame)
