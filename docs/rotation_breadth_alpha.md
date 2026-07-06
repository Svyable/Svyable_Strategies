# Svyable Rotation Breadth research note

This note documents the Rotation Breadth factor family and first strategy mandate. It is research infrastructure, not a live-capital performance claim.

## Gap identified

The current new alpha books cover fast tape bursts, residual catalysts, durable leadership, and downside resilience. The missing offensive sleeve was early leadership rotation: names whose relative rank, volume sponsorship, and reclaim behavior improve before they become obvious absolute-momentum leaders.

## New factors

| Factor | Sleeve | Idea |
| --- | --- | --- |
| `relative_momentum_spread` | momentum | Medium-horizon momentum ranked versus the current cross-section. |
| `rank_improvement_velocity` | momentum | Acceleration in relative rank over the last month. |
| `relative_volume_sponsorship` | liquidity | Improving dollar-volume sponsorship versus the cross-section. |
| `breadth_thrust_participation` | momentum | Own-name participation when broad single-name breadth is expanding. |
| `leader_pullback_accumulation` | momentum | Relative-strength leader pulling back quietly with constructive closes. |
| `weak_breadth_relative_reclaim` | resilience | Single-name reclaim behavior during weak breadth. |

## Strategy mandate

`svyable_rotation_breadth` combines the six Rotation Breadth factors with Tape Acceleration, Alpha Catalyst, Leadership Quality, residual alpha, institutional trend, resilience, liquidity, and idiosyncratic-risk controls.

The mandate is built for early leadership rotation:

- no ML sleeve;
- blended seat weighting;
- 20 base seats, 16 minimum, 28 maximum;
- 8.5% max position;
- 27% cluster cap;
- 3.4% no-trade band;
- 15.5% target volatility;
- 9.2% stressed target volatility;
- 4.2 bps cost assumption;
- 3-day minimum hold.

## Why this fills a useful gap

Tape Acceleration finds fast tape bursts. Alpha Catalyst finds beta-stripped residual catalysts. Leadership Quality finds steadier durable leaders. Downside Resilience gives the selector a defensive book. Rotation Breadth adds a cross-sectional lens that can detect improving relative leaders before the absolute-trend books fully agree.

## Promotion path

1. Run as a normal strategy candidate.
2. Compare candidate-board utility, turnover, and overlap against Leadership Quality and Tape Acceleration.
3. Watch whether rank-improvement and volume-sponsorship factors improve candidate selection without simply duplicating existing momentum.
4. Keep the new factors shadow/incubation until purged IC and candidate behavior justify promotion.
