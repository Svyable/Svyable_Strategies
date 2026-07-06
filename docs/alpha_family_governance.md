# Alpha-family governance guide

Svyable now has five new alpha-family books:

1. `svyable_tape_acceleration` for short-to-medium horizon tape bursts.
2. `svyable_alpha_catalyst` for residual acceleration, absorption, and volatility-transition catalysts.
3. `svyable_leadership_quality` for slower, more durable residual leadership and quiet accumulation.
4. `svyable_downside_resilience` for defensive residual alpha during weak or turbulent markets.
5. `svyable_rotation_breadth` for early cross-sectional leadership rotation and breadth participation.

The purpose of alpha-family governance is to keep those books visible without treating early research factors as proven. The governance layer is read-only and does not create portfolios, write decisions, or touch operations.

## What the report answers

The alpha-family report answers four PM questions:

- Which newest factor families exist?
- Which factors belong to each family?
- Which strategies use the newest family factors?
- How much of each strategy still depends on shadow factors?

## Commands

Render JSON:

```bash
svyable-alpha-family
```

Render Markdown:

```bash
svyable-alpha-family --format markdown
```

Persist both JSON and Markdown:

```bash
svyable-alpha-family --write --out outputs
```

The persisted files are:

- `outputs/governance/latest_alpha_family_governance.json`
- `outputs/governance/latest_alpha_family_governance.md`

## Dashboard adapters

`alpha_family_frames.py` converts the governance report into DataFrames for Streamlit and notebooks:

- `strategies`
- `factors`
- `stage_counts`
- `stage_matrix`

It also exposes compact metric rows for review cards.

## Review posture

A shadow-heavy strategy is not bad by itself. It means the strategy is still in research/incubation and should be compared by candidate-board utility, turnover, factor health, redundancy, and diagnostics before being trusted with more weight.

The PM should compare the five books by role rather than treating them as interchangeable:

- Tape Acceleration: fast tape bursts.
- Alpha Catalyst: beta-stripped residual catalyst pressure.
- Leadership Quality: durable participation and quiet accumulation.
- Downside Resilience: defensive candidate for difficult regimes.
- Rotation Breadth: early relative-rank and breadth participation.
