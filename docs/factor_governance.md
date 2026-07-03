# Factor governance and IC standard

## Scope

The active stack is designed to be state of the art within a daily OHLCV, market-proxy, and point-in-time liquidity data contract. It is not yet a complete modern equity-characteristics stack. Point-in-time fundamentals, analyst revisions, options, short-interest/borrow, news, and true intraday trades and quotes remain separate data gates.

The runtime `factor_catalog.csv` is the source of truth for what is implemented.

## Maturity

Each factor is either:

- `proven`: established lineage and eligible for the configured minimum floor after IC breadth and coverage gates;
- `shadow`: research or proxy implementation with no guaranteed allocation.

Daily-bar approximations of OFI, VPIN, Kyle lambda, BVC, and related order-book quantities are shadow factors. They are hypotheses, not substitutes for intraday microstructure data.

## Production IC rules

1. Preserve missing observations through IC estimation.
2. Compute Spearman IC only on pairwise-valid, point-in-time tradable assets.
3. Require minimum cross-sectional breadth.
4. Purge IC by `forward_horizon + 1` days before it affects weights.
5. Estimate causal EWMA IC mean and IC volatility.
6. Adjust trust with positive ICIR, trailing hit rate, and eligible-universe coverage.
7. Block factors below the minimum coverage threshold.
8. Penalize redundancy using pairwise-valid cross-sectional correlations.
9. Apply floors only to active proven factors; shadow factors have zero floors.
10. Persist mean IC, IC volatility, ICIR, hit rate, observations, coverage, maturity, lineage, and live weight.

## Research promotion rules

The `svyable factors` report uses the same catalog and tradability rules as production. A promotion candidate requires adequate breadth and history, positive ICIR, stable IC sign across sample halves, an overlap-aware Newey-West t-statistic of at least 3, and a Benjamini-Hochberg q-value no greater than 10% across the tested library.

Promotion remains a human PM decision. Walk-forward performance, costs, capacity, correlation to the existing book, and economic rationale must also pass.

## ML sleeve

The default model is purged walk-forward histogram gradient boosting with cross-sectional forward-return rank targets, deterministic time-decay weights, bounded training size, and a ridge fallback. The ML sleeve is shadow and must earn capital through the same sleeve-level purged IC process.

## Richer-data roadmap

Priority expansions are point-in-time profitability/investment/value/issuance, analyst revisions and earnings surprises, option-implied volatility/skew/term structure, borrow and short-interest signals, true intraday order-flow and spread measures, and timestamped news/filing attention signals.
