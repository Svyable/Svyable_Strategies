# Tastytrade Sandbox (cert) Runbook

Status: v1.0 (2026-07-02). Companion to production.md (gates) and CLAUDE_LOOP.md (daily loop).

## What the sandbox is — and is not

The cert environment (`api.cert.tastyworks.com`, streamer at
`streamer.cert.tastyworks.com`) never routes to a real market. Its fill engine
is a fixed rule set, not a matching engine:

| Order | Cert behavior |
|---|---|
| Market | always fills at **$1.00** |
| Limit, price < $3 | fills immediately |
| Limit, price > $3 | stays `Live`, never fills |

Consequences, stated plainly:

- **Zero economic signal.** Cert fill prices are simulator artifacts. They must
  never feed the slippage stats, the `tc_bps` cost model, or any performance
  claim. The engine enforces this: sandbox fills are tagged
  `synthetic_fills=true` in execution-quality records and are logged as
  info-level audit events, never warning/critical escalations
  (`execution_control.py`, `execution_backfill.py`, covered by
  `tests/test_execution_backfill.py`).
- **A deterministic order-lifecycle simulator.** The fixed rules are actually
  useful: they make every branch of the execution state machine reachable on
  demand, which a real paper venue cannot guarantee.

| To exercise | Submit |
|---|---|
| immediate-fill path (submit → fill capture → reconcile → ledger) | market order, or limit priced < $3 |
| working-order path (poll → cancel → replace) | limit priced > $3 (guaranteed to stay Live) |
| rejection path | order that fails buying power / preflight |

So the sandbox proves **plumbing repeatability** — OAuth refresh, order
normalization, dry-run preflight, submission, polling, cancellation, fill
capture, transaction dedupe, reconciliation, audit chain. The **economics**
record comes from the daily loop's shadow NAV (canonical weights marked on
real closes), which needs no broker at all. Both records together are the
Gate-B evidence; neither substitutes for the other.

## Known cert limitations

- No net-liquidating-value history, no market metrics, no real-time market
  data (streaming quotes are delayed). Position marks in cert may be stale —
  the rebalancer's `execution_prices` (mid > last > close) already falls back
  through the chain.
- Instrument list sometimes lags production: valid symbols can 422. If a
  universe name 422s in cert, it is a **sandbox artifact, not a data bug** —
  note it in the ledger and email api.support@tastytrade.com. Do not "fix"
  the universe for it.
- Sandbox accounts are not funded like production; check equity/buying power
  via the sandbox check before assuming order sizes.

## Credentials — the only missing piece

From the sandbox portal (developer.tastytrade.com, logged in with the sandbox
user):

1. Create (or open) your **OAuth2 application** → copy the **client secret**
   (shown once; regenerate if lost).
2. Generate a **refresh token** with read + trade scopes.
3. Note the **sandbox account number** (from the sandbox customer's accounts).

Then:

```bash
cd engine
cp .env.example .env   # if not already present
# populate: TASTY_CLIENT_SECRET, TASTY_REFRESH_TOKEN, TASTY_ACCOUNT_NUMBER
# keep:     TASTY_IS_TEST=true, SVYABLE_ENV=sandbox, SVYABLE_ENABLE_LIVE=false
```

`.env` is never committed. Production requires `TASTY_IS_TEST=false` **and**
`SVYABLE_ENABLE_LIVE=true` **and** typed account-number confirmation — three
independent latches.

## First-light sequence (run in order, each gate green before the next)

```bash
cd engine && source .venv/bin/activate

# 1. read-only + dry-run integration check (never submits)
python -m svyable.sandbox_check

# 2. start PIT universe snapshot accumulation (irreplaceable calendar data —
#    every day this doesn't run is point-in-time history lost)
python -m svyable.cli universe

# 3. daily loop end-to-end against the sandbox account's actual positions
python -m svyable.strategy_daily --start 2020-01-01

# 4. human-triggered rebalance preflight + submission from the Streamlit
#    Rebalance page (production bulk submission stays disabled)
python -m svyable.ui
```

`sandbox_check` refuses production credentials by construction
(`TASTY_IS_TEST=true` required).

## What a clean sandbox day proves

1. Auth refresh survived the session.
2. The candidate board → decision → activation → canonical weights chain ran.
3. Orders were normalized, preflighted, submitted, polled, and captured.
4. Duplicate batches/transactions were blocked on re-run.
5. Reconciliation matched intended vs actual, with drift recorded.
6. Every step left ledger + audit rows.

That, repeated across strategy switches and holds, is the "sustained sandbox
operating record" the production gates require.
