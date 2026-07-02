"""End-to-end pipeline: Panel -> weights + artifacts (strategy.md §7 steps 1-4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from svyable.panel import Panel
from svyable.config import SvyableConfig
from svyable import factors as flib
from svyable.sleeves import build_ensemble, SleeveResult
from svyable.construct import build_unit_weights, ConstructResult
from svyable.risk import apply_risk_budget, backtest_pnl, RiskResult
from svyable.ml import ml_sleeve_score
from svyable.metrics import perf_summary, deflated_sharpe
from svyable.artifacts import ArtifactWriter, morning_report


@dataclass
class RunResult:
    weights: pd.DataFrame        # final scaled target weights (time x asset)
    budget: pd.Series
    pnl: pd.DataFrame
    ensemble: SleeveResult
    construct: ConstructResult
    risk: RiskResult
    tag: str
    output_dir: Path | None


def run_pipeline(panel: Panel, cfg: SvyableConfig, *,
                 output_root: str | Path | None = None,
                 tag: str | None = None,
                 write_artifacts: bool = True) -> RunResult:
    data_report = panel.validate()

    # ML sleeve (optional, plugs into the ensemble as one more sleeve)
    extra = {}
    if cfg.ml_enabled:
        F_for_ml = flib.compute_all(panel, cfg)
        ml_score = ml_sleeve_score(F_for_ml, panel, cfg)
        if ml_score is not None:
            extra["ml"] = ml_score

    ens = build_ensemble(panel, cfg, extra_sleeve_scores=extra)

    liq = panel.liquidity_mask(cfg.min_adv, cfg.min_price, cfg.adv_win)
    con = build_unit_weights(ens.score, panel.ret, liq, cfg)

    rk = apply_risk_budget(con.unit_weights, panel.ret, panel.market_ret,
                           ens.stress, cfg)
    pnl = backtest_pnl(rk.final_weights, panel.ret, cfg)

    use_tag = tag or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = None

    if write_artifacts and output_root is not None:
        aw = ArtifactWriter(output_root, cfg.strategy_id, use_tag)
        out_dir = aw.dir

        last = rk.final_weights.index[-1]
        w_today = rk.final_weights.loc[last]
        w_prev = rk.final_weights.iloc[-2] if len(rk.final_weights) > 1 else None

        aw.write_frame("weights_today", w_today[w_today > 0].rename("weight"))
        aw.write_frame("weights_history", rk.final_weights.iloc[-63:])
        aw.write_frame("budget", rk.budget.rename("budget"))
        aw.write_frame("sleeve_weights", ens.sleeve_weights)
        aw.write_frame("ic_health", ens.ic_health)
        aw.write_frame("pnl_diag", pnl)
        for name, fw in ens.factor_weights.items():
            aw.write_frame(f"factor_weights_{name}", fw.iloc[-21:])

        recent = perf_summary(pnl["net_ret"].iloc[-252:], benchmark=panel.market_ret.iloc[-252:])
        report = morning_report(
            strategy_id=cfg.strategy_id, tag=use_tag,
            weights_today=w_today, weights_prev=w_prev,
            budget=float(rk.budget.iloc[-1]), seats=int(con.seats.iloc[-1]),
            sleeve_weights=ens.sleeve_weights.iloc[-1],
            ic_health=ens.ic_health.iloc[-1],
            stress=float(ens.stress.iloc[-1]),
            kill_switch=bool(rk.kill_switch.iloc[-1] > 0),
            data_report=data_report, perf_recent=recent,
            config_hash=cfg.config_hash(),
        )
        aw.write_report(report)

        aw.write_meta({
            "strategy_id": cfg.strategy_id,
            "version": cfg.version,
            "tag": use_tag,
            "run_timestamp": datetime.now().isoformat(),
            "config_hash": cfg.config_hash(),
            "config": cfg.to_dict(),
            "data": data_report,
            "panel_meta": panel.meta,
            "perf_1y_net": recent,
        })

    return RunResult(weights=rk.final_weights, budget=rk.budget, pnl=pnl,
                     ensemble=ens, construct=con, risk=rk,
                     tag=use_tag, output_dir=out_dir)


def backtest_report(result: RunResult, panel: Panel, cfg: SvyableConfig,
                    n_trials: int = 20) -> dict:
    net = result.pnl["net_ret"]
    return {
        "full_period": perf_summary(net, benchmark=panel.market_ret),
        "deflated_sharpe": deflated_sharpe(net, n_trials=n_trials),
        "avg_daily_turnover": round(float(result.pnl["turnover"].mean() / 2), 4),
        "tc_drag_annual": round(float(result.pnl["tc"].mean() * 252), 4),
        "avg_gross": round(float(result.pnl["gross_exposure"].mean()), 3),
        "no_trade_band_held_frac": round(float(result.construct.held_days.mean()), 3),
        "kill_switch_days": int(result.risk.kill_switch.sum()),
        "config_hash": cfg.config_hash(),
    }
