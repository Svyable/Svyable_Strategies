# Svyable Strategies — From Quantiacs Research Harness to Multi-Vendor Execution Platform

Status: Draft v1
Scope: Architecture + migration plan for evolving the Q23 quantitative factor/strategy harness from a Quantiacs-coupled backtesting tool into a vendor-agnostic research + live execution platform.

---

## 0. Executive Summary

The Q23 system (`Q23_QUANT_SYSTEM_2`) is a mature **research harness**: a factor library, IC-weighted portfolio constructor, and transaction-cost model, all built on top of Quantiacs' `qnt.data` API for survivorship-bias-free daily bars, with Marketstack layered in to patch the most recent days. It produces CSV artifacts consumed by a Streamlit dashboard for human PM review. It has **no execution layer** — nothing in the codebase talks to a broker, manages an order, or reconciles a live position.

The ask: generalize this so (a) data sourcing isn't hard-coded to Quantiacs/Marketstack and can pull fundamentals from **Daloopa** and alternative data from **Quiver Quant**, and (b) the harness can hand its target weights to a real broker — **tastytrade**, **Schwab**, or others — instead of stopping at a CSV file.

The right shape for this is a **ports-and-adapters (hexagonal) architecture**: define two small, stable internal contracts — `DataProvider` and `BrokerConnector` — and push every vendor-specific quirk (auth flows, rate limits, schema differences) behind adapters that implement them. The factor/portfolio math in `engine.py` doesn't need to know or care whether prices came from Quantiacs or Polygon, or whether an order went to tastytrade or Schwab.

