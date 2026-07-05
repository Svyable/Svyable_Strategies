# Svyable Downside Resilience research note

This note documents the Downside Resilience factor family and strategy mandate. It is research infrastructure, not a live-capital performance claim.

## Gap identified

The newer alpha books already cover fast tape acceleration, residual catalysts, and durable leadership. The remaining gap was a defensive alpha candidate for difficult regimes: names that retain residual strength when the broad market is weak, avoid severe downside capture, reclaim quickly after broad selloffs, and keep liquidity support during stress.

## New factors

| Factor | Sleeve | Idea |
| --- | --- | --- |
| `down_market_residual_strength` | resilience | Residual strength measured specifically on broad-market down days. |
| `downside_capture_inverse` | resilience | Low or positive capture on negative market-return days. |
| `panic_reclaim_strength` | resilience | Fast recovery after broad market selloffs with strong close location. |
| `drawdown_floor_stability` | resilience | Shallow and stable medium-term drawdowns. |
| `liquidity_safety_momentum` | liquidity | Dollar-volume support that remains present during market weakness. |
| `volatility_cooldown_momentum` | momentum | Positive drift as realized range cools down from a stress spike. |

## Strategy mandate

`svyable_downside_resilience` combines the six Downside Resilience factors with existing resilience, defensive, residual-alpha, institutional-trend, Alpha Catalyst, and Leadership Quality controls.

The mandate is intentionally defensive:

- no ML sleeve;
- blended seat weighting;
- 16 base seats, 12 minimum, 22 maximum;
- 7.5% max position;
- 24% cluster cap;
- 4.5% no-trade band;
- 12% target volatility;
- 7% stressed target volatility;
- 4 bps cost assumption;
- 5-day minimum hold.

## Why this fills a useful gap

Alpha Catalyst and Tape Acceleration are designed to find upside pressure. Leadership Quality is a steadier participation book. Downside Resilience is built for a different board role: when turbulence or weak breadth makes the best offensive candidates unattractive, the selector can still compare a lower-volatility residual-alpha candidate that emphasizes drawdown behavior and stress liquidity.

## Promotion path

1. Run as a normal candidate and compare against offensive alpha books during turbulent or weak-market periods.
2. Monitor turnover, drawdown behavior, factor-health coverage, and redundancy against existing resilience factors.
3. Keep the new factors in shadow/incubation until they earn evidence through purged IC and candidate-board behavior.
