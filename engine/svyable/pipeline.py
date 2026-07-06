"""End-to-end pipeline: Panel -> weights + reproducible PM artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from svyable import factor_library as flib
from svyable.artifacts import ArtifactWriter, morning_report
from svyable.cold_start import cold_start_adjustment, latest_diagnostics
from svyable.config import SvyableConfig
from svyable.construct import ConstructResult, build_unit_weights
from svyable.metrics import deflated_sharpe, perf_summary
from svyable.ml import ml_sleeve_score
from svyable.panel import Panel
from svyable.risk import RiskResult, apply_risk_budget, backtest_pnl
from svyable.sleeves import SleeveResult, build_ensemble


@dataclass
class RunResult:
    weights: pd.DataFrame
    budget: pd.Series
    pnl: pd.DataFrame
    ensemble: SleeveResult
    construct: ConstructResult
    risk: RiskResult
    tag: str
    output_dir: Path | None
    factor_names: tuple[str, ...]


def run_pipeline(
    panel: Panel,
    cfg: SvyableConfig,
    *,
    output_root: str | Path | None = None,
    tag: str | None = None,
    write_artifacts: bool = True,
    factor_names: list[str] | tuple[str, ...] | None = None,
    precomputed_factors: dict[str, pd.DataFrame] | None = None,
    run_context: dict[str, Any] | None = None,
) -> RunResult:
    data_report = panel.validate()
    selected_factors = tuple(
        factor_names or sorted(flib.factor_metadata().index)
    )

    if precomputed_factors is None:
        factors = flib.compute_all(panel, cfg, names=list(selected_factors))
    else:
        missing = [
            name for name in selected_factors
            if name not in precomputed_factors
        ]
        if missing:
            raise ValueError(
                "Precomputed factor cache is missing: " + ", ".join(missing)
            )
        factors = {
            name: precomputed_factors[name]
            for name in selected_factors
        }
    catalog = flib.factor_metadata(factors)

    extra = {}
    if cfg.ml_enabled:
        ml_score = ml_sleeve_score(factors, panel, cfg)
        if ml_score is not None:
            extra["ml"] = ml_score

    ensemble = build_ensemble(
        panel,
        cfg,
        extra_sleeve_scores=extra,
        factors=factors,
    )
    cold_start = cold_start_adjustment(panel, factors, cfg) if cfg.cold_start_enabled else None
    model_score = ensemble.score
    max_pos_mult = None
    if cold_start is not None:
        model_score = model_score * cold_start.score_multiplier
        max_pos_mult = cold_start.max_pos_multiplier

    liquidity = panel.liquidity_mask(
        cfg.min_adv,
        cfg.min_price,
        cfg.adv_win,
    )
    construction = build_unit_weights(
        model_score,
        panel.ret,
        liquidity,
        cfg,
        max_pos_mult=max_pos_mult,
    )
    risk = apply_risk_budget(
        construction.unit_weights,
        panel.ret,
        panel.market_ret,
        ensemble.stress,
        cfg,
    )
    pnl = backtest_pnl(risk.final_weights, panel.ret, cfg)
    pnl["benchmark_ret"] = panel.market_ret.reindex(pnl.index)

    use_tag = tag or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = None

    if write_artifacts and output_root is not None:
        writer = ArtifactWriter(output_root, cfg.strategy_id, use_tag)
        output_dir = writer.dir

        last = risk.final_weights.index[-1]
        weights_today = risk.final_weights.loc[last]
        weights_previous = (
            risk.final_weights.iloc[-2]
            if len(risk.final_weights) > 1
            else None
        )
        prices_today = panel.close.loc[last].dropna().rename("price")
        adv_today = panel.adv(cfg.adv_win).loc[last].dropna().rename(
            "adv_dollars"
        )
        liquid_today = (
            liquidity.loc[last]
            .fillna(False)
            .astype(bool)
            .rename("is_liquid")
        )
        execution_inputs = pd.concat(
            [prices_today, adv_today, liquid_today],
            axis=1,
        ).sort_index()

        writer.write_frame(
            "weights_today",
            weights_today[weights_today > 0].rename("weight"),
        )
        writer.write_frame("weights_history", risk.final_weights.iloc[-63:])
        writer.write_frame("budget", risk.budget.rename("budget"))
        writer.write_frame("sleeve_weights", ensemble.sleeve_weights)
        writer.write_frame("sleeve_health", ensemble.sleeve_health)
        writer.write_frame("ic_health", ensemble.ic_health)
        writer.write_frame("factor_catalog", catalog)
        writer.write_frame("pnl_diag", pnl)
        writer.write_frame("execution_inputs", execution_inputs)
        cold_start_diag = None
        if cold_start is not None:
            cold_start_diag = latest_diagnostics(cold_start, last)
            writer.write_frame("cold_start_diagnostics", cold_start_diag)
        if risk.regime is not None:
            writer.write_frame("regime", risk.regime.iloc[-504:])
        for name, factor_weights in ensemble.factor_weights.items():
            writer.write_frame(
                f"factor_weights_{name}",
                factor_weights.iloc[-21:],
            )
        for name, health in ensemble.factor_health.items():
            writer.write_frame(f"factor_health_{name}", health)

        recent = perf_summary(
            pnl["net_ret"].iloc[-252:],
            benchmark=panel.market_ret.iloc[-252:],
        )
        writer.write_frame(
            "institutional_metrics",
            pd.Series(recent, name="value"),
        )
        report = morning_report(
            strategy_id=cfg.strategy_id,
            tag=use_tag,
            weights_today=weights_today,
            weights_prev=weights_previous,
            budget=float(risk.budget.iloc[-1]),
            seats=int(construction.seats.iloc[-1]),
            sleeve_weights=ensemble.sleeve_weights.iloc[-1],
            ic_health=ensemble.ic_health.iloc[-1],
            stress=float(ensemble.stress.iloc[-1]),
            kill_switch=bool(risk.kill_switch.iloc[-1] > 0),
            data_report=data_report,
            perf_recent=recent,
            config_hash=cfg.config_hash(),
        )
        writer.write_report(report)

        stages = catalog["stage"].value_counts().to_dict()
        regime_columns = [
            "turb_pct",
            "absorption",
            "breadth",
            "panic_signal",
            "regime_risk",
            "throttle",
            "risk_on_signal",
            "boost",
            "regime_ready",
            "multiplier",
        ]
        cold_start_summary = None
        if cold_start_diag is not None and len(cold_start_diag):
            cold = cold_start_diag[cold_start_diag["is_cold_start"]]
            cold_start_summary = {
                "enabled": True,
                "min_trading_days": cfg.cold_start_min_trading_days,
                "full_trading_days": cfg.cold_start_full_trading_days,
                "min_factor_coverage": cfg.cold_start_min_factor_coverage,
                "cold_start_count": int(len(cold)),
                "eligible_cold_start_count": int(cold["eligible_by_cold_start"].sum()),
                "held_cold_start_count": int(
                    weights_today.reindex(cold.index).fillna(0.0).gt(0.0).sum()
                ),
            }
        elif cfg.cold_start_enabled:
            cold_start_summary = {"enabled": True, "cold_start_count": 0}
        else:
            cold_start_summary = {"enabled": False}

        writer.write_meta(
            {
                "strategy_id": cfg.strategy_id,
                "version": cfg.version,
                "tag": use_tag,
                "run_timestamp": datetime.now().isoformat(),
                "config_hash": cfg.config_hash(),
                "config": cfg.to_dict(),
                "run_context": run_context or {},
                "data": data_report,
                "panel_meta": panel.meta,
                "perf_1y_net": recent,
                "factor_library": {
                    "count": len(catalog),
                    "names": list(selected_factors),
                    "proven": int(stages.get("proven", 0)),
                    "shadow": int(stages.get("shadow", 0)),
                    "missing_values_preserved_for_ic": True,
                    "available_signal_score_normalization": True,
                    "tradable_universe_ic": True,
                    "precomputed_cache": precomputed_factors is not None,
                },
                "cold_start": cold_start_summary,
                "regime": (
                    {
                        column: (
                            round(
                                float(
                                    risk.regime[column]
                                    .dropna()
                                    .iloc[-1]
                                ),
                                4,
                            )
                            if column in risk.regime
                            and risk.regime[column].notna().any()
                            else None
                        )
                        for column in regime_columns
                    }
                    if risk.regime is not None
                    else None
                ),
                "execution_inputs": {
                    "date": str(
                        last.date() if hasattr(last, "date") else last
                    ),
                    "price_count": int(
                        execution_inputs["price"].notna().sum()
                    ),
                    "adv_count": int(
                        execution_inputs["adv_dollars"].notna().sum()
                    ),
                    "liquid_count": int(
                        execution_inputs["is_liquid"].fillna(False).sum()
                    ),
                    "adv_window": cfg.adv_win,
                    "adv_participation_cap": cfg.adv_participation_cap,
                },
            }
        )

    return RunResult(
        weights=risk.final_weights,
        budget=risk.budget,
        pnl=pnl,
        ensemble=ensemble,
        construct=construction,
        risk=risk,
        tag=use_tag,
        output_dir=output_dir,
        factor_names=selected_factors,
    )
