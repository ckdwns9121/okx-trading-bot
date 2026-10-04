# Funding-rate carry on OKX — research note (2026-10-04)

**Question.** Can a spot-long / perp-short carry that only enters when OKX
funding is extreme earn enough after costs to be worth building?

**Verdict: no, not on OKX under its current funding formula.** The positive side
of OKX funding is structurally pinned near 0.01%/8h, so there is nothing
"extreme" to select; the always-in version nets roughly 3–7%/yr on capital,
which is savings-account territory with execution risk attached. Recorded here
so the idea is not re-opened without new information.

Reproduce: `cd bot && .venv/bin/python -m scripts.research_funding_carry --days 730`
(data cached under `bot/state/research_cache/`, read-only, no orders).

## What OKX actually pays

OKX revised its funding formula in April 2025 ([announcement](https://www.okx.com/en-us/help/important-update-revision-of-the-funding-rate-formula-for-okx-perpetual)):

```
funding = clamp( avg_premium + clamp(interest − avg_premium, −0.05%, +0.05%), cap, floor )
interest = 0.03% / 3 settlements = 0.01% per 8h
```

For any 8-hour average premium between **−0.04% and +0.06%** the inner clamp
cancels the premium and funding is **exactly 0.01%**. Only a sustained premium
above 0.06% lifts funding (to `premium − 0.05%`), and per-instrument caps sit on
top of that.

Observed in the ~3 months of history OKX exposes (2026-06-29 → 2026-10-04,
291 settlements per instrument):

| inst | mean /8h | ≈ /yr gross | max | min | settlements exactly at 0.0100% |
|---|---|---|---|---|---|
| BTC-USDT-SWAP | 0.0052% | 5.7% | 0.0100% | −0.0039% | 13% (p95 = cap) |
| ETH-USDT-SWAP | 0.0040% | 4.4% | 0.0100% | −0.0060% | 9% |
| SOL-USDT-SWAP | 0.0030% | 3.3% | 0.0100% | −0.0115% | 18% |
| DOGE-USDT-SWAP | 0.0065% | 7.2% | 0.0100% | −0.0072% | 38% |
| PEPE / HYPE / WLD / ZEC | 0.005% | ~5.5% | 0.035% / 0.028% / 0.010% / 0.010% | down to −0.04% | 35–49% |

Not one BTC/ETH/SOL/DOGE settlement reached 0.03%/8h. The negative tail is
wider than the positive one, which is the wrong way round for a long-spot /
short-perp carry (you are in the trade when it flips against you).

## Cost model

- Spot taker 0.10% + perp taker 0.05% per side → 0.30% of notional per round trip
- Half-spread on four fills ≈ 0.04–0.08%
- Capital tied up = spot notional + 50% margin for the short → 1.5× notional
- Basis P&L included (short perp gains when the premium shrinks between entry and exit)

## Simulation on real funding (last 3 months) and the always-in case

With real OKX funding the always-in carry on $10k notional ($15k capital) nets
about 3.8%/yr (BTC), 3.0% (ETH), −1.3% (SOL), 1.5% (DOGE) once fees and the
negative settlements are included. Threshold rules (enter ≥ 0.01–0.03%/8h,
exit at a third of that) trade rarely, spend 1–3 round trips of fees per entry,
and land at 0–2%/yr. None beats simply holding USDT in a savings product.

## Why the two-year extension is not trustworthy

OKX only publishes ~3 months of funding history. Two proxies were tried to
extend to 24 months of hourly data:

1. Linear regression `funding ≈ a + b·basis` on the overlap — R² 0.31–0.46.
2. OKX's exact formula applied to hourly perp/spot close basis as the premium
   index — R² 0.18 (BTC), 0.44 (ETH), **negative** for SOL and DOGE.

The premium index OKX uses is built from order-book impact prices averaged
per minute; hourly close-to-close basis is far too noisy a stand-in, especially
for thin alts. Binance funding (uncapped, years of history) correlates with
OKX at only 0.52 over the overlap because OKX's clamp removes exactly the
excursions that matter. So the honest evidence base is the 3 months of real
data plus the formula itself, and both say the same thing.

## What would change the conclusion

- Trading the carry on a venue whose funding is **not** clamped to a base rate
  (Binance/Bybit) — requires a second exchange integration and keys.
- Harvesting the **negative** side (collect when shorts pay) — needs a spot
  short or margin borrow leg; more moving parts than the yield justifies.
- OKX changing the formula again.

## Next research candidates (see conversation 2026-10-04)

1. Liquidation-cascade mean reversion — needs months of `perp_market_snapshots`;
   turn the collector on as a long-running service and wait.
2. Cross-sectional momentum over top-N alts with a BTC regime filter — can be
   backtested today from daily candles; closest to "public price data", so it
   must beat buy-and-hold on risk-adjusted terms by a wide margin to count.
