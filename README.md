# Svyable_Strategies

Vendor-agnostic quantitative strategy operation, distilled from the Q23 research harness (`~/Q23_QUANT_SYSTEM 2`). Goal: run a systematic book on a daily loop against any data provider and any broker.

## Documents

- **[strategy.md](strategy.md)** — the alpha specification. What to compute: factor library (~70 factors across defensive / momentum / OU mean-reversion / microstructure / behavioral families), the IC meta-learning weighting scheme, the four-sleeve ensemble with stress prior, portfolio construction, the risk stack, PM tooling requirements, fixes over the Q23 implementations, the **contest-constraint unlock analysis (§11)**, and the **`svyable_nasdaq_lo` long-only NASDAQ flagship spec (§12)**.
- **[plan.md](plan.md)** — the platform architecture. How to plug it in: `DataProvider` / `BrokerConnector` protocols, vendor landscape (Quantiacs, Marketstack, Daloopa, Quiver; Alpaca, tastytrade, Schwab, IBKR), secrets/token management, and the phased migration from research harness to live execution.
- **[roadmap.md](roadmap.md)** — the operation. Five phases from generic `svyable-engine` package → paper loop → live pilot with a staged unlock schedule → scale/second book → company formation, plus the standing research agenda and operating principles.
- **[engine/](engine/README.md)** — the working codebase (Phase 1, built). Panel → factor registry → purged IC meta-learner → sleeve ensemble (+ ML sleeve) → construction → risk stack → morning report. Verified end-to-end on real NASDAQ data; full 6.5y backtest ≈ 5 seconds.
- **[ops/](ops/CLAUDE_LOOP.md)** — the daily loop: launchd job at 07:30 ET produces weights + `engine/outputs/svyable_nasdaq_lo/LATEST.md` before the 08:30 deadline; a scheduled Claude session reviews, escalates, and journals. Deterministic code computes; Claude supervises.
- **[production.md](production.md)** — the operational chassis: accuracy (restatement detection, trading calendar, Massive/Polygon provider, PIT universe), consistency (golden-weights + causality regression tests, lockfile), observability (SQLite run ledger, `svyable health`, external dead-man heartbeat, shadow-vs-live drift), and the three hard gates to live capital.

Reference proof point: q23_neural_alpha, 2025 under full contest constraints — 63.58% annual, Sharpe 3.545, MaxDD −5.67%, 58.02% net of contest-model costs.

## Operating model (one line)

```
Panel(OHLCV) → factors → IC-weighted sleeves → composite score → seats/tilt/projection → vol-target budget × dd throttle × overlay → target weights → rebalancer diff → broker orders → reconcile
```

Steps through target weights exist in Q23 today; the rebalancer and broker adapters are the build (plan.md Phases 0–5).

## Next actions

1. Phase 0 (plan.md): extract `DataProvider` interface from Q23's `data_loader.py` — behavior-preserving, verified by byte-identical backtest CSVs.
2. Stand up `svyable_core` per strategy.md §5 with the §8 fixes (causal recency boost, purged IC shift, flat factor registry).
3. Alpaca paper-trading adapter + rebalancer for the first end-to-end loop.
