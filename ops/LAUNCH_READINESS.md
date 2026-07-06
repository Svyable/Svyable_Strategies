# Launch Readiness — Go-Live Inspection Record

Status: **sandbox go-live candidate / production capital blocked** (refreshed 2026-07-05).

This document is a codebase-review readiness record, not a claim that today's machine-level commands have already run. The current repo implements the daily candidate board, agent context pack, guarded decision, review receipt/audit chain, sandbox check, ledger, and canonical activation path. Go-live here means **validation-era sandbox/paper operations**. Production capital remains blocked by the gates in `production.md`.

## Readiness verdict

| Scope | Verdict | Reason |
|---|---|---|
| Daily PM loop | **READY FOR SANDBOX GO-LIVE AFTER LOCAL SMOKE** | `strategy_daily` evaluates candidates and writes agent context packs in agent/evaluate-only mode; launchd script now runs strict daily selection with heartbeat logging. |
| Agentic decision loop | **READY FOR CONTROLLED USE** | The writer fills date/hash from context, guard validates allowed candidate + artifact readiness, and review chain freezes hashes before activation. |
| Canonical activation | **READY FOR SANDBOX/PAPER** | Activation validates board date/hash/eligibility and emits exactly one canonical artifact directory. |
| Broker sandbox plumbing | **READY AFTER CREDENTIALS CHECK** | `sandbox_check` validates OAuth/account/quote/dry-run and refuses production credentials. |
| Production live capital | **BLOCKED** | Gate B/C evidence is not yet complete: sustained sandbox operating record, account kill-switch fire drill, production sign-off, measured execution costs, and live-enable controls. |

## Codebase evidence reviewed

| Area | Evidence in repo | Readiness implication |
|---|---|---|
| Current truth | README says Svyable is paper-operational research infrastructure and explicitly disclaims live-capital performance. | Ops docs must not describe this as live-capital ready. |
| Agent context pack | `agent_pm_harness.py` builds `agent_context.json`, `agent_pm_memo.md`, decision rails, artifact health, factor warnings, visible meta trace, and counterfactuals. | PM/agent receives auditable context, not a blank prompt. |
| Daily runner | `strategy_daily.py` refreshes data, checks staleness/degradation, evaluates candidates, writes current-position snapshots, and writes the agent context pack when awaiting agent. | Morning launchd can stop at board/context generation in agent mode. |
| Guarded writer | `agent_decision_writer.py` reads the latest context, restricts candidate IDs to allowed IDs, writes date/hash automatically, and immediately runs the guard. | Hash and date errors should not come from manual editing. |
| Guard | `agent_decision_guard.py` validates required fields, context readiness, date/hash, allowed candidate, confidence, reason, artifact freshness, and required execution columns. | Activation should be preceded by a deterministic PASS/BLOCK report. |
| Receipt and audit | `agent_review_receipt.py` freezes decision/context/memo/guard file hashes; `agent_review_audit.py` checks they are unchanged. | The review state is tamper-evident before activation. |
| Review chain | `agent_review_chain.py` orchestrates optional context refresh, guard, receipt, and audit without writing decisions, targets, or orders. | One operator command can verify the non-trading review package. |
| Activation | `strategy_activation.py` rejects stale/mismatched/ineligible decisions and writes one canonical `outputs/svyable_nasdaq_lo/<tag>/` artifact. | Portfolio Ops and broker preflight have a single canonical target. |
| Credentials | `broker_settings.py` loads canonical `TASTY_*` variables, accepts legacy `TT_*` aliases, defaults to sandbox, and keeps `SVYABLE_ENABLE_LIVE=false` unless explicitly changed. | Sandbox is the safe default; production requires multiple deliberate changes. |
| Sandbox check | `sandbox_check.py` refuses production credentials and performs read-only/session/quote/dry-run checks without submitting orders. | This is the first real-account gate before any sandbox order workflow. |
| CLI | `svyable auth`, `svyable universe`, `svyable session`, `svyable health`, `svyable tasty`, and `svyable rebalance --broker tasty` exist for onboarding, health, and broker workflow. | Ops docs can use installed commands instead of manual Python one-offs. |
| Tests present | Agent pack/writer tests verify context/memo/template generation and disallowed-candidate rejection. | Specific agentic rails have unit coverage; run the full suite locally before go-live. |

## Day-0 local verification checklist

Run these on the target Mac before trusting the launchd job:

