# Svyable daily PM / agentic loop

Status: go-live operating contract refresh (2026-07-05). This runbook reflects the current engine controls: deterministic strategy evaluation, automatic agent context-pack generation, guarded decision writing, guard/receipt/audit review chain, and separately triggered activation.

The invariant is strict: **deterministic code computes complete candidate portfolios; the human/agent PM selects exactly one allowed candidate ID.** The PM loop never writes security weights, symbols, quantities, orders, factors, parameters, or same-cycle repository changes.

## Built control surface

| Layer | Current implementation | Go-live meaning |
|---|---|---|
| Candidate generation | `svyable.strategy_daily` refreshes the panel, evaluates registered strategies and chimeras, writes the immutable board, and records the run. | Code produces the investable menu; the agent does not invent it. |
| Agent context | In agent or evaluate-only mode, the daily runner writes `agent_context.json`, `agent_pm_memo.md`, and `agent_decision_template.json`. | Review material is generated from the same board/hash that activation will validate. |
| Decision writer | `svyable-agent-decide` fills date/hash from the latest context and rejects disallowed candidates before writing `agent_decision.json`. | Humans and agents should not hand-edit hashes. |
| Guard | `svyable-agent-guard --write` validates context readiness, date, hash, allowed candidate, confidence, reason, and artifact health. | Activation cannot proceed safely unless the guard is PASS. |
| Receipt + audit | `svyable-agent-review-chain` writes guard, review receipt, and integrity audit reports. | Reviewed context/decision files are hash-frozen before activation. |
| Activation | `svyable-strategy-activate` validates the latest board/decision and emits one canonical artifact under `outputs/svyable_nasdaq_lo/<tag>/`. | Tastytrade/Portfolio Ops consume only activated canonical weights. |
| Execution | Streamlit Portfolio Ops / Rebalance and `svyable rebalance --broker tasty` remain separately approved. | Candidate selection and broker execution stay separated by human/sandbox controls. |

## First-time install

Run from a clean checkout on the Mac that owns the morning loop:

```bash
cd ~/Svyable_Strategies/engine
uv venv .venv --python 3.14
uv pip install --python .venv/bin/python -e '.[all]'

cp .env.example .env
# Fill TASTY_CLIENT_SECRET, TASTY_REFRESH_TOKEN, TASTY_ACCOUNT_NUMBER.
# Keep TASTY_IS_TEST=true, SVYABLE_ENV=sandbox, SVYABLE_ENABLE_LIVE=false.

python -m svyable.sandbox_check
python -m svyable.cli --env sandbox universe

cp ../ops/com.svyable.daily.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.svyable.daily.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.svyable.daily.plist
launchctl list | grep svyable
```

If the Mac is not set to America/Chicago, adjust `Hour` in `ops/com.svyable.daily.plist` so the run lands at the intended pre-market PM-review time.

## Daily deterministic step

`ops/run_daily.sh` runs on weekdays through launchd. By default it executes:

```bash
python -m svyable.strategy_daily \
  --env sandbox \
  --provider yf \
  --start 2020-01-01 \
  --out outputs \
  --strict
```

Operator overrides are environment variables:

| Variable | Default | Purpose |
|---|---:|---|
| `SVYABLE_ENGINE_DIR` | `$HOME/Svyable_Strategies/engine` | Engine checkout path. |
| `SVYABLE_ENV` | `sandbox` | Isolated runtime profile. |
| `SVYABLE_PROVIDER` | `yf` | `yf` until tasty DXLink is fully customer-token ready; use `tasty` only after sandbox data check passes. |
| `SVYABLE_OUTPUT_ROOT` | `outputs` | Selection, ledger, and canonical artifact root. |
| `SVYABLE_START_DATE` | `2020-01-01` | Backfill start for daily panel. |
| `SVYABLE_STRICT_DAILY` | `true` | Refuse to proceed on degraded data. |
| `SVYABLE_HEALTHCHECK_URL` | empty | Optional healthchecks.io-style success/fail ping. |

The daily step writes:

```text
outputs/strategy_selection/<tag>/candidate_board.csv
outputs/strategy_selection/<tag>/candidate_board.json
outputs/strategy_selection/<tag>/selection.json
outputs/strategy_selection/<tag>/agent_context.json
outputs/strategy_selection/<tag>/agent_pm_memo.md
outputs/strategy_selection/<tag>/agent_decision_template.json
outputs/strategy_selection/latest_agent_context.json
outputs/strategy_selection/latest_agent_pm_memo.md
outputs/strategy_selection/agent_decision_template.json
outputs/strategy_selection/current_positions.json
```

Every candidate is a complete portfolio with factors, construction, risk, cadence, cost assumptions, operating inputs, and artifact health. Dynamic chimeras persist causal component-weight histories. The board hash is the immutable link between PM review and activation.

## PM / agent review prompt

Use this as the morning review contract after the candidate board exists:

