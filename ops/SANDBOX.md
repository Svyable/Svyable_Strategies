# Tastytrade Sandbox (cert) Runbook

Status: go-live sandbox runbook refresh (2026-07-05). Companion docs: `production.md`, `ops/LAUNCH_READINESS.md`, and `ops/CLAUDE_LOOP.md`.

The sandbox is the validation venue for plumbing, controls, audit, and repeatability. It is **not** a source of economic performance evidence.

## What the sandbox is — and is not

The cert environment (`api.cert.tastyworks.com`, streamer at `streamer.cert.tastyworks.com`) does not route to the live market. Its fill engine is deterministic simulator behavior:

| Order | Cert behavior |
|---|---|
| Market | normally fills at a simulator price, historically observed as `$1.00` in this cert path |
| Limit, price < $3 | fills immediately |
| Limit, price > $3 | remains `Live` and can exercise polling/cancel/replace |

Operational consequences:

- **Zero economic signal.** Sandbox fill prices, slippage, and P/L must not feed alpha, cost-model, or performance claims.
- **Good lifecycle coverage.** The fixed rules are useful for proving order normalization, preflight, submission, polling, cancel/replace, fill capture, dedupe, reconciliation, and audit.
- **Separate economic record.** The daily loop's shadow NAV and canonical weights marked on real closes are the paper operating record; sandbox fills prove broker plumbing only.

## Credential contract

Canonical environment variables are `TASTY_*`. Legacy `TT_*` aliases are accepted by the code during migration, but ops should write only canonical names.

From the Tastytrade developer portal / sandbox account:

1. Create or open an OAuth application.
2. Set `TASTY_CLIENT_ID`.
3. Set `TASTY_CLIENT_SECRET`.
4. Ensure `TASTY_REDIRECT_URI` matches the app, default:
   `http://127.0.0.1:8182/callback`.
5. Generate a refresh token with the minimum scope needed:
   - `read` is enough for account/readiness checks;
   - `read trade` is required only for sandbox order submission workflows.
6. Set `TASTY_ACCOUNT_NUMBER`.

Recommended onboarding:

```bash
cd ~/Svyable_Strategies/engine
source .venv/bin/activate

cp .env.example .env
python -m svyable.cli --env sandbox auth --scope read
# Re-run with --scope 'read trade' only when the sandbox submission workflow is intentionally armed.
```

Required safe values in `engine/.env`:

```bash
TASTY_CLIENT_ID=...
TASTY_CLIENT_SECRET=...
TASTY_REDIRECT_URI=http://127.0.0.1:8182/callback
TASTY_REFRESH_TOKEN=...
TASTY_ACCOUNT_NUMBER=...

TASTY_IS_TEST=true
SVYABLE_ENV=sandbox
SVYABLE_OUTPUT_ROOT=outputs
SVYABLE_ENABLE_LIVE=false
SVYABLE_TASTY_AUDIT_PATH=outputs/audit/tastytrade.jsonl
```

`.env` is never committed. Production requires a separate, explicit operator decision: `TASTY_IS_TEST=false`, `SVYABLE_ENV=production`, `SVYABLE_ENABLE_LIVE=true`, and account-number confirmation at execution time. Do not set those during sandbox validation.

## First-light sequence

Run in order, and stop at the first BLOCK/failure.

```bash
cd ~/Svyable_Strategies/engine
source .venv/bin/activate

# 1. Offline sanity.
python -m pytest tests/
python -m svyable.cli --env sandbox smoke

# 2. Read-only + dry-run broker integration check. Never submits.
python -m svyable.sandbox_check

# 3. Start / refresh PIT universe snapshot accumulation.
python -m svyable.cli --env sandbox universe

# 4. Optional session warmup: OAuth, quote token, account read, universe snapshot.
python -m svyable.cli --env sandbox session

# 5. Daily selector + agent context pack. Agent mode should stop before activation.
python -m svyable.strategy_daily --env sandbox --provider yf --start 2020-01-01 --strict

# 6. Review memo and write a guarded decision.
svyable-agent-decide \
  --out outputs \
  --candidate <allowed_candidate_id> \
  --confidence 0.60 \
  --reason "Artifact-derived rationale from the board, context pack, and counterfactuals."

# 7. Freeze and audit the review package.
svyable-agent-review-chain --out outputs

# 8. Human-approved activation to canonical sandbox/paper artifacts.
svyable-strategy-activate --out outputs --env sandbox

# 9. Health/readiness review.
python -m svyable.cli --env sandbox --out outputs health
```