This doc is in two parts: **Part A** is a grounded map of what exists today (so we're not guessing at the starting point), **Part B** is the target connector architecture and a phased migration plan to get there.

---

## Part A — Current Tech Stack Structure Analysis

### A.1 High-level shape

```
qnt.data (Quantiacs)  ─┐
                        ├─► MarketDataBundle ─► FactorLibrary ─► DynamicICWeighting ─► PortfolioConstructor ─► OutputWriter ─► CSVs ─► Streamlit dashboard (human PM)
Marketstack (gap-fill) ─┘         (StrategyEngine orchestrates all of this)

Postgres (psycopg2)  ─── separate ingestion track for crypto / blockchain / NDX data (scripts/ingest_*.py) — not yet wired into the strategy engine's data path
```

Everything downstream of data loading is `xarray`/`pandas`-native, batch-oriented, and designed for **end-of-day rebalancing**, not streaming or intraday decisions.

### A.2 Data layer

- **Primary source: Quantiacs (`qnt.data` / `qndata`)** — `src/q23/strategy/data_loader.py` calls `qndata.stocks.load_ndx_data` / `load_spx_data` for OHLCV + `is_liquid`/`is_stock`/`is_ndx` flags, using `load_ndx_list()` / `load_spx_list()` for point-in-time, delisting-aware universes (the whole reason Quantiacs was chosen — it avoids survivorship bias for free). The loader wraps this in a `_try_call` shim that survives minor `qnt` signature drift across versions, and normalizes everything into an internal `MarketDataBundle` dataclass (`data`, `returns`, `asset_ids`, `pin_idx`, `meta`).
- **Gap-fill source: Marketstack** — `marketstack_client.py` is a thin REST client (`requests` + rate-limit delay + telemetry via `marketstack_telemetry.py`) used only to backfill the most recent days that Quantiacs hasn't published yet. `data_gap_detector.py` decides *whether* to call it (`should_fetch_marketstack`, `get_latest_quantiacs_date`), and `data_merger.py` converts Marketstack's response shape into `xr.Dataset` and merges it with the Quantiacs dataset (`marketstack_to_xarray`, `merge_datasets`).
- **Identity bridge:** `symbol_mapper.py` + `id-translation.csv` translate between Quantiacs' `server_id` format (e.g. `NAS:AAPL`) and plain ticker symbols, because every non-Quantiacs vendor (Marketstack today, brokers tomorrow) speaks tickers, not Quantiacs IDs.
- **Caching:** `data_cache.py` provides local on-disk caching with TTL validation (`is_cache_valid`, `cleanup_old_cache`) to avoid re-hitting `qnt.data` every run.
- **A second, disconnected data track:** `src/q23/database/` is a full Postgres layer (`client.py` with `psycopg2` connection pooling, `schema.py`, `crypto_schema.py`, `ingestion.py`, `crypto_ingestion.py`, `blockchain_ingestion.py`, `smart_ingestion.py`) fed by standalone scripts in `scripts/` (`ingest_ndx.py`, `ingest_crypto.py`, `ingest_blockchain.py`). This exists for crypto/blockchain-metric use cases and is **not** consumed by `StrategyEngine` today — it's a parallel ingestion pipeline, not part of the factor pipeline.

**Coupling observation:** `qnt.data` is imported directly inside `data_loader.py` rather than behind an interface — the `MarketDataBundle` dataclass is a decent abstraction boundary for *consumers* (factors only ever see the bundle), but nothing stops a *second* vendor from requiring its own bespoke loader function the way Marketstack did. There's no `DataProvider` protocol; each new source has so far meant writing a new client + a new merge function.

### A.3 Strategy / factor layer

- `StrategyBase` (`strategies/base.py`) is a clean ABC: `strategy_id()`, `config` (a `StrategyConfig` dataclass covering universe, position sizing, vol targeting, leverage caps, TC bps), `run(...)` returning a `StrategyArtifacts` bundle (weights, budget, factor weights, IC, composite score, factor matrix `F`, metadata).
- `StrategyRegistry` (`strategies/registry.py`) auto-discovers and registers strategies via explicit `try/import` blocks (not entry-points or dynamic scanning) — currently ~12 concrete strategies: GLFT v1/v2/v3 (microstructure), Neural Alpha v1/v2 (behavioral factors), Composer v1/v2 (ensembles), Hybrid Alpha, OU (mean reversion), GPT52v4, NASNYS v4, and benchmark strategies.
- `FactorLibrary` (`strategy/factors.py`) implements 40+ factors (`V4_24_FACTORS` etc.), all pure functions over the `xr.Dataset`/`DataArray` from `MarketDataBundle` — meaning **every factor today is derivable only from price/volume/liquidity fields**. There is no fundamentals or alt-data input anywhere in the factor graph.
- `DynamicICWeighting` (`ic_weighting.py`) computes rolling information-coefficient-based factor weights; `PortfolioConstructor` (`portfolio.py`) turns the composite score into long/short seat allocations with budget/vol-targeting rules from `StrategyConfig`.

### A.4 Cost model & risk

- `TransactionCostModel` (`transaction_costs.py`) defaults to the **Quantiacs contest formula** (`TC = atr_multiplier × ATR(14) × |Δposition|`), with `FLAT_BPS`, `PERCENTAGE`, `TIERED`, and `CUSTOM` schemes also supported via `TransactionCostScheme`. This is a *simulated* cost, applied post-hoc to backtest diagnostics (`_compute_portfolio_diag` in `engine.py`) — it has no relationship to what a real broker would actually charge or how it would actually fill an order.
- There is no pre-trade risk check, no live drawdown circuit breaker, no position-limit enforcement against an actual account — all risk logic operates on the backtest weight matrix, after the fact.

### A.5 Output & presentation layer

- `OutputWriter` (`strategy/outputs.py`) is deliberately I/O-only (its own docstring: "no qnt, no streamlit") and writes deterministic, atomically-written CSVs: wide weights, factor exposures, factor vectors, portfolio diagnostics — keyed by `{BASE_NAME}_{tag}`.
- The Streamlit dashboard (`dashboard/app.py` + ~15 `_pages/*.py` modules: overview, rebalance, blotter, bias, risk analytics, live strategy lab, stock analysis, calendar heatmap, position stack, etc.) reads those CSVs and renders them for a **human** to review and act on manually. "Blotter" and "Live Strategy" pages notwithstanding, nothing in the dashboard submits an order — it's a decision-support surface, not an OMS.

### A.6 What's structurally missing for live execution

1. **No `DataProvider` abstraction** — vendors are added by writing bespoke client+merge code each time (this is exactly what happened for Marketstack).
2. **No execution/broker layer at all** — no `Order`, `Fill`, `Position`, or `Account` model; no OAuth session management; no order lifecycle.
3. **No secrets/token infrastructure beyond flat `.env` vars** — fine for a static API key (Marketstack), completely inadequate for OAuth2 flows with 30-minute access tokens and 7-day refresh tokens (Schwab) or client-credential refresh-token flows (tastytrade).
4. **No reconciliation** — nothing compares "what the engine says the portfolio should be" against "what a broker says the account actually holds."
5. **Batch/EOD assumption baked in throughout** — `xarray` time-indexed daily bars, `.diff()`-based turnover, ATR-based TC — all of this assumes rebalancing happens once a day, not intraday.

---

## Part B — Future Connector Landscape Analysis

### B.1 Design principle

Introduce two narrow, stable protocols at the seams that currently leak vendor detail, and make every vendor — existing or new — an adapter behind them. Nothing in `engine.py`, `factors.py`, or `portfolio.py` should change; only `data_loader.py`'s internals and a new `execution/` package should.

```python
# q23/data/provider.py  (new)
class DataProvider(Protocol):
    def get_universe(self, as_of: date) -> list[str]: ...
    def get_prices(self, symbols: list[str], start: date, end: date) -> xr.Dataset: ...
    def get_fundamentals(self, symbols: list[str], as_of: date) -> pd.DataFrame: ...   # new capability
    def get_alt_signals(self, symbols: list[str], start: date, end: date) -> pd.DataFrame: ...  # new capability

# q23/execution/broker.py  (new)
class BrokerConnector(Protocol):
    def get_account(self) -> Account: ...
    def get_positions(self) -> list[Position]: ...
    def submit_order(self, order: Order) -> OrderAck: ...
    def cancel_order(self, order_id: str) -> None: ...
    def stream_fills(self) -> Iterator[Fill]: ...
```

`MarketDataBundle` stays as the internal normalized shape; `DataProvider` adapters are just responsible for producing it (or the fundamentals/alt-data equivalents) regardless of vendor.

### B.2 Data connector landscape

| Provider | Role | Auth model | Integration notes |
|---|---|---|---|
| **Quantiacs** (`qnt.data`) | Point-in-time price/volume universe, survivorship-bias-free — keep for backtesting even after live trading exists | Library-embedded, no key management | Wrap as `QuantiacsProvider(DataProvider)`; this is nearly a pure refactor of existing `data_loader.py` logic behind the new interface. |
| **Marketstack** | Recent-day EOD gap-fill | Static API key | Wrap existing `MarketstackClient` as `MarketstackProvider`; logic in `data_gap_detector.py`/`data_merger.py` becomes the reference implementation for how any two `DataProvider`s get merged. |
| **Daloopa** | Fundamentals (income statement, balance sheet, cash flow — 1,300+ standardized metrics sourced from SEC filings, investor decks, and transcripts, >99% accuracy, point-in-time) — unlocks an entire class of value/quality factors the current price-only factor library can't build | Base64(email:api_key) in `Authorization` header ([docs.daloopa.com](https://docs.daloopa.com/docs/api-authentication)); also exposes an MCP server for LLM-native querying ([docs.daloopa.com](https://docs.daloopa.com/docs/daloopa-mcp)) | New `DaloopaProvider.get_fundamentals()`. Because Daloopa is filing-driven, fundamentals arrive on an irregular, per-ticker cadence (quarterly + revisions) — this needs a point-in-time join against the daily price panel (as-of merge on filing date, not calendar date, to avoid look-ahead bias). |
| **Quiver Quant** | Alternative/informational data — congressional trading, insider trading, lobbying, government contracts, hedge fund 13F moves, WSB/Reddit sentiment | Bearer token; REST, versioned `/beta` and `/v1` paths, e.g. `/beta/live/congresstrading`, `/beta/historical/congresstrading/{ticker}` ([api.quiverquant.com/docs](https://api.quiverquant.com/docs/)); official Python package with a `congress_trading()` helper ([github.com/Quiver-Quantitative/python-api](https://github.com/Quiver-Quantitative/python-api)) | New `QuiverProvider.get_alt_signals()`. This is genuinely new *factor* territory (nothing in `FactorLibrary` today ingests anything but price/volume) — treat each Quiver dataset as its own factor family, gated behind an IC-weighting evaluation before it's trusted in a live composite score. Check redistribution/compliance terms before use in anything client-facing. |

Net effect: the harness goes from "one price feed, patched by a second price feed" to "a price feed + a fundamentals feed + an alt-data feed," each independently swappable. Nothing here requires giving up Quantiacs — it's additive.

### B.3 Broker / execution connector landscape

| Broker | Asset classes | Auth model | Integration notes |
|---|---|---|---|
| **tastytrade** | Equities, options (strong options chain/greeks support) | OAuth2 — official `tastytrade-sdk-python` supports client ID/secret + refresh token ([developer.tastytrade.com/oauth](https://developer.tastytrade.com/oauth/)); community `tastyware/tastytrade` SDK is a fuller async alternative | Good fit if strategies want an options overlay (the existing GLFT/microstructure strategies are equities-only today, but the factor framework doesn't preclude options-based expressions). |
| **Charles Schwab** (Trader API, successor to TD Ameritrade's API) | Equities, options | OAuth2 — access tokens expire in **30 minutes**, refresh tokens in **7 days** ([schwab-py docs](https://schwab-py.readthedocs.io/en/latest/auth.html); [developer.schwab.com](https://developer.schwab.com/)); app registration requires manual approval (1–3 business days) | The 7-day refresh-token wall is an operational constraint, not just a code detail — needs a scheduled re-auth reminder/job, or the connection goes stale on a weekend. App approval lead time means this should be started early in the migration, independent of code readiness. |
| **Interactive Brokers** (optional, broader landscape) | Equities, options, futures, global markets | TWS/Gateway session or Client Portal Web API (OAuth-like) | Worth keeping on the radar given the multi-asset ambitions of the factor library (GLFT/microstructure factors are naturally suited to more liquid/derivatives markets IBKR covers well); heavier operational footprint (gateway process to keep alive). |
| **Alpaca** (optional) | US equities/crypto | API key + secret (simplest of the group) | Useful as a **low-friction paper-trading / CI adapter** — cheapest way to get an end-to-end "engine → order → fill" integration test working before dealing with tastytrade/Schwab's OAuth complexity. |

**Unified execution model**, independent of which broker(s) are live:

```
Order(symbol, side, qty, order_type, tif, strategy_tag)
Fill(order_id, symbol, qty, price, ts)
Position(symbol, qty, avg_price, market_value)
Account(id, buying_power, equity, positions: list[Position])
```

Each `BrokerConnector` adapter translates this into its own wire format. The existing `OutputWriter` weight CSVs become the *input* to a new `execution/rebalancer.py` that diffs target weights against `BrokerConnector.get_positions()` and emits an `Order` list — this is the one genuinely new piece of business logic in the whole migration, everything else is plumbing.

### B.4 Secrets & token management

Flat `.env` values (today's `MARKETSTACK_API_KEY`, `API_KEY`) don't survive contact with OAuth2 refresh cycles. Given the project already has a Postgres layer (`src/q23/database/client.py`), the pragmatic move is an encrypted `oauth_tokens` table (provider, access_token, refresh_token, expires_at) with a small `TokenStore` service that adapters call through — not a new piece of infrastructure, just a new table and a thin wrapper. A background job (cron or APScheduler) refreshes tokens before expiry (well before Schwab's 30-minute window, comfortably before its 7-day wall).

### B.5 Migration phases

1. **Phase 0 — Interface extraction (no new vendors).** Refactor `data_loader.py` so `QuantiacsProvider` and `MarketstackProvider` both implement `DataProvider`; behavior-preserving. This is the prerequisite for everything else and should be verifiable by diffing backtest outputs before/after (byte-identical CSVs).
2. **Phase 1 — Fundamentals.** Add `DaloopaProvider`; extend `FactorLibrary` with 2–3 fundamentals-driven factors (e.g., a value composite); validate via the existing IC-weighting pipeline before promoting into any live composite score.
3. **Phase 2 — Alt-data.** Add `QuiverProvider`; same IC-gated validation pattern as Phase 1 for e.g. a congressional-trading-following factor.
4. **Phase 3 — Paper execution.** Build `BrokerConnector` + `Order`/`Fill`/`Position`/`Account` models; stand up an Alpaca (or broker sandbox) adapter first as the cheapest path to an end-to-end paper-trade integration test; build `execution/rebalancer.py` (target weights → orders) and a reconciliation view added to the dashboard.
5. **Phase 4 — Live pilot.** Add the `TastytradeConnector` and/or `SchwabConnector` (start Schwab app approval early — it's the long pole). Pilot with one strategy, small capital, a hard kill-switch tied to live drawdown, and daily reconciliation between engine weights and actual account state.
6. **Phase 5 — Multi-broker & hardening.** Token-refresh automation, rate-limit/backoff handling per vendor, data-provider failover (e.g., Marketstack down → skip gap-fill gracefully, already partially true today), audit logging of every submitted order, and — if there's appetite — smart order routing across brokers.

Each phase is independently shippable and testable; nothing in Phase 1–2 touches execution, and nothing in Phase 3+ requires the fundamentals/alt-data work to be done first — they can run in parallel if there are two engineering tracks.

---

## Appendix — Concrete touch points in the existing codebase

- `src/q23/strategy/data_loader.py` → split into `q23/data/providers/{quantiacs,marketstack,daloopa,quiver}.py` behind `q23/data/provider.py`'s `DataProvider` protocol.
- `src/q23/strategy/symbol_mapper.py` → generalizes from "Quantiacs↔Marketstack" to the canonical ticker-identity layer every provider and every broker adapter maps through.
- `src/q23/strategy/factors.py` → new factor functions consuming `get_fundamentals()`/`get_alt_signals()` outputs, evaluated through the existing `DynamicICWeighting` before promotion.
- `src/q23/strategy/outputs.py` → unchanged; its weight CSVs become `execution/rebalancer.py`'s input.
- `src/q23/database/client.py` → reused (not replaced) as the home for the new `oauth_tokens` table and any live-fill/position history.
- New package: `src/q23/execution/` — `broker.py` (protocol + models), `rebalancer.py`, `adapters/{alpaca,tastytrade,schwab,ibkr}.py`.
- Dashboard: extend `_pages/_blotter.py` (already exists, currently backtest-only) into the reconciliation view for Phase 3+.
