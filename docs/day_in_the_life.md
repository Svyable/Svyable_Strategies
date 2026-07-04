# A day in the life of a Svyable strategy

PM training guide. This walks through one full daily cycle — from waking the
engine up to activating a canonical portfolio — using the **real output from a
verified run** so you know exactly what each screen and command should show.

Read [`agentic_operating_model.md`](agentic_operating_model.md) once for the
"why." This document is the "how," step by step.

## The one rule that governs everything

> The agent (and you) may **choose** one candidate from an audited board.
> Neither of you may **invent** weights, symbols, quantities, orders, or push a
> code change during the same cycle.

Every step below exists to enforce that rule. The engine builds the menu; you
pick from the menu; a guard checks your pick; only then does anything become a
real target portfolio.

## The two loops (don't cross them)

- **Research / dev loop** — improving factors, strategies, the harness, the GUI.
  Lives in branches, tests, and merges to `main`. Do this *any day except the
  morning you are activating.*
- **Daily PM loop** — the six steps below. Operates only on already-merged code
  and already-generated artifacts.

If the memo suggests a research improvement, that's a ticket for tomorrow's dev
loop — never a same-morning code edit.

## Who does what (separation of duties)

The rails only work because no single actor can do everything. Know your lane.

| Actor | May do | May **not** do |
| --- | --- | --- |
| **Engine** (deterministic code) | Build the panel, factors, strategies, chimeras; write the immutable board + hash; write canonical `weights_today.csv` **after** a guard PASS | Choose which candidate is active; skip validation |
| **Agent PM** (or you, acting as one) | Read the context pack; select **one allowed `candidate_id`**; write the small decision artifact with a reason | Invent weights, symbols, quantities, or orders; edit repo code this cycle; pick a non-allowed candidate |
| **Decision guard** | Validate the artifact against the board (date, hash, allowed candidate, confidence, reason, freshness); emit PASS/BLOCK | Activate anything; change the decision |
| **Human PM (you)** | Review the trace, approve/write the decision, resolve BLOCKs, approve the sandbox workflow | Bypass a BLOCK, a stale-input gate, or a failed preflight |

If you ever find yourself hand-editing `weights_today.csv` or an order
quantity, **stop** — that is outside every lane and defeats the audit trail.

## Setup (once)

```bash
cd engine
python -m pip install -r requirements.txt
```

Two ways to drive the daily loop. **Use the GUI as your primary surface**; the
CLI is the same steps in the terminal for automation or when you want receipts.

Launch the console:

```bash
python -m svyable.ui        # opens the Streamlit PM Command Center on :8501
```

You'll see six tabs — **🧠 Command Center · 🤖 Agent Lab · 📈 Analytics ·
🧬 Factors · 🏦 Portfolio Ops · 🧾 Audit** — plus a sidebar showing environment
(SANDBOX vs PRODUCTION), broker status, live-submission gate, and frontier
coverage. The dedicated **Selection Meta Harness** review screen is
`pages/8_Agent_Meta_Harness.py`.

> Sandbox is the safe default. Bulk production submission stays disabled. Even
> when live submission is enabled, orders require typed confirmation.

---

## The morning cycle — six steps

Each step lists the command, what it produces, and **what "good" looks like**
using the numbers from a real run (board date `2026-07-02`, hash
`485f8daf4d8e2b4865d25048`).

### Step 1 — Wake the engine: build the candidate board

```bash
python -m svyable.strategy_daily --evaluate-only --out outputs
```

Refreshes the OHLCV panel, recomputes governed factors, runs every enabled
strategy and chimera, and writes an **immutable ranked candidate board** with a
`candidate_set_hash`. `--evaluate-only` means *build the menu, don't activate
anything.*

- On a normal trading day this just runs. On a **weekend/holiday** it prints
  `market holiday/weekend — skipping`; add `--force` to run anyway for
  training/demo.
- This is the only network-heavy step (it fetches the universe). Give it a few
  minutes.

The board (`candidate_board.csv`) is the menu. Real example — four rows, one
eligible:

| candidate_id | eligible | utility_bps | expected_alpha_bps | one-way turnover | why not eligible |
| --- | --- | --- | --- | --- | --- |
| `hold_current` | ✅ | 5.376 | 5.376 | 0.0 | — (the no-trade baseline) |
| `q23_concentrated` | ❌ | −31.1 | 5.42 | 0.048 | cadence not due |
| `q23_hybrid_alpha` | ❌ | −48.6 | 5.50 | 0.121 | minimum hold lock active |
| `q23_defensive_alpha` | ❌ | −50.5 | 6.41 | 0.154 | minimum hold lock active |

**Reading it:** `q23_defensive_alpha` has the *highest raw alpha* (6.41 bps) but
the *worst utility* (−50.5) once turnover and risk penalties are charged, and
it's hold-locked anyway. `hold_current` wins because trading today costs more
than it earns. This is the system doing its job: not every strong signal is
worth a trade.

### Step 2 — Build the context pack (the agent/PM briefing)

```bash
python -m svyable.agent_pm_harness --out outputs
```

