"""Download free event data for the event-driven families (PROTOCOL12).

  python -m daytrade.research.events_fetch yahoo     # earnings dates + analyst rating changes
  python -m daytrade.research.events_fetch insider   # SEC Form 3/4/5 data sets -> open-market buys/sells

Resumable: one parquet per ticker / per quarter; existing files are skipped.
"""

from __future__ import annotations

import io
import sys
import time
import zipfile

import pandas as pd
import requests

from ..config import DATA_DIR
from .daily import universe

EDIR = DATA_DIR.parent / "events"
SEC_UA = "StockAnalysis research nickcuda1228@gmail.com"


def fetch_yahoo():
    import yfinance as yf
    (EDIR / "earnings").mkdir(parents=True, exist_ok=True)
    (EDIR / "ratings").mkdir(parents=True, exist_ok=True)
    tickers = sorted(set(universe("sp500") + universe("sp400") + universe("sp600")))
    for i, t in enumerate(tickers):
        fe, fr = EDIR / "earnings" / f"{t}.parquet", EDIR / "ratings" / f"{t}.parquet"
        if fe.exists() and fr.exists():
            continue
        for attempt in range(3):
            try:
                tk = yf.Ticker(t.replace(".", "-"))
                if not fe.exists():
                    e = tk.get_earnings_dates(limit=100)
                    e = (e if e is not None else pd.DataFrame()).reset_index()
                    e.columns = [str(c) for c in e.columns]
                    e.to_parquet(fe)
                if not fr.exists():
                    r = tk.upgrades_downgrades
                    r = (r if r is not None else pd.DataFrame()).reset_index()
                    r.columns = [str(c) for c in r.columns]
                    r.to_parquet(fr)
                break
            except Exception as ex:  # noqa: BLE001 - network/throttle; retry then move on
                print(f"{t} attempt {attempt}: {ex}", flush=True)
                time.sleep(10 * (attempt + 1))
        if i % 50 == 0:
            print(f"{i}/{len(tickers)} {t}", flush=True)
        time.sleep(0.4)


def fetch_insider(first=(2006, 1), last=(2026, 3)):
    out = EDIR / "insider"
    out.mkdir(parents=True, exist_ok=True)
    y, q = first
    while (y, q) <= last:
        f = out / f"{y}q{q}.parquet"
        if not f.exists():
            url = (f"https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/"
                   f"{y}q{q}_form345.zip")
            r = requests.get(url, headers={"User-Agent": SEC_UA}, timeout=300)
            if r.status_code != 200:
                print(f"{y}q{q}: HTTP {r.status_code}", flush=True)
            else:
                z = zipfile.ZipFile(io.BytesIO(r.content))
                rd = lambda n: pd.read_csv(z.open(n), sep="\t", dtype=str, low_memory=False)  # noqa: E731
                sub = rd("SUBMISSION.tsv")[["ACCESSION_NUMBER", "FILING_DATE", "ISSUERTRADINGSYMBOL",
                                            "DOCUMENT_TYPE"]]
                nd = rd("NONDERIV_TRANS.tsv")
                nd = nd[nd["TRANS_CODE"].isin(["P", "S"])]
                nd = nd[["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                         "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD"]]
                own = rd("REPORTINGOWNER.tsv")[["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP",
                                                "RPTOWNER_TITLE"]]
                own = own.drop_duplicates("ACCESSION_NUMBER")
                df = nd.merge(sub, on="ACCESSION_NUMBER").merge(own, on="ACCESSION_NUMBER", how="left")
                df.to_parquet(f)
                print(f"{y}q{q}: {len(df)} P/S rows", flush=True)
            time.sleep(1.0)
        q += 1
        if q == 5:
            y, q = y + 1, 1


if __name__ == "__main__":
    {"yahoo": fetch_yahoo, "insider": fetch_insider}[sys.argv[1]]()