```text
Svyable institutional strategy-selection review.

1. Read outputs/strategy_selection/latest_agent_pm_memo.md and the newest
   outputs/strategy_selection/*/candidate_board.csv.
2. Consider only candidate IDs listed under allowed_candidate_ids.
3. Compare utility, expected alpha, net expected alpha, estimated cost, turnover,
   current-position overlap, cadence, hold lock, kill switch, regime proxy,
   artifact health, factor trend summary, and counterfactual alternatives.
4. For the strongest single strategies and chimeras, inspect their output_dir
   artifacts: institutional_metrics.csv, pnl_diag.csv, weights_today.csv,
   execution_inputs.csv, ic_health.csv, factor_catalog.csv, and, for dynamic
   chimeras, component_weights_history.csv.
5. A chimera earns selection only when its diversification, capture profile,
   stability, implementation cost, and current-position overlap improve on its
   components. Do not select a blend merely because it contains more strategies.
6. Prefer hold_current when the evidence is weak, the regime proxy is defensive,
   the proposed switch is a short-sample effect, costs swamp alpha, or the current
   book already overlaps the candidate.
7. Never edit weights, factors, policy, strategy code, or repository files during
   this same board/activation cycle.
8. Write exactly one hash-matched decision using svyable-agent-decide or the
   guarded UI writer. The artifact path is:
   outputs/strategy_selection/agent_decision.json.
9. Run the review chain. Do not activate if any stage is BLOCK.
10. After human approval and review-chain PASS, run svyable-strategy-activate.
11. Confirm canonical weights_today.csv, morning_report.md, ledger row, and
    dashboard/Portfolio Ops readiness before any broker preflight.
12. Record proposal, approval, candidate hash, decision fingerprint, activation,
    and any execution/reconciliation notes in journal/YYYY-MM.md.
```

Recommended guarded decision command:

```bash
cd ~/Svyable_Strategies/engine
source .venv/bin/activate

svyable-agent-decide \
  --out outputs \
  --candidate <allowed_candidate_id> \
  --confidence 0.60 \
  --reason "Evidence-based rationale from the context pack, board, artifacts, and counterfactuals."

svyable-agent-review-chain --out outputs
```

Required decision schema:

```json
{
  "as_of": "YYYY-MM-DD",
  "candidate_set_hash": "board hash from latest context",
  "candidate_id": "one allowed candidate_id",
  "confidence": 0.60,
  "reason": "Artifact-derived rationale.",
  "operator": "human_pm",
  "written_at": "timestamp",
  "writer": "svyable.agent_decision_writer"
}
```

## Activation and operating handoff

Activation remains a distinct operator step:

```bash
cd ~/Svyable_Strategies/engine
source .venv/bin/activate

svyable-agent-review-chain --out outputs
svyable-strategy-activate --out outputs --env sandbox
svyable --env sandbox --out outputs health
```

Activation rejects:

- missing or malformed decision files;
- stale `as_of` values;
- candidate hash mismatches;
- candidate IDs not present on the latest board;
- ineligible candidates;
- second activation of the same board with a different decision;
- canonical destination collisions.

Only after activation may the operator open Portfolio Ops / Rebalance for quote review, drift review, dry-run preflight, and any explicit sandbox submission. Production live order submission remains disabled until the production gates in `production.md` pass.

## Hard rules

- The PM/agent chooses one immutable candidate ID, never security weights.
- Candidate weights are immutable after the board hash is produced.
- `hold_current` is always valid when evidence is weak and allowed by the board.
- Strategy definitions, policy, code, factor parameters, and cost assumptions change only through reviewed development work, not during a morning PM loop.
- Context pack recommendations may become future issues/branches; they must not alter the same-day board.
- If the daily run fails, yesterday's canonical weights remain in force.
- If guard, receipt, audit, or activation fails, no new canonical weights are emitted.
- If broker preflight or sandbox submission fails, the selection record remains intact; execution is investigated separately.
- Tastytrade consumes only canonical selected artifacts under `outputs/svyable_nasdaq_lo/`.

## Launch-day timeline

Times are intended pre-market review windows. The provided launchd plist is set for 06:30 America/Chicago, which is 07:30 America/New_York.

| Time ET | Step | Owner | Blocking artifact |
|---:|---|---|---|
| 07:30 | Refresh data, evaluate strategies/chimeras, write board/context pack | deterministic code | candidate board + latest context |
| 07:40 | Review memo, meta trace, artifacts, regime, counterfactuals | human/agent PM | allowed candidate IDs |
| 07:50 | Write guarded decision | human/agent PM | `agent_decision.json` |
| 07:55 | Run guard/receipt/audit review chain | deterministic code | `latest_agent_review_chain.json` PASS |
| 08:00 | Activate canonical portfolio after approval | deterministic code + human approval | canonical `weights_today.csv` |
| 08:05 | Health/readiness review | operator | `svyable health`, dashboard, Portfolio Ops |
| 09:15 | Sandbox preflight and order plan review | human + code | dry-run/preflight PASS |
| 09:28 | Optional human-triggered sandbox submission during validation era | human + code | explicit sandbox workflow |
| 16:15 | Fill capture, reconciliation, drift, ledger/journal update | code + human/agent PM | clean operating record |