Turns the immutable board into a decision briefing:

| File | For | Purpose |
| --- | --- | --- |
| `agent_context.json` | agent / GUI | machine-readable board, rails, trace, readiness |
| `agent_pm_memo.md` | **you** | human-readable memo |
| `agent_decision_template.json` | agent / you | the exact legal shape of a decision |

The memo (`agent_pm_memo.md`) is your morning read. From the real run:

- **Visible regime proxy:** `risk_on` (0.4566 risk_on / 0.2402 risk_off / 0.0934
  chop / 0.2098 ops_stress)
- **Decision readiness:** `PASS` · next step: *prepare decision artifact*
- **Eligible candidates:** 1 / 4 · **top eligible:** `hold_current`
- **Hard rails** (printed every day): choose exactly one allowed `candidate_id`;
  don't edit code this cycle; don't invent weights/symbols/quantities/orders;
  hold when nothing improves the state; activation stays a separate step.
- **Visible decision tree** for the focus candidate — each gate shows
  PASS/BLOCK: `selector_eligibility`, `rebalance_required`, `cadence_due`,
  `hold_lock`, `kill_switch`, `turnover`, `utility`.
- **Counterfactual table** — what each alternative *would* have gained/lost and
  why it was blocked.

This is an **auditable rationale tree, not hidden chain-of-thought.** It tells
you what the artifacts imply; it never claims certainty or future returns.

### Step 3 — Make the call: write the decision artifact

In the GUI: open **Selection Meta Harness**, confirm readiness is `PASS`, review
the tree / blocked candidates / counterfactuals / weight provenance, then
approve the decision. On the CLI, write
`outputs/strategy_selection/agent_decision.json` — and it must be exactly this
shape (nothing more):

```json
{
  "as_of": "2026-07-02",
  "candidate_set_hash": "485f8daf4d8e2b4865d25048",
  "candidate_id": "hold_current",
  "confidence": 0.7,
  "reason": "Best switch (defensive, 6.41 bps) beats hold (5.38 bps) by ~1 bp, under the 2 bps switch buffer; hybrid/defensive are hold-locked and concentrated is not cadence-due. Discipline: hold."
}
```

Rules you can't get around: the `candidate_id` must be one of the **allowed**
IDs, the `candidate_set_hash` and `as_of` must match today's board, `confidence`
is in `[0,1]`, and `reason` must be substantive. It's **write-once per board.**

### Step 4 — Run the guard (the safety check)

```bash
python -m svyable.agent_decision_guard --out outputs --write
```

Validates your decision against the latest context before anything can activate.
A clean pass looks like:

```json
{ "status": "PASS", "blockers": [], "next_step": "activate latest selection" }
```

**What a BLOCK looks like — and why you want it.** If you (or the agent) pick a
candidate that isn't allowed today, the guard stops the cycle cold:

```
status: BLOCK
blockers: ['decision candidate_id is not in allowed_candidate_ids']
```

The guard also BLOCKs on a stale date/hash, out-of-range confidence, a weak
reason, or an un-ready context. **A BLOCK is the system protecting you — resolve
the blocker; never work around it.**

### Step 5 — Activate the canonical portfolio

```bash
python -m svyable.strategy_activate --out outputs
```

Only *after* a guard PASS does this promote the chosen candidate into the one
canonical `weights_today.csv` and update `state.json`. Real result: action
`hold`, canonical strategy `q23_concentrated`, source `agent`. The agent never
writes weights or quantities — activation does, from the validated choice only.

### Step 6 — Operate: drift, quotes, preflight, audit

Move to **🏦 Portfolio Ops** (and **🧠 Command Center** for readiness/ledger).
Here you check quote sanity, position drift vs. canonical target, stale-input
and liquidity gates, preflight, and — only through the explicit sandbox-first
workflow — reconciliation and audit. Everything downstream consumes **only**
activated canonical artifacts.

---

## The eight-point checklist (print this)

1. Build the board — `strategy_daily --evaluate-only`.
2. Open **Selection Meta Harness**.
3. Confirm decision readiness is **PASS**.
4. Review regime proxy, decision tree, blocked candidates, counterfactuals, and
   weight provenance.
5. Approve / write `agent_decision.json` — allowed `candidate_id` + matching hash.
6. Run the guard; resolve any **BLOCK** before continuing.
7. Activate canonical weights.
8. Use **Portfolio Ops** for quotes, drift, preflight, sandbox, reconciliation,
   audit.

## Installed-script equivalents

```bash
svyable-strategy-daily --evaluate-only     # step 1
svyable-agent-pack     --out outputs       # step 2
svyable-agent-guard    --out outputs --write   # step 4
svyable-strategy-activate --out outputs    # step 5
```

The guard exits `0` on PASS and `2` on BLOCK, so it composes safely in a script:
`svyable-agent-guard --out outputs && svyable-strategy-activate --out outputs`
will only activate when the guard passes.

## Freshness pre-checks (30 seconds before you trust the board)

The rails assume you are looking at *today's* board. Confirm it:

