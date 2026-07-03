# Production Readiness — Operational Chassis Spec & Gates

Status: v1.0 (2026-07-02). Companion to strategy.md (alpha), plan.md (connectors), roadmap.md (phases).
This doc defines what "operationally trustworthy" means, what is built, and the gates to live capital.

## The four pillars and their implementations

### 1. Accuracy (the data is right)
| Control | Implementation | Status |
|---|---|---|
| Restatement detection | `providers.detect_restatement` — overlapping history compared on every refresh; >0.2% diff ⇒ full refetch + ledger warning | **BUILT — caught a real CRWD restatement on first run** |
| Primary data source | **tastytrade DXLink** (`dxlink.py` + `TastytradeProvider`): daily candles over websocket (`SYM{=1d}` + fromTime), 24h api-quote-token cached, COMPACT format, chunked subscriptions with keepalive; broker and data share one vendor/auth — zero symbol-mapping drift | BUILT (needs full tastytrade customer account for quote tokens) |
| Secondary source / cross-check | yfinance retained as independent cross-check + fallback feed | BUILT |
| Spot quotes (no websocket) | `TastytradeBroker.get_market_snapshot` via `/market-data/by-type` (batched); `execution_prices` (mid > last > close) feeds the rebalancer live prices | BUILT + tested |
| Trading calendar | `calendar.py` — US holidays incl. Good Friday/Juneteenth, observance shifts; daily run skips holidays and staleness-checks against the expected last close | BUILT + tested |
| PIT universe | `universe.py` — **snapshot accumulation**: daily persisted snapshots of tastytrade `/instruments/equities/active` (XNAS, ETFs/options-only filtered) → membership grows point-in-time from day one; `svyable universe`. Honest caveat: deep-history PIT unavailable from tastytrade — coverage starts when snapshots start; buy a historical membership dataset later if pre-2026 citable backtests are required | BUILT (rewired from the removed Polygon/Massive path) |
| Cross-provider price check | compare yf closes vs tastytrade snapshot, alert > 25bps divergence | TODO (~30 lines, both sources now live) |

### 2. Consistency (same inputs ⇒ same book, provably)
| Control | Implementation | Status |
|---|---|---|
| Golden weights test | `tests/test_regression.py` — SHA-256 of full weight matrix on frozen synthetic panel; any behavior change fails CI until deliberately re-blessed | BUILT + blessed |
| Causality test | truncate the panel at T, re-run, assert weights ≤ T identical to 1e-9 — mechanical look-ahead detector for the whole pipeline | BUILT, passing |
| Dependency lockfile | `engine/requirements.lock` (uv freeze) | BUILT |
| Config provenance | config hash in every artifact/ledger row | BUILT (add git SHA later) |
| Shadow-vs-live tracking | ledger `equity` table: shadow NAV (from daily run) vs paper equity (from rebalance) ⇒ daily drift bps; §12.5 ±30bps check computed by `health` | BUILT — populates as the paper loop runs |

### 3. Observability (knowing what happened, from anywhere)
| Control | Implementation | Status |
|---|---|---|
| Run ledger | `ledger.py` SQLite: runs, orders, equity, events — every CLI command records | BUILT |
| Health endpoint | `svyable health` — one JSON for the Claude loop: last run, drift stats, warnings | BUILT |
| External dead-man switch | `run_daily.sh` pings `$SVYABLE_HEALTHCHECK_URL` (healthchecks.io) on success/fail; missing ping ⇒ *they* email — covers "laptop was asleep" | BUILT (set the env var) |
| Morning report | per-run markdown + LATEST.md pointer | BUILT (earlier phase) |
| HTML dashboard from ledger | equity curves, drift, IC health over time | TODO |

### 4. Execution robustness
| Control | Implementation | Status |
|---|---|---|
| Order audit chain | rebalancer logs every plan+result to JSON and ledger | BUILT |
| Pre-trade checks | long-only guard, lev_cap check, ADV participation caps, dust filter | BUILT |
| Reconciliation | post-fill drift report, warnings into ledger | BUILT |
| Order lifecycle | fill polling, partial fills, retries, MOC/limit types | PARTIAL — tastytrade adapter has per-order fill polling, limit orders, cancel/replace |
| Pre-trade broker validation | tastytrade dry-run endpoint: every order validated (buying power + fees) before submission; warnings ⇒ not submitted | **BUILT** (`tastytrade.py`, dry-run gated by construction) |
| tastytrade adapter | OAuth2 (15-min tokens, auto-refresh) + sandbox session auth; sandbox default, production requires TT_ENV=production AND code-level `allow_production=True`; CLI: `svyable tasty status\|orders\|cancel\|dry-run`, `rebalance --broker tasty` | BUILT + offline-tested (mock transport) |
| Account-based kill switch | live rule on actual account equity, not backtest curve | TODO (with lifecycle work) |

## Gates to capital (hard, pre-committed)

- **Gate A — paper autopilot on**: golden+causality suites green; Massive key live; cross-provider check running; tastytrade sandbox session live. Then the daily loop auto-submits to tastytrade sandbox.
- **Gate B — 60 clean paper days**: ≥90% of days |drift| ≤ 30bps; zero unexplained reconcile drifts; heartbeat uptime ≥ 98%; PIT-universe backtest re-run and walkforward still ROBUST.
- **Gate C — first live dollars**: order-lifecycle + account kill switch built and fire-drilled; measured tastytrade fill costs fed back into `tc_bps`; human sign-off on the Gate-B report.

## Broker lineup

| Broker | Role | Auth (env vars) | State |
|---|---|---|---|
| LocalPaperBroker | offline testing, CI | none | live |
| tastytrade (sandbox) | canonical data + broker provider; dry-run-validated execution; the richest pre-trade checks | OAuth: `TT_CLIENT_ID`/`TT_CLIENT_SECRET`/`TT_REFRESH_TOKEN`; or sandbox `TT_USERNAME`/`TT_PASSWORD`; optional `TT_ACCOUNT` | built, needs sandbox account |
| tastytrade (production) | live capital at Gate C | same + `TT_ENV=production` + code-level opt-in | gated |

## Next-session queue (in order) — tastytrade-primary
1. Create tastytrade sandbox login + open a real tastytrade customer account (the latter is required for DXLink quote tokens) → `svyable tasty status` → `svyable universe` (starts PIT snapshot accumulation) → `svyable --provider tasty fetch` (first DXLink candle cache).
2. `rebalance --broker tasty --execute` against sandbox with live snapshot prices; compare dry-run fee estimates vs modeled `tc_bps`.
3. Cross-provider last-close check (yf vs tastytrade snapshot) in `cmd_daily`; wire universe snapshot into the daily loop.
4. Account streamer websocket (order-status push instead of per-id polling) + account-equity kill switch.
5. HTML dashboard generated from the ledger.
6. Gate A: tastytrade sandbox is the paper-autopilot default (one vendor for data + broker); LocalPaperBroker remains the offline/CI adapter.
