# Svyable agentic operating model

This document is the contract between Svyable's deterministic research engine, the human PM, the agent PM harness, and the broker-facing operations layer.

The short rule: **the agent may choose from audited candidate portfolios; it must not invent weights, symbols, quantities, orders, or same-cycle repository changes.**

## Two loops that must stay separate

```mermaid
flowchart LR
    subgraph DEV["Research / development loop"]
        IDEA["Idea: factor, strategy, harness, GUI"]
        BRANCH["Code change"]
        TEST["Tests / review"]
        MERGE["Merge to main"]
        IDEA --> BRANCH --> TEST --> MERGE
    end

    subgraph TRADE["Daily PM / rebalance loop"]
        DATA["Refresh market panel"]
        BOARD["Immutable candidate board"]
        PACK["Agent PM context pack"]
        DECIDE["Hash-matched decision artifact"]
        ACT["Canonical portfolio activation"]
        PLAN["Rebalance plan + preflight"]
        APPROVE["Human / sandbox controls"]
        BROKER["Broker adapter"]
        DATA --> BOARD --> PACK --> DECIDE --> ACT --> PLAN --> APPROVE --> BROKER
    end

    MERGE -. "future runs use merged code" .-> DATA
    PACK -. "may propose future improvements" .-> IDEA
```

The development loop can improve the repository. The daily trading loop must operate from already-approved code and already-generated artifacts. This avoids same-morning self-modification of the code path that produces the portfolio.

## Daily artifact flow

```mermaid
flowchart TB
    PANEL["Panel\nOHLCV + validation"]
    FACTORS["Governed factors\nprice action · residual · defensive · flow proxy"]
    STRATEGIES["Registered strategies\ncomplete factor/risk/cost/cadence recipes"]
    CHIMERAS["Causal chimeras\ncomponent-weight histories"]
    BOARD["candidate_board.csv/json\ncandidate_set_hash"]
    META["Meta harness\nvisible regime proxy · decision tree · counterfactuals"]
    CONTEXT["agent_context.json\nagent_pm_memo.md\nagent_decision_template.json"]
    DECISION["agent_decision.json\nallowed candidate_id only"]
    ACTIVATION["strategy_activation.py\ncanonical weights_today.csv"]
    OPS["Portfolio Ops\nquote board · drift · readiness"]
    ORDERS["Execution control\nplan_orders · preflight · audit"]

    PANEL --> FACTORS --> STRATEGIES --> BOARD
    STRATEGIES --> CHIMERAS --> BOARD
    BOARD --> META --> CONTEXT --> DECISION --> ACTIVATION --> OPS --> ORDERS
```

## Agent context pack files

| File | Owner | Purpose | Mutability |
| --- | --- | --- | --- |
| `candidate_board.csv` | Engine | Immutable ranked candidate set with hash | Read-only |
| `selection.json` | Engine | Deterministic or pending policy recommendation | Read-only |
| `agent_context.json` | Harness | Full machine-readable context, rails, trace, and counterfactuals | Read-only |
| `agent_pm_memo.md` | Harness | Human-readable memo for PM review | Read-only |
| `agent_decision_template.json` | Harness | Exact shape of legal decision artifact | Read-only template |
| `strategy_selection/agent_decision.json` | Agent / human | Selected allowed `candidate_id` + confidence + reason | Write-once per board |
| `weights_today.csv` | Engine after activation | Canonical target weights for broker planning | Engine-written only |

## Decision rails

```mermaid
stateDiagram-v2
    [*] --> BoardGenerated
    BoardGenerated --> ContextPackGenerated: generate meta harness
    ContextPackGenerated --> Blocked: stale artifacts / no legal candidates
    ContextPackGenerated --> AwaitingDecision: readiness PASS
    AwaitingDecision --> DecisionRejected: date/hash mismatch
    AwaitingDecision --> DecisionRejected: candidate not allowed
    AwaitingDecision --> Activated: hash + candidate valid
    Activated --> PlanBuilt: canonical weights only
    PlanBuilt --> PreflightFailed: stale inputs / missing prices / liquidity gates
    PlanBuilt --> ReadyForApproval: broker preflight OK
    ReadyForApproval --> SubmittedSandbox: explicit sandbox submit
    ReadyForApproval --> SubmittedProduction: production requires separate live controls
```

The agent decision is deliberately small:

```json
{
  "as_of": "YYYY-MM-DD",
  "candidate_set_hash": "hash from current board",
  "candidate_id": "one allowed candidate_id",
  "confidence": 0.0,
  "reason": "artifact-derived rationale"
}
```

## Visible meta trace

The meta trace is an **auditable rationale tree**, not hidden chain-of-thought. It exposes:

- HMM-like visible regime proxy: `risk_on`, `risk_off`, `chop`, `ops_stress`
- Selector gates: eligibility, rebalance threshold, cadence, hold lock, kill switch, turnover, utility
- Score decomposition: expected alpha minus cost, turnover penalty, and risk penalty
- Weight provenance: where deterministic target weights were read from, gross/net exposure, effective N, and top weights
- Counterfactual alternatives: what the focus candidate gained or lost versus competing candidates
- Decision readiness: PASS/BLOCK plus specific issues to fix before activation

## Broker-facing contract

Only activated canonical artifacts may reach order planning.

```mermaid
flowchart LR
    DECISION["valid decision artifact"] --> ACT["activate latest selection"]
    ACT --> TARGET["canonical weights_today.csv"]
    TARGET --> INPUTS["execution_inputs.csv\nprice · ADV · liquidity"]
    INPUTS --> PLAN["build_rebalance_plan"]
    PLAN --> PREFLIGHT["broker preflight"]
    PREFLIGHT --> AUDIT["ledger + order audit"]
    AUDIT --> SUBMIT["submit only under explicit controls"]
```

The agent never writes `weights_today.csv`. It never writes order quantities. It never bypasses activation, readiness, execution input checks, broker preflight, or human/sandbox controls.

## Operating commands

From `engine/` after installing requirements:

```bash
python -m pip install -r requirements.txt
python -m svyable.strategy_daily --evaluate-only
python -m svyable.agent_pm_harness --out outputs
python -m svyable.strategy_activate --out outputs
```

Equivalent installed scripts are exposed by `pyproject.toml`:

```bash
svyable-strategy-daily --evaluate-only
svyable-agent-pack --out outputs
svyable-strategy-activate --out outputs
```

## Human PM checklist

Before activation:

1. Open the Selection Meta Harness page.
2. Confirm decision readiness is `PASS`.
3. Review the decision tree, blocked candidates, counterfactuals, and visible regime proxy.
4. Confirm deterministic weight provenance and artifact freshness.
5. Write or approve the hash-matched decision artifact.
6. Activate canonical weights.
7. Use Portfolio Ops for quote checks, drift checks, broker preflight, and sandbox execution controls.

## Future improvement loop

The context pack may recommend research improvements, but those belong in the development loop:

```mermaid
flowchart LR
    MEMO["Agent PM memo"] --> ISSUE["Research/dev issue"]
    ISSUE --> CHANGE["Branch or direct reviewed change"]
    CHANGE --> TESTS["Unit/smoke/regression tests"]
    TESTS --> MAIN["Merge to main"]
    MAIN --> NEXT["Next daily run"]
```

Never let the agent alter the same code path during the same board/activation cycle.
