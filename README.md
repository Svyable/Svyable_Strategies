# Svyable Strategies

Svyable Strategies is a daily cross-sectional alpha research, portfolio-management, and operations platform derived from the strongest price-action ideas in [`Svyable/Q23_QUANT_SYSTEM_2`](https://github.com/Svyable/Q23_QUANT_SYSTEM_2).

The objective is effective systematic trading research: differentiated alpha sources, controlled beta participation, robust volatility and turbulence avoidance, honest costs, observable decisions, and one safe operating boundary.

Svyable is **paper-operational research infrastructure**. It is not yet a live-capital track record.

## Latest and greatest

- **Daily roster decision:** evaluate all enabled strategies and chimeras, then pick one legal candidate from an immutable `candidate_board.csv` with a `candidate_set_hash`.
- **PM decision scorecard:** Agent Lab translates each board into GREENLIGHT / REVIEW / HOLD / BLOCK language using edge vs hold, turnover, overlap, drawdown, volatility, cost, eligibility, and risk flags.
- **Decision ticket:** the scorecard produces a copy-ready guarded-decision rationale plus downloadable markdown/CSV for review notes and audit handoff.
- **Agentic PM rails:** context pack, memo, guarded decision writer, guard, receipt, audit, and one-click review chain keep the agent/human choice hash-matched and reviewable.
- **Streamlit command surfaces:** PM Command Center, Agent Lab, Selection Meta Harness, Factor Governance, Analytics/Arcana, Factor Health, Portfolio Ops, and audit views.
- **Interactive PM charts:** the GUI extra includes Plotly for hoverable/zoomable candidate rankings, candidate deep-dive performance/regime charts, factor-health reliability maps, strategy maturity mix, decision scorecard maps, stress-lab bars, drawdown tapes, monthly heatmaps, position-overlap heatmaps, alpha-vs-turnover maps, and multi-strategy equity overlays. Matplotlib remains the static fallback.
- **Deterministic PM one-pager:** `tests/test_regression.py` renders `golden_weights_human.md` with provenance, holdings, risk posture, regime stack, Markov price-action state, sleeve IC health, factor stack, and construction settings.
- **Complete strategy frontier:** every registered strategy owns factors, construction, concentration, risk, cost, cadence, maturity, and an operating role.
- **Alpha families:** price-action, residual, defensive, reversal, liquidity, behavioral, frontier tape-reading, tape-acceleration, alpha-catalyst, rotation-breadth, and clearly labeled daily-flow proxy factors.
- **Portfolio construction:** correlation-cluster caps, score/equal/HRP/blended seat weighting, no-trade bands, ADV-aware operating inputs, volatility targeting, structural turbulence, absorption ratio, breadth, panic state, and own-book kill switch.
- **Broker boundary:** Tastytrade SDK adapter supports sandbox-first preflight, redacted audit logging, explicit confirmation gates, reconciliation handoff, and ledger-backed execution health.

## What is not claimed

- No live-capital performance is claimed.
- Bulk production action from Streamlit remains disabled.
- The strategy and chimera registry has not yet accumulated a sustained sandbox operating record.
- Seed-universe historical tests remain survivorship-biased unless explicitly labeled point-in-time.
- Institutional metrics are engineering evidence, not promised future returns.

## Daily PM loop

1. Refresh and validate the daily OHLCV panel.
2. Compute governed factors and build candidate artifacts for every enabled strategy/chimera.
3. Write the immutable candidate board and PM context pack.
4. Review Streamlit: Agent Lab decision scorecard, Candidate Deep Dive, Stress Lab, Selection Meta Harness, Factor Governance, and Portfolio Ops readiness.
5. Copy the decision-ticket rationale into the guarded decision writer only after human review.
6. Write exactly one guarded decision from an allowed `candidate_id`.
7. Run guard → receipt → audit.
8. Activate canonical weights only after review PASS.
9. Use Portfolio Ops for quote sanity, drift review, preflight, sandbox workflow, reconciliation, and audit.
10. Feed observations back into the research loop for future commits, never same-cycle repo self-modification.

## Install

**Requires Python 3.14+** (`pyproject.toml` sets `requires-python = ">=3.14"`). From `engine/`:

```bash
uv venv .venv --python 3.14
uv pip install --python .venv/bin/python -r requirements.txt   # installs offline research + GUI + dev extras
```

`requirements.txt` intentionally matches the offline CI and Streamlit/agent PM workflow. Live broker SDK connectivity is opt-in:

```bash
uv pip install --python .venv/bin/python -e .[broker]
```

For a byte-for-byte reproducible environment, install from the lockfile after regenerating it for the current optional-extra policy:

```bash
uv pip install --python .venv/bin/python -r requirements.lock
```

Optional groups are declared in `engine/pyproject.toml`:

| Extra | Purpose |
| --- | --- |
| `data` | YFinance/Tasty market data clients and HTTP/websocket plumbing |
| `ml` | scikit-learn ML sleeve |
| `hrp` | SciPy-backed HRP / clustering support |
| `gui` | Streamlit, Matplotlib, Plotly, and watchdog for interactive PM review |
| `broker` | Tastytrade SDK live-broker adapter |
| `dev` | pytest |
| `all` | data + ml + hrp + gui + broker |

Package policy: add dependencies only when they materially improve decision quality, operating safety, or research velocity. Plotly is included because it turns the highest-value PM charts into interactive decision surfaces; no new quant dependency was added in this pass because NumPy/Pandas/SciPy/scikit-learn already cover the current alpha and risk stack.

## Daily commands

```bash
python -m svyable.strategy_lifecycle --strategy svyable_alpha_catalyst
python -m svyable.strategy_registry_quality --write --out outputs
python -m svyable.strategy_daily --evaluate-only
python -m svyable.agent_pm_harness --out outputs
python -m svyable.agent_decision_writer --out outputs --candidate <allowed_candidate_id> --confidence 0.60 --reason "Reviewed meta harness and approved this candidate."
python -m svyable.agent_review_chain --out outputs
python -m svyable.strategy_activate --out outputs
```

Installed script equivalents:

```bash
svyable-strategy-day --strategy svyable_alpha_catalyst
svyable-registry-quality --write --out outputs
svyable-strategy-daily --evaluate-only
svyable-agent-pack --out outputs
svyable-agent-decide --out outputs --candidate <allowed_candidate_id> --confidence 0.60 --reason "Reviewed meta harness and approved this candidate."
svyable-agent-review-chain --out outputs
svyable-strategy-activate --out outputs
```

## Core artifacts

| Artifact | Produced by | Consumed by | Purpose |
| --- | --- | --- | --- |
| `candidate_board.csv` | `strategy_selector.py` | human, agent, GUI | Immutable ranked candidate set with hash |
| `agent_context.json` | `agent_pm_harness.py` | agent / GUI | Machine-readable board, rails, trace, readiness |
| `agent_pm_memo.md` | `agent_pm_harness.py` | human PM | Human-readable decision memo |
| `agent_decision.json` | guarded writer / agent / human | guard + activation | Hash-matched candidate choice |
| `latest_agent_decision_guard.json` | `agent_decision_guard.py` | human / automation | PASS/BLOCK validation report |
| `latest_agent_review_receipt.json/md` | `agent_review_receipt.py` | human / audit | Frozen review packet with file hashes |
| `latest_agent_review_audit.json` | `agent_review_audit.py` | human / automation | Receipt integrity report |
| `latest_agent_review_chain.json` | `agent_review_chain.py` | human / automation | One-click review-chain report |
| `latest_strategy_registry_quality.json/md` | `strategy_registry_quality.py` | human / governance | Registry audit |
| `golden_weights_human.md` | `tests/test_regression.py` | human / CI review | Deterministic PM one-pager for the pinned golden fixture |
| `weights_today.csv` | activation / pipeline | Portfolio Ops | Canonical target weights |
| `execution_inputs.csv` | pipeline | rebalancer / preflight | Prices, ADV, liquidity flags |
| `ledger.db` | ops layers | dashboards / audit | Runs, warnings, actions, fills, drift |

## Repository map

| Layer | Important modules |
| --- | --- |
| Data | `providers.py`, `panel.py`, `calendar.py`, `universe.py` |
| Factors | `factor_library.py`, `factor_ohlcv_tools.py`, `factor_institutional.py`, `factor_price_action_frontier.py`, `factor_tape_acceleration.py`, `factor_alpha_catalyst.py`, `factor_rotation_breadth.py`, `factor_health_tools.py` |
| Portfolio intelligence | `portfolio_arcana.py`, `selection_explain.py`, `agent_meta_trace.py`, `strategy_alpha_diagnostics.py`, `strategy_decision_scorecard.py` |
| Strategy frontier | `strategy_registry.py`, `strategy_registry_quality.py`, `strategy_lifecycle.py`, `strategy_tape_acceleration.py`, `strategy_alpha_catalyst.py`, `strategy_rotation_breadth.py`, `strategy_blend.py`, `strategy_daily.py`, `strategy_selector.py` |
| GUI surfaces | `dashboard_command_center.py`, `dashboard_agent.py`, `dashboard_interactive.py`, `dashboard_charts.py`, `dashboard_factor_governance.py`, `dashboard_portfolio_ops.py`, Streamlit `pages/` |
| Agent PM harness | `agent_pm_harness.py`, `agent_decision_writer.py`, `agent_decision_guard.py`, `agent_review_receipt.py`, `agent_review_audit.py`, `agent_review_chain.py`, `strategy_activate.py` |
| Operations | `dashboard_readiness.py`, `dashboard_live_market.py`, `rebalancer.py`, `execution_control.py`, `submission_guard.py`, `tastytrade_sdk.py`, `ledger.py` |
| Tests | Regression, broker safety, rebalancer/execution policy, ledger execution status, agent PM rails, GUI models, factor governance, strategy readiness, rotation breadth, and interactive dashboard chart tests. |

## Safety and truthfulness

Svyable is designed so the agent can improve review quality without bypassing human and operating rails. The visible meta harness, scorecard, and decision ticket are auditable rationale layers, not hidden chain-of-thought. They explain what the artifacts imply; they do not claim certainty, future returns, or live-capital performance.
