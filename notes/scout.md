# Scout notes (max ~150 lines)

## Last run: 2026-10-27
- Run reason: scheduled scouting (1 idea waiting, target 5)
- Ideas in registry at start: insider-officer-buys (1 total, stage=idea)
- Budget state: insider family has 1 holdout used; earnings_events 4832 variants 2 holdouts (heavily mined); all other families fresh

## What was done
- Wrote 4 new idea card files to ideas/
- Could NOT register in CSV: Bash denied + registry/ directory denied for Edit
- Left exact registration commands in outbox for user/dispatcher to run

## 4 ideas proposed (files written, registry add PENDING)
1. **turn-of-month** (calendar_effects, 4d, 10 bps) — TOM effect; structural fund-flow mechanism; daily OHLCV only; no graveyard conflict
2. **insider-cluster-buys** (insider, 3-5d, 15 bps) — 2+ insiders buying same stock in 5-day window; SEC Form 345 data available; distinct from single-officer queued idea
3. **sp-reconstitution** (index_events, 3-7d, 25 bps) — S&P 400/600 addition drift; forced index buying; NEEDS announcement dates scraped from spglobal.com
4. **earnings-contagion** (earnings_events, 1-3d, 12 bps) — buy sector peers on large-cap earnings beat; cross-firm information transfer; NOT PEAD; needs GICS mapping from yfinance

## Commands needed to register (run in team folder)
```
python tools/ideas.py add --id turn-of-month --family calendar_effects --horizon 4d --summary "Buy last trading day of month; sell 3rd trading day of new month (TOM effect)" --mechanism "Month-end fund flows (401k/dividends/rebalancing) drive structural buying pressure at month turn" --data "daily() OHLCV only - no additional data needed" --cost 10 --source "McConnell & Xu (2008) FAJ; Ariel (1987) JFE"

python tools/ideas.py add --id insider-cluster-buys --family insider --horizon 3-5d --summary "Buy when 2+ insiders independently buy same stock within 5 calendar days ($25k+ each)" --mechanism "Independent convergence of multiple insiders is high-information signal; market slow to aggregate staggered Form 4 filings" --data "insider() SEC Form 345 + daily() prices - both in archives" --cost 15 --source "Lakonishok & Lee (2001) RFS; Seyhun (1998)"

python tools/ideas.py add --id sp-reconstitution --family index_events --horizon 3-7d --summary "Buy S&P 400/600 additions at announcement; exit at effective date" --mechanism "Forced index-fund buying creates predictable demand shock between announcement and effective date; less arbitraged than S&P 500 additions" --data "NEEDS: S&P 400/600 reconstitution announcement dates - free one-time scrape from spglobal.com; NOT in current archives" --cost 25 --source "Chen Noronha & Singal (2004); Harris & Gurel (1986)"

python tools/ideas.py add --id earnings-contagion --family earnings_events --horizon 1-3d --summary "Buy sector peers when large-cap announces big earnings beat (short on big miss)" --mechanism "Cross-firm information transfer: sector-level earnings signal reaches peer firms 1-3 days after announcing firm" --data "earnings() + daily() in archives; needs GICS sector mapping (free via yfinance)" --cost 12 --source "Thomas & Zhang (2008) JAR; Ramnath (2002) JAR"
```

## Sources/areas checked this run
- Academic: McConnell & Xu 2008, Ariel 1987, Lakonishok & Lee 2001, Seyhun 1998, Chen et al 2004, Harris & Gurel 1986, Thomas & Zhang 2008, Ramnath 2002
- Webull: market sectors (semiconductors +2.48%, TOM signal for sectors approach plausible)
- Graveyard checked: no conflicts found (analyst rating actions ≠ earnings contagion; overnight reversal ≠ TOM; no index event or calendar ideas listed)

## Watch for next run
- Was registration completed? Check ideas.csv for these 4 entries
- sp-reconstitution needs data sourcing before it can be queued - flag to Director
- If insider-cluster-buys gets queued, note it shares the insider holdout count with insider-officer-buys
- calendar_effects is a new family: trial budget starts at 0
- earnings-contagion: Director should note the earnings_events family is heavily mined; bar will be high

## Graveyard check (done 2026-10-27)
- Liquidity sweep reversal, C6, intraday patterns: price/volume exhausted
- PEAD/ESUR, analyst rating actions, earnings-gap continuation: tested directionally; earnings-contagion is peer-firm mechanism (not same idea)
- Daily classics (RSI2, IBS, gap fade, overnight reversal): different from TOM calendar mechanism
- Insider: 1 holdout used; cluster buys not previously tested
