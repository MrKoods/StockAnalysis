# earnings-contagion

## Mechanism
When a large-cap firm in a sector reports earnings that beat or miss consensus by a large margin, peer firms in the same sector drift in the same direction over the next 1-3 days, even before they have reported. Analysts and institutional investors update their sector-level expectations and systematically re-price peers. The announcing firm's initial reaction is already traded; the alpha is in the PEER firms that have not yet moved.

**Who is on the other side?** Passive holders of peer firms who are slow to connect the sector-level signal from one firm's earnings to their own holdings; they sell at open the next day when the full impact is priced. We are the early buyers.

**Key difference from PEAD/ESUR (graveyard):** PEAD is drift of the ANNOUNCING firm. Earnings contagion is drift of PEER firms that have NOT yet announced. Different signal, different trade, different mechanism.

## Evidence
- Thomas & Zhang (2008) "Overreaction to Intra-Industry Information Transfers?" - JAR: peers drift in the direction of large earnings surprises; information transfer is predictable
- Ramnath (2002) "Investor and Analyst Reactions to Earnings Announcements of Related Firms" - JAR: analyst revisions for peers follow industry leaders by 1-3 days
- Foster (1981): first to document industry earnings contagion (earnings of large firms predict peers' stock returns)
- Han, Wild & Ramesh (1989): magnitude of peer drift is larger when announcing firm is more central to the industry
- Practitioners: "sector sympathy" trades are well-known around tech earnings (MSFT/GOOG/META influencing each other's peers)

## Rule sketch
- Universe: S&P 500 + S&P 400 (1,000 names), grouped by GICS sector/sub-industry
- Signal: on date E, a firm with market cap >= $10B reports earnings surprise > +5% (or < -5%)
  - "Announcing firm" (AF): the one reporting
  - "Peer firms" (PF): same GICS sub-industry, NOT yet reported in current quarter, excluding AF
- Entry: buy (or short) peer firms at open on E+1
- Exit: close at open on E+3 (2 trading days held) or at E+2 close
- Direction: same direction as AF surprise (positive surprise → long peers; negative → short peers)
- Variants: sub-industry vs sector; market cap cutoff for AF; surprise threshold; hold period 1/2/3 days

## Data
- earnings() for EPS surprise + announcement dates: fully in archives (2000+)
- daily() for prices: fully in archives
- Sector/sub-industry: needs a GICS mapping; can be derived from the universe CSVs or fetched via yfinance
- No additional external data needed; all testable today

## Horizon
1-3 trading days

## Cost estimate
~12 bps round trip (S&P 500 peers = liquid; S&P 400 peers = ~20 bps)

## Why it might NOT work
1. earnings_events family already has 4,832 search variants and 2 holdouts - the multiple comparison bar is high
2. Analysts now update peer estimates same-day or pre-market → drift may be priced within hours (would need hourly data to capture)
3. Tech mega-caps (MSFT, GOOG, META, AMZN) report at staggered times; the sympathy trade may be well-arbitraged already
4. GICS sub-industry groups can be small (2-3 firms) → sparse; need to define peer similarity carefully

## Differs from graveyard
- PEAD/ESUR (graveyard): trades the ANNOUNCING firm's post-earnings drift
- Earnings contagion: trades PEER firms not yet announced; mechanism is cross-firm information transfer, not momentum in the announcing name
- Analyst rating actions (graveyard): directional trades on rating changes; contagion is about earnings info transfer

## Source
Thomas & Zhang (2008): https://doi.org/10.1111/j.1475-679X.2008.00282.x
Ramnath (2002): https://doi.org/10.2308/accr.2002.77.4.1265
Foster (1981): https://doi.org/10.2307/2490926