```bash
cd ~/Svyable_Strategies/engine
source .venv/bin/activate

python -m pytest tests/
python -m svyable.cli --env sandbox smoke
python -m svyable.sandbox_check
python -m svyable.cli --env sandbox universe
python -m svyable.strategy_daily --env sandbox --provider yf --start 2020-01-01 --strict
python -m svyable.agent_decision_guard --out outputs --write || true
python -m svyable.cli --env sandbox --out outputs health
```

Expected first-day interpretation:

- Full tests must pass before launchd is loaded.
- Smoke must pass without network.
- `sandbox_check` must return `PASS` before any broker sandbox workflow.
- `strategy_daily` in agent mode should produce a board/context pack and normally end with `awaiting_agent`.
- `agent_decision_guard` may return `BLOCK` until a decision is written; that is expected.
- `health` should show the latest selection run and no unexplained critical warnings.

## Sandbox go-live sequence

1. Confirm `engine/.env` exists and contains only sandbox-safe values:
   - `TASTY_IS_TEST=true`
   - `SVYABLE_ENV=sandbox`
   - `SVYABLE_ENABLE_LIVE=false`
   - canonical `TASTY_CLIENT_SECRET`, `TASTY_REFRESH_TOKEN`, `TASTY_ACCOUNT_NUMBER`
2. Run `python -m svyable.sandbox_check`.
3. Run `python -m svyable.cli --env sandbox universe` to start / refresh PIT snapshot accumulation.
4. Run one manual strict daily cycle:
   `python -m svyable.strategy_daily --env sandbox --provider yf --start 2020-01-01 --strict`.
5. Review `outputs/strategy_selection/latest_agent_pm_memo.md`.
6. Write a guarded decision:
   `svyable-agent-decide --out outputs --candidate <allowed_candidate_id> --confidence 0.60 --reason "<artifact-derived rationale>"`.
7. Run `svyable-agent-review-chain --out outputs` and require `PASS`.
8. Activate only after human approval:
   `svyable-strategy-activate --out outputs --env sandbox`.
9. Review `svyable --env sandbox --out outputs health` and Portfolio Ops.
10. Only then run a sandbox dry-run/preflight or a human-triggered sandbox submission workflow.

## LaunchAgent status

`ops/com.svyable.daily.plist` is now configured for the target validation-era loop:

- weekdays at 06:30 local America/Chicago time, i.e. 07:30 New York market time;
- sandbox environment;
- strict daily data handling;
- explicit output root;
- logs to `/tmp/com.svyable.daily.out` and `/tmp/com.svyable.daily.err`;
- script-level heartbeat logging and optional external healthcheck pings.

Install / refresh:

```bash
cp ~/Svyable_Strategies/ops/com.svyable.daily.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.svyable.daily.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.svyable.daily.plist
launchctl list | grep svyable
```

Manual dry-run of the launch target:

```bash
SVYABLE_ENV=sandbox \
SVYABLE_PROVIDER=yf \
SVYABLE_STRICT_DAILY=true \
zsh ~/Svyable_Strategies/ops/run_daily.sh
```

## Production blockers still open

Production capital remains blocked until all are true:

1. At least 60 clean sandbox/paper operating days are recorded.
2. Heartbeat uptime is at or above the pre-committed threshold.
3. Reconciliation drift is explained and within Gate-B tolerance.
4. PIT universe snapshots have accumulated and walkforward remains robust.
5. Account-based kill switch is built, tested, and fire-drilled.
6. Order lifecycle edge cases are fire-drilled: rejection, working limit, cancel/replace, partial fill/delayed fill, duplicate batch.
7. Measured sandbox/live-like execution-cost evidence has been reviewed and fed back into cost assumptions where appropriate.
8. Human sign-off packet exists with candidate history, review receipts, audits, health logs, fills, drift, exceptions, and resolved warnings.
9. Only then consider `TASTY_IS_TEST=false`, `SVYABLE_ENV=production`, and `SVYABLE_ENABLE_LIVE=true` with account-number confirmation.

## Honest caveats to keep visible

- The platform has engineering evidence, not a live-capital track record.
- Sandbox fills have no economic signal and must never support performance claims.
- Seed-universe history remains survivorship-biased until PIT snapshots have sufficient history.
- Agent reasoning is limited to visible artifacts and allowed candidate IDs.
- Same-cycle code or policy edits remain forbidden during a board/activation cycle.
- If any local verification command fails, stay in manual research mode and do not load the launchd job.