- **Command Center header** shows `Board: N/M candidates`. If it warns the board
  is incomplete, re-run step 1 before deciding — a partial board is not a menu.
- **Memo `Board date` and `Candidate hash`** must match the `as_of` /
  `candidate_set_hash` you put in the decision artifact. A mismatch is the #1
  cause of a guard BLOCK.
- **`Decision readiness: PASS`** in the memo. If it says BLOCK, the context
  itself isn't activation-ready — fix that before writing a decision.

## When the guard says BLOCK — and how to fix it

A BLOCK is the system doing its job. Each blocker string maps to a specific,
fixable cause. These are the **actual** messages the guard emits:

| Blocker message | What happened | Fix |
| --- | --- | --- |
| `missing file: …agent_decision.json` | No decision written yet | Write/approve the decision artifact (step 3) |
| `missing file: …latest_agent_context.json` | Context pack not generated | Re-run the harness (step 2) |
| `malformed json` / `json root must be object` | Decision file has a syntax error | Fix the JSON; it must be a single object |
| `decision missing required fields: …` | Artifact is missing a key | Include exactly `as_of, candidate_set_hash, candidate_id, confidence, reason` |
| `context decision_readiness is not PASS` | The board/context isn't activation-ready (stale artifacts, no legal candidates) | Read the listed issues; often re-run step 1 for a fresh board |
| `decision as_of does not match latest context` | You're deciding against yesterday's board | Copy `as_of` from **today's** memo |
| `decision candidate_set_hash does not match latest context` | Stale/typo'd hash | Copy the hash from today's memo exactly |
| `decision candidate_id is not in allowed_candidate_ids` | You picked a blocked candidate (hold-locked, cadence not due, ineligible) | Choose from the memo's **Allowed candidate IDs**; usually `hold_current` |
| `confidence must be numeric` / `must be between 0 and 1` | Bad confidence value | Use a number in `[0, 1]` |
| `decision reason is too short` | Reason under 10 characters | Write a substantive, artifact-derived rationale |
| `focus execution inputs are stale` | Prices/ADV behind the board date | Refresh inputs (re-run step 1); don't activate on stale data |
| `focus execution artifact is missing required columns` | Operating inputs incomplete | Regenerate the candidate's artifacts before activating |

Warnings (not blockers, but read them): `low confidence decision; human PM
should review carefully` (confidence < 0.25) and `candidate is allowed but not
present in truncated context candidate table`.

**Never** work around a BLOCK by editing artifacts to satisfy the check. Fix the
underlying cause.

## Glossary — reading the board and memo

| Term | Meaning |
| --- | --- |
| **candidate** | A complete, audited portfolio option (a strategy or the `hold_current` no-trade baseline) |
| **candidate_set_hash** | Fingerprint of today's exact board; ties a decision to one immutable menu |
| **eligible** | Passed all selector gates (see below); only eligible candidates are allowed choices |
| **expected_alpha_bps** | Modeled gross edge, in basis points, before costs |
| **estimated_cost_bps** | Modeled trading cost to move into the candidate |
| **utility_bps** | `expected_alpha − cost − turnover_penalty − risk_penalty`; the real ranking number |
| **one_way_turnover** | Fraction of the book that would trade to adopt the candidate |
| **hold_lock** | Minimum-hold-days gate; blocks switching out of a recently adopted book |
| **cadence_due** | Whether the candidate's rebalance interval has elapsed |
| **kill_switch** | Own-book risk cutout (drawdown/volatility/turbulence) |
| **regime proxy** | Visible market-state estimate: `risk_on`, `risk_off`, `chop`, `ops_stress` — context, not a command |
| **weight provenance** | Where the deterministic target weights were read from, plus gross/net/effective-N |
| **counterfactual** | What an alternative candidate would have gained/lost, and why it was blocked |

## First week: practice in the sandbox

1. **Days 1–2 — read only.** Run steps 1–2 and just *read* the memo and Meta
   Harness. Learn to predict the readiness verdict before you scroll to it.
2. **Days 3–4 — decide and guard, don't activate.** Write decisions, run the
   guard, and deliberately trigger each BLOCK (wrong hash, blocked candidate,
   short reason) so the failure modes are familiar, not scary.
3. **Day 5 — full loop in sandbox.** Activate, then work Portfolio Ops: quote
   sanity, drift, preflight. Confirm the sidebar reads **SANDBOX / TEST MODE**
   before every operating action.

Only move toward production once the sandbox loop is second nature — and even
then, submission stays gated behind typed confirmation.

## Mental model to leave the PM with

- The engine builds an **immutable menu**; you pick, a **guard** checks, then the
  system **activates** — in that order, every day.
- **"Hold" is a valid, common, and often correct outcome.** Highest alpha ≠ best
  trade once costs, turnover, and risk are charged.
- The regime proxy, decision tree, and counterfactuals are there to be
  **questioned** — they explain the choice, they don't command it.
- If something looks wrong, a **BLOCK** or a failed preflight is the system
  working. Fix the input; don't bypass the rail.
- Improvements go to **tomorrow's dev loop**, never today's activation cycle.
