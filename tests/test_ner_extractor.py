"""
Regression guard for shared/utils/ner_extractor.py's _TICKER_TO_COMPANY alias table.

regional_banks (v2.2.10) and healthcare (v2.2.24) both shipped without entries
in this table, silently scoring News=0.0/15 for every ticker in that sector for
weeks before anyone noticed live — bare ticker symbols like "ZION"/"HBAN" almost
never appear literally in a headline (coverage uses company names), so every
headline fell through to the ticker-symbol-only fallback and never matched.
consumer_discretionary was caught manually during its own rollout by a live
API test, not by an automated check. This test makes sure the next sector
doesn't need a human to catch it again.
"""
import yaml

from shared.utils.ner_extractor import _TICKER_TO_COMPANY
from shared.utils.sector_config import get_all_tickers


class TestNerAliasCoverage:
    def test_every_active_ticker_has_an_alias_entry(self):
        cfg = yaml.safe_load(open("config/swing_config.yaml").read())
        tickers = get_all_tickers(cfg)

        missing = [t for t in tickers if t not in _TICKER_TO_COMPANY]
        assert not missing, (
            f"No _TICKER_TO_COMPANY entry for: {missing} — headlines will fall through "
            f"to the bare-ticker-symbol fallback and likely never match, silently "
            f"zeroing News for these tickers. Add entries in shared/utils/ner_extractor.py."
        )