## Launchd installation

The LaunchAgent only runs the daily selector/context-pack step. It does **not** write decisions, activate portfolios, or submit orders.

```bash
cp ~/Svyable_Strategies/ops/com.svyable.daily.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.svyable.daily.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.svyable.daily.plist
launchctl list | grep svyable
```

Manual launch target dry-run:

```bash
SVYABLE_ENV=sandbox \
SVYABLE_PROVIDER=yf \
SVYABLE_STRICT_DAILY=true \
zsh ~/Svyable_Strategies/ops/run_daily.sh
```

Logs:

```bash
tail -n 200 ~/Svyable_Strategies/engine/logs/heartbeat.log
tail -n 200 /tmp/com.svyable.daily.out
tail -n 200 /tmp/com.svyable.daily.err
```

## What a clean sandbox day proves

A clean day means all of the following have evidence in outputs/ledger/audit files:

1. OAuth refresh survived the session.
2. Account read and quote snapshot worked.
3. PIT universe snapshot was attempted or refreshed.
4. Candidate board and context pack were generated.
5. The decision used only an allowed candidate ID and matched the board hash.
6. Guard, receipt, and audit chain passed.
7. Canonical weights were emitted exactly once after approval.
8. Broker dry-run/preflight was reviewed before any submission.
9. Any submitted sandbox orders were captured, deduped, and reconciled.
10. Warnings/exceptions were logged, investigated, and journaled.

That record, repeated across holds, switches, stale-data days, order lifecycle edge cases, and reconciliation days, is the Gate-B evidence base. It is not optional paperwork; it is the operating record.

## Cert lifecycle drills

Use small sandbox-only orders and explicitly label each drill in the journal.

| Drill | How to exercise | Pass condition |
|---|---|---|
| Immediate fill path | Market order or limit below cert fill threshold | Submit → fill capture → ledger/order record → reconciliation. |
| Working order path | Limit order above cert non-fill threshold | Live order appears, polling sees it, cancel/replace path works. |
| Rejection path | Intentionally impossible buying-power or invalid instrument test | Preflight or broker rejects; no silent partial state. |
| Duplicate batch defense | Re-run same batch/log path intentionally | Duplicate orders/transactions are blocked or clearly deduped. |
| Delayed/backfill path | Poll/backfill existing cert order after initial capture window | Backfill records state without poisoning economics. |
| Manual kill path | Abort before execute after preflight | No submitted orders; ledger records dry-run only. |

## Known cert limitations

- No reliable economic fill prices.
- No live-market performance signal.
- Streaming quotes can be delayed or unavailable.
- Cert instrument coverage can lag production; a 422 for a valid production symbol is a sandbox artifact until confirmed otherwise.
- Sandbox buying power/equity may not mirror production.
- If cert fills look impossible, do not tune alpha, costs, or universe to fit them.

## Daily operator checklist

Before market open:

- Confirm `run_daily.sh` succeeded or manually run it.
- Review `outputs/strategy_selection/latest_agent_pm_memo.md`.
- Confirm allowed candidates and blockers.
- Write guarded decision through `svyable-agent-decide` or the guarded UI.
- Run `svyable-agent-review-chain --out outputs`.
- Activate only after review-chain PASS and human approval.
- Review `svyable health`, dashboard/Portfolio Ops, canonical weights, and quote readiness.
- Use dry-run/preflight before any sandbox execution.

After market close:

- Check order/fill/reconcile artifacts.
- Confirm sandbox fills are tagged/treated as simulator artifacts.
- Check `svyable health` and open warnings.
- Append the day to `journal/YYYY-MM.md`: board hash, candidate, decision fingerprint, activation, preflight, orders, fills, reconciliation, exceptions, and operator sign-off.

## Stop conditions

Do not activate or submit if any of these are true:

- daily run failed or data is degraded under strict mode;
- latest context is missing;
- decision readiness is BLOCK;
- selected candidate is not in `allowed_candidate_ids`;
- guard, receipt, or audit is BLOCK;
- canonical destination already exists unexpectedly;
- broker preflight has errors;
- stale quotes/inputs cannot be explained;
- `TASTY_IS_TEST` is not true during sandbox validation;
- `SVYABLE_ENABLE_LIVE` is true before Gate C.
