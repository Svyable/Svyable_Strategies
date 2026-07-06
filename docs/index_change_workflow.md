# Index-change workflow

This is the lightweight harness for events such as `SPCX` joining the Nasdaq-100.

## Goal

Keep universe changes simple, SOLID, repeatable, and auditable:

1. **Official source in, deterministic universe out.**
2. **Events are data, not code.**
3. **Future events can be staged early but remain pending until effective.**
4. **Daily runs always record the universe file they actually used.**

## Inputs

### `engine/universe_nasdaq_seed.txt`

Current liquid NASDAQ seed list. It is intentionally honest about its caveat:
deep historical tests using only this file remain survivorship-biased.

### `engine/universe_index_events.csv`

Append-only constituent event ledger.

Required columns:

```csv
effective_date,index,action,symbol,source,note
```

Rules:

- `action` is `add` or `remove`.
- `symbol` is normalized to uppercase.
- `index` is normalized, so `NASDAQ-100` and `NASDAQ100` resolve to the same key.
- Same-day conflicting actions for the same symbol are rejected.
- Rows dated after the run's `as_of` date are reported as `pending` and not applied.

## Daily materialization

The scheduled wrapper runs:

```bash
python -m svyable.universe \
  --seed universe_nasdaq_seed.txt \
  --events universe_index_events.csv \
  --out outputs/universe/effective_universe.txt \
  --as-of "$(date +%F)"
```

Then `python -m svyable.strategy_daily` receives:

```bash
--universe outputs/universe/effective_universe.txt
```

This keeps the strategy selector and providers unchanged: they still consume a
plain one-symbol-per-line universe file.

## SPCX case

Nasdaq announced that Space Exploration Technologies Corporation (`SPCX`) becomes
a Nasdaq-100 component before market open on 2026-07-07. The repo captures that
as:

```csv
2026-07-07,NASDAQ100,add,SPCX,<official Nasdaq source>,Space Exploration Technologies Corporation enters Nasdaq-100 before market open
```

Behavior:

- As of 2026-07-06: `SPCX` is staged but pending.
- As of 2026-07-07 and later: `SPCX` is included in the effective model universe.
- Re-running materialization is idempotent.

## Operator checklist

1. Add the event row with the official source.
2. Run `pytest engine/tests/test_universe_index_changes.py`.
3. Run the materializer for the effective date if a dry run is needed:
   `SVYABLE_UNIVERSE_AS_OF=2026-07-07 ops/run_daily.sh`.
4. Review `outputs/universe/effective_universe.txt` and the materializer JSON
   in the daily log.
5. Let the normal strategy selection, activation, and execution guardrails handle
   downstream portfolio changes.
