# Holdout shortlist — written 2026-10-06 BEFORE any holdout evaluation

Chosen on structural consistency across search families, not single best score.

| id | detection | exit | why |
|----|-----------|------|-----|
| C0 | locked rules (1m) | locked (level TP, min_r 1.5) | reference |
| C1 | wide: reclaim 6, choch 40, timeout 30 | locked | more trades, mean held across exits |
| C2 | wide | stop +0.05 ATR, min_r 1.0, max hold 30 | wider stop + time stop helped on average |
| C3 | locked | stop +0.05 ATR, min_r 1.0, max hold 30 | same exit change alone |
| C4 | wide | fixed 1R target | simplest, most trades |
| C5 | 5m base (sweep on 15m) | locked | longer-history variant |
| C6 | 5m base, close_out trigger | fixed 2R | best consistent 5m row |

Holdout: 1m = 2026-09-24..10-05 (8 sessions); 5m = 2026-08-24..10-05.
Pass (per candidate): n >= 40, mean net R >= +0.10, day-clustered t >= 2.4
(Bonferroni for 7 candidates, ~p<0.05 one-sided), and mean still > 0 without the best 5 trades.
"Promising" = mean >= +0.10 and t >= 1.5 but short of Bonferroni.
