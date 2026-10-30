# Scout

Find **new, testable** short-horizon trading ideas. Quality over quantity: add at most 3 per run; 0 is fine.

1. Read `notes/scout.md`, `registry/graveyard.md` (dead ideas - never re-propose them or a renamed variant),
   `python tools/ideas.py list`, and `python tools/budget.py` (families already mined hard).
2. Search for ideas with a **mechanism** - who is on the other side and why they pay you (forced flows,
   index rebalances, liquidity provision, behavioural over/under-reaction to events, information leakage,
   calendar/settlement effects, short-sale constraints). Sources: academic papers (SSRN, arXiv q-fin, journals),
   practitioner research, replication studies (note when an effect was found to decay after publication).
   Webull tools give live market colour (unusual activity, gainers/losers, earnings calendar, news, capital flow)
   - use them to sanity-check that an idea's setup actually occurs now, a few calls per run, not for bulk data.
3. Keep only ideas that are:
   - testable NOW with `tools/research_data.py` alone (its loaders: daily OHLCV 1999+, hourly 2023-11+, 5-min,
     1-min, earnings, insider, ratings, universe sp500/400/600). Every input of the rule - including event
     dates such as announcements, index changes or filings - must come from one of those loaders. If it needs a
     scrape or any other new data, do NOT add it: list it under "Needs data" in `notes/scout.md` (one line) so
     the user can decide whether that data is worth getting;
   - left with an untouched holdout: the `data` column of the family's rows in `registry/trials.csv` lists the
     periods already searched or held out; what remains must include a clean multi-year window. A family whose
     periods are all used cannot be tested honestly - don't propose it;
   - holding period <= ~5 trading days (shorter preferred, if costs allow);
   - plausible after realistic costs (>= 10 bps round trip large caps, 20-40 bps small caps);
   - paper-tradable by `tools/paper_runner.py` (daily signal after the close, entry next open, exit at an open or
     close N sessions later, optional stop/target) - or flag that it needs a different engine.
4. For each kept idea: write `ideas/<id>.md` (mechanism, evidence with links, exact rule sketch, data, horizon,
   cost estimate, why it might NOT work, how it differs from graveyard entries), then add it:
   `python tools/ideas.py add --id <slug> --family <family> --horizon <e.g. 1d> --summary "..." --mechanism "..."
   --data "..." --cost <bps> --source "<link/citation>"`. Reuse an existing family name when it fits (the
   trial budget is per family); otherwise a new short snake_case family.
5. Outbox: `💡 Scout <date>: <n> new idea(s)` then one line each (id - summary - why it might work).
