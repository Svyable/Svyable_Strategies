# A day in the life of a Svyable strategy

This document describes the daily lifecycle of a Svyable strategy candidate. The example strategy is `svyable_alpha_catalyst`, but the flow applies to every registered strategy and chimera candidate.

Svyable has two loops that must stay separate:

1. **Research/development loop**: propose factor, strategy, GUI, guardrail, or infrastructure changes; write code; review; test; merge to `main`.
2. **Daily PM loop**: run already-approved code; build a candidate board; package visible context; write one guarded decision; run review-chain checks; then hand canonical artifacts to operations.

The daily loop never modifies the codebase mid-cycle. Any idea discovered during review becomes future research work.

## Timeline

### 00 · Approved-code boundary

The strategy starts the day as code already present on `main`. If Alpha Catalyst was changed yesterday, today can use it. If a new improvement is proposed during today’s PM review, it waits for the research/development loop.

Artifact: repository commit history.

Guardrail: no same-cycle repo self-modification inside the daily PM loop.

### 01 · Data refresh

The runtime refreshes the daily OHLCV panel, validates shape and expected dates, and prepares the data used by every factor.

Artifact: `Panel(open, high, low, close, volume)`.

Guardrail: stale or incomplete inputs surface as readiness issues.

### 02 · Factor compute

The factor library computes the strategy’s causal daily-bar factor pack. For `svyable_alpha_catalyst`, this includes residual acceleration, residual breakout, downside absorption, failed breakdown reclaim, idiosyncratic trend quality, volatility-transition alpha, Tape Acceleration, institutional trend, resilience, and risk/liquidity controls.

Artifact: factor score frames.

Guardrail: higher factor values must be oriented as more attractive to own; shadow/incubation factors earn no guaranteed floor.

### 03 · Strategy recipe

The strategy registry turns factor IDs and configuration into a complete executable recipe: seats, concentration, smoothing, no-trade band, costs, target volatility, stressed volatility, maturity, family, and pitch role.

Artifact: `StrategySpec` plus built `SvyableConfig`.

Guardrail: strategy recipes own their factor/config contract; agents do not invent raw weights, symbols, or quantities.

### 04 · Candidate construction

The portfolio engine turns factor scores into a candidate portfolio artifact. It applies seat selection, score smoothing, no-trade bands, cluster caps, cost assumptions, volatility targeting, and operating-input requirements.

Artifact: candidate weights and operating inputs.

Guardrail: ADV, concentration, turbulence, and cost controls throttle the candidate before PM review.

### 05 · Candidate board

The selector evaluates all enabled strategies and chimeras, ranks them, and writes an immutable candidate board with a candidate-set hash.

Artifact: `candidate_board.csv` and `candidate_set_hash`.

Guardrail: later decisions must reference one allowed candidate ID and the matching hash.

### 06 · Visible PM context

The agent PM harness creates a context pack with allowed IDs, candidate rows, visible score decomposition, regime proxy, readiness gates, blocked candidates, counterfactual alternatives, and memo text.

Artifacts: `agent_context.json`, `agent_pm_memo.md`, and `agent_decision_template.json`.

Guardrail: the harness explains artifacts; it does not expose hidden reasoning or create positions.

### 07 · Human/agent review

The human PM opens Selection Meta Harness and Factor Governance. The review screens show alpha candidate spotlight, Factor Governance alpha cockpit, registry quality audit, factor maturity, strategy coverage, utility decomposition, candidate ranking, visible regime proxy, decision tree, weight provenance, and artifact inventory.

Artifact: GUI review and optional registry-quality report.

Guardrail: review is read-only until a guarded decision artifact is written.

### 08 · Decision artifact

The guarded decision writer produces a small decision file using the latest board date/hash and one allowed candidate ID.

Artifact: `strategy_selection/agent_decision.json`.

Guardrail: the decision contains candidate ID, confidence, reason, operator, and context identifiers only. It does not contain quantities or orders.

### 09 · Guard / receipt / audit

The review chain validates the decision, freezes reviewed file hashes, and checks those files remain unchanged.

Artifacts: `latest_agent_decision_guard.json`, `latest_agent_review_receipt.json/md`, `latest_agent_review_audit.json`, and `latest_agent_review_chain.json`.

Guardrail: any `BLOCK` must be resolved before canonical artifacts are prepared.

### 10 · Canonical artifact handoff

After review passes, the selected candidate can become the canonical target artifact consumed by Portfolio Ops. Operations then handles quote sanity, drift review, preflight, sandbox workflow, reconciliation, and ledger/audit.

Artifacts: `weights_today.csv`, `execution_inputs.csv`, and `ledger.db`.

Guardrail: operations consume canonical artifacts only; bulk production action from Streamlit remains disabled.

### 11 · Learning loop

Diagnostics, factor health, registry quality findings, artifacts, and review observations flow back into the research/development loop for future code changes.

Artifacts: docs, tests, commits, governance reports.

Guardrail: improvements can inform tomorrow’s board, not today’s already-reviewed cycle.

## Commands

Render a read-only lifecycle narrative:

```bash
svyable-strategy-day --strategy svyable_alpha_catalyst
```

Persist JSON and Markdown runbooks:

```bash
svyable-strategy-day --strategy svyable_alpha_catalyst --write --out outputs
```

Run the registry quality audit referenced in the PM review:

```bash
svyable-registry-quality --write --out outputs
```

## What this resolves

The repo previously had strong modules for the daily PM flow, but no single user-facing narrative that explained how a strategy moves from approved code to reviewed candidate to canonical artifacts. The new runbook and CLI make that lifecycle explicit and testable without changing daily selection behavior.
