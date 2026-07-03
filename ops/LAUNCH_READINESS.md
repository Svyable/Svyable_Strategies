# Launch Readiness — Day-1 Inspection Record

Status: v1.0 (2026-07-02, prelaunch). Every claim below was verified by running
the command shown on this machine on this date. Companions: README.md
(narrative), production.md (gates), ops/SANDBOX.md (cert runbook),
ops/CLAUDE_LOOP.md (daily contract).

## Verified today, with evidence

| Claim | Evidence (2026-07-02) |
|---|---|
| Full offline suite green | `pytest tests/` → **38 passed, 0 failed** |
| Golden-weights gate green and meaningful | Re-blessed deliberately after the v0.2.0 config change (IC gating + ML hyperparameters, commit a48b3e8 had skipped the re-bless). New hash `662b6941bf669a54e4b8e628` @ config `6a8d224e9ad53d92`; byte-identical on rerun |
| No look-ahead anywhere in the pipeline | `test_causality_future_blindness` — truncate-at-T weights identical to 1e-9 |
| Restatement defense works on real data | Today's refresh detected a vendor-wide re-adjustment (~115 names) and forced a clean full refetch instead of caching a corrupted seam |
| Bad-print detection works on real data | 3 suspect ±40% spike-and-reverse bars flagged (FANG, HOOD, PDD); run marked DEGRADED, not silently trusted |
| Multi-strategy candidate board runs end-to-end | First board produced: `outputs/strategy_selection/20260702_224449/` — 7 registered candidates + hold_current, hash `e53161d0d45eba8288551704` |
| Agent contract enforces its gates | Tampered hash → `RuntimeError: Agent decision hash does not match`; ineligible candidate → `RuntimeError: Agent selected an ineligible candidate`; both refused before any weights were emitted |
| Legitimate decision activates exactly once | `q23_concentrated` activated; canonical artifacts under `outputs/svyable_nasdaq_lo/20260702_224449/`; re-running activation returns the original record (same `activated_at`), never a second book |
| Every step left a ledger trail | `runs` table: daily_selection (evaluated) → strategy_activation rows, all hash-stamped |
| Concentrated flagship registered and gated | `q23_concentrated`: 7–10 seats, 12% ceiling, full Q23 ensemble; mandate enforced by `test_concentrated_flagship_matches_mandate` |
| Sandbox fills cannot poison economics | Cert fill prices tagged `synthetic_fills`; slippage escalation suppressed to info-level in sandbox (`test_sandbox_synthetic_fills_do_not_escalate`) |

## Day-1 board result (first live-data selection)

The deterministic selector and the agent decision independently converged on
**q23_concentrated** — the 7–10-name flagship — as the bootstrap activation:
highest trailing 252-day Sharpe (2.49) among eligible candidates. The activated
book: 7 seats, equal-weighted at the 12% relative ceiling, gross throttled to
0.40x by the risk overlay (trailing vol 23% vs 17% target — the budget system
binding exactly as specified).

## Honest observations a reviewer should raise (we raise them first)

1. **Theme concentration.** Today's 7 names are all semiconductors/storage.
   The statistical cluster brake is active but links only pairs with trailing
   corr > 0.70; measured median pairwise corr of this book is 0.55 (max 0.90 in
   the memory trio), so the theme as a whole legitimately escapes the cap.
   Standing research item: cluster-threshold sensitivity for the concentrated
   flagship (a 9-name book needs a stricter notion of "same bet" than a
   25-name book).
2. **Candidate backtests are survivorship-biased** until PIT snapshot
   accumulation has history (`universe.py` starts the clock the day
   credentials exist). The 63.58% / Sharpe 3.545 reference is a Q23 contest
   result, not a Svyable claim.
3. **Selection estimates are forecasts.** Board `expected_alpha_bps` is a
   causal estimate for ranking candidates, not a promised return.
4. **The operating record is zero days old.** Everything above proves the
   machine works once; Gate B requires it to work for 60 clean days.

## Blocked only on credentials (sandbox portal, ~15 minutes)

1. OAuth2 app → client secret; refresh token (read + trade); sandbox account
   number → `engine/.env` per ops/SANDBOX.md.
2. Then, in order: `python -m svyable.sandbox_check` → `svyable universe`
   (starts the irreplaceable PIT clock) → load
   `ops/com.svyable.daily.plist` → set `SVYABLE_HEALTHCHECK_URL` (arms the
   dead-man switch).

## Standing configuration decisions on record

- Selection policy: **agent mode** (`outputs/strategy_selection/policy.json`)
  per the validation-era contract in ops/CLAUDE_LOOP.md — deterministic code
  evaluates, the PM/agent picks a candidate ID, activation validates.
- `SVYABLE_ENABLE_LIVE=false`; production bulk submission disabled; sandbox is
  the only execution venue until the production gates in production.md pass.
