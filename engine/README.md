# svyable-engine

The generic daily alpha harness specified in [../strategy.md](../strategy.md).
Zero Quantiacs dependencies; runs on a MacBook (full 6.5y × 128-asset pipeline ≈ 5s).

## Layout

```
svyable/
  panel.py       canonical Panel(time x asset OHLCV) + validation + cs helpers
  config.py      SvyableConfig — strategies are configs, never code forks
  factors.py     flat registry, ~30 factors across 4 sleeves (defensive/momentum/meanrev/micro)
  weighting.py   rank-IC meta-learner: purged (h+1) shift, causal recency boost,
                 correlation penalty, min-weight floor
  sleeves.py     sleeve ensemble + drawdown stress prior
  ml.py          optional 5th sleeve: walk-forward ridge on the factor matrix (GKX-style)
  construct.py   seats -> softmax tilt (or HRP) -> capped-simplex projection ->
                 smoothing -> no-trade band
  risk.py        vol-target budget x dd throttle x overlay + kill switch + cash yield
  metrics.py     perf summary + deflated Sharpe (Bailey/López de Prado)
  artifacts.py   evidence chain + morning report
  providers.py   DataProvider protocol; YFinanceProvider (parquet cache), SyntheticProvider
  pipeline.py    orchestration
  analysis.py    factor IC harness: per-factor IC/IR/hit-rate by horizon, quintile
                 spread, rank stability -> markdown tearsheet (the promotion gate)
  walkforward.py per-year OOS table + parameter fragility scan (ROBUST/FRAGILE verdict)
  brokers.py     BrokerConnector protocol; LocalPaperBroker (offline JSON), AlpacaBroker (paper REST)
  tastytrade.py  full tastytrade suite: OAuth2/session auth with auto-refresh, dry-run-gated
                 submission (warnings => never submitted), limit/market orders, search/cancel/
                 replace/poll, status snapshot; sandbox default, production double-gated
  calendar.py    US market holidays (incl. Good Friday), staleness expectations
  ledger.py      SQLite runs/orders/equity/events; shadow-vs-live drift; `svyable health`
  universe.py    point-in-time NASDAQ membership via Massive /v3/reference/tickers?date=
  rebalancer.py  weights -> integer-share orders: ADV participation caps, sells-first,
                 lev_cap pre-trade check, order audit log, reconciliation
  cli.py         fetch / daily / backtest / factors / walkforward / rebalance / smoke
```

## Setup

```bash
cd engine
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python numpy pandas pyarrow yfinance scikit-learn scipy
.venv/bin/python tests/test_smoke.py          # no-network sanity
.venv/bin/python -m svyable.cli fetch          # build the data cache
.venv/bin/python -m svyable.cli --start 2020-01-01 backtest --trials 20
.venv/bin/python -m svyable.cli --start 2020-01-01 daily   # today's weights + report

# research & validation
.venv/bin/python -m svyable.cli --start 2020-01-01 factors      # IC tearsheet
.venv/bin/python -m svyable.cli --start 2020-01-01 walkforward  # yearly OOS + fragility

# execution (paper). Alpaca: export ALPACA_KEY_ID / ALPACA_SECRET_KEY, --broker alpaca
.venv/bin/python -m svyable.cli --start 2020-01-01 rebalance                 # dry run
.venv/bin/python -m svyable.cli --start 2020-01-01 rebalance --execute      # local paper fills
```

## Validation snapshot (2026-07-01, real data, untuned defaults, biased seed universe)

- Walk-forward fragility scan: **ROBUST** — all 16 parameter perturbations positive
  (base Sharpe 1.01, worst 0.91), profitable 6 of 7 calendar years,
  **+32% active vs universe in 2022** (stress rotation working).
- Top factor: `kyle_lambda_inv` IR21 = 1.19 at 0.99 rank stability; reversal family
  negative on this trend-heavy sample (auto-de-weighted by the positive-only IC learner).
- Full loop verified: weights -> orders -> paper fills -> reconcile (0 drifts).

Daily automation + Claude review loop: see [../ops/CLAUDE_LOOP.md](../ops/CLAUDE_LOOP.md).

## Honesty ledger (read before quoting any number)

- The seed universe (`universe_nasdaq_seed.txt`) is a **current** list →
  backtests on it are survivorship-biased. Engineering validation only.
  PIT universe = roadmap research item #1.
- Defaults are **untuned**; the first real-data run scored deflated-Sharpe
  "INCONCLUSIVE" — which is the tool working, not failing. Parameters change
  only with a walk-forward report (strategy.md §8.5).
- yfinance is the at-home feed: fine for research cadence, no SLA. A commercial
  EOD provider is a ~40-line `DataProvider` subclass when it's time.
- The ML sleeve is fully causal (train window ends `horizon` days before any
  prediction) but shares the survivorship caveat above.
