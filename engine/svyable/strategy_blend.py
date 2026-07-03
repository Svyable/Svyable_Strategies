"""Causal, bounded blends of registered strategy portfolios."""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
import numpy as np
import pandas as pd
from svyable.config import SvyableConfig, nasdaq_lo_config
from svyable.metrics import perf_summary
from svyable.panel import EPS, Panel
from svyable.pipeline import RunResult
from svyable.risk import backtest_pnl
from svyable.strategy_registry import get_strategy

ANN = 252.0

@dataclass(frozen=True)
class BlendSpec:
    blend_id: str
    display_name: str
    description: str
    components: tuple[tuple[str, float], ...]
    method: str = "fixed"
    rebalance_interval_days: int = 1
    minimum_hold_days: int = 3
    maturity: str = "production_candidate"
    enabled_by_default: bool = True
    allocation_window: int = 126
    allocation_min_history: int = 42
    allocation_smooth_alpha: float = .25
    component_min_weight: float = .05
    component_max_weight: float = .60
    alpha_tilt: float = .35

    @property
    def strategy_id(self): return self.blend_id
    @property
    def family(self): return "chimera blend"
    @property
    def factor_names(self):
        return tuple(sorted({f for sid, _ in self.components for f in get_strategy(sid).factor_names}))
    def component_ids(self): return tuple(sid for sid, _ in self.components)
    def fixed_weights(self):
        w = pd.Series(dict(self.components), dtype=float)
        return w / w.sum()
    def build_config(self, base: SvyableConfig | None = None):
        from dataclasses import replace
        cfg, w = base or nasdaq_lo_config(), self.fixed_weights()
        configs = {sid: get_strategy(sid).build_config() for sid in w.index}
        avg = lambda key: float(sum(w[sid] * getattr(configs[sid], key) for sid in w.index))
        return replace(cfg, strategy_id=f"candidate_{self.blend_id}", ml_enabled=False,
                       tc_bps=avg("tc_bps"), no_trade_band=avg("no_trade_band"),
                       target_vol=avg("target_vol"))
    def validate(self):
        if not self.blend_id.startswith("chimera_"): raise ValueError("blend id must start chimera_")
        if not 2 <= len(self.components) <= 4: raise ValueError("blend needs 2-4 components")
        ids = [sid for sid, _ in self.components]
        if len(ids) != len(set(ids)): raise ValueError("duplicate component")
        for sid, weight in self.components:
            get_strategy(sid)
            if weight <= 0: raise ValueError("component weight must be positive")
        if self.method not in {"fixed", "inverse_vol", "alpha_risk"}: raise ValueError("unknown method")
        if self.method == "fixed" and abs(sum(dict(self.components).values()) - 1) > 1e-6:
            raise ValueError("fixed weights must sum to one")
        n = len(ids)
        if not 0 <= self.component_min_weight < self.component_max_weight <= 1:
            raise ValueError("invalid bounds")
        if self.component_min_weight*n > 1 or self.component_max_weight*n < 1:
            raise ValueError("infeasible bounds")

_REGISTRY: dict[str, BlendSpec] = {}
def register_blend(spec):
    spec.validate()
    if spec.blend_id in _REGISTRY: raise ValueError("duplicate blend")
    _REGISTRY[spec.blend_id] = spec
    return spec

def _defaults():
    return [
        BlendSpec("chimera_flagship_shield","Flagship + Shield","Conviction plus defense",(("q23_concentrated",.7),("q23_defensive_alpha",.3)),minimum_hold_days=5),
        BlendSpec("chimera_trend_reversion","Trend x Reversion","Horizon diversification",(("q23_momentum_quality",.5),("q23_ou_mean_reversion",.5))),
        BlendSpec("chimera_all_weather","All-Weather","Hybrid, defense and capacity",(("q23_hybrid_alpha",.4),("q23_defensive_alpha",.3),("q23_low_turnover",.3)),minimum_hold_days=5),
        BlendSpec("chimera_adaptive","Adaptive Risk Parity","Causal inverse-vol blend",(("q23_concentrated",.25),("q23_momentum_quality",.25),("q23_ou_mean_reversion",.25),("q23_defensive_alpha",.25)),method="inverse_vol",component_min_weight=.1,component_max_weight=.5),
        BlendSpec("chimera_institutional_alpha","Institutional Alpha","Beta capture, managed momentum, residual and defense",(("q23_alpha_beta",.25),("q23_crash_resilient_momentum",.25),("q23_residual_alpha",.25),("q23_defensive_alpha",.25)),method="alpha_risk",minimum_hold_days=4,component_min_weight=.08,component_max_weight=.5,alpha_tilt=.4),
        BlendSpec("chimera_opportunity_stack","Opportunity Stack","Conviction, dispersion, reversal and capacity",(("q23_concentrated",.25),("q23_dispersion_alpha",.25),("q23_ou_mean_reversion",.25),("q23_low_turnover",.25)),method="alpha_risk",component_min_weight=.08,component_max_weight=.5,alpha_tilt=.3),
    ]
for _spec in _defaults(): register_blend(_spec)

def get_blend(blend_id):
    if blend_id not in _REGISTRY: raise KeyError(f"unknown blend {blend_id}")
    return _REGISTRY[blend_id]
def list_blends(): return list(_REGISTRY.values())
def default_blend_ids(): return [s.blend_id for s in _REGISTRY.values() if s.enabled_by_default]

def blend_spec_from_dict(payload: Mapping[str, Any]):
    raw = payload.get("components", {})
    components = tuple((str(k),float(v)) for k,v in (sorted(raw.items()) if isinstance(raw,Mapping) else raw))
    spec = BlendSpec(str(payload["blend_id"]),str(payload.get("display_name",payload["blend_id"])),
        str(payload.get("description","User-defined chimera")),components,str(payload.get("method","fixed")),
        int(payload.get("rebalance_interval_days",1)),int(payload.get("minimum_hold_days",3)),"user_defined",True,
        int(payload.get("allocation_window",126)),int(payload.get("allocation_min_history",42)),
        float(payload.get("allocation_smooth_alpha",.25)),float(payload.get("component_min_weight",.05)),
        float(payload.get("component_max_weight",.6)),float(payload.get("alpha_tilt",.35)))
    spec.validate(); return spec

def blend_frame():
    return pd.DataFrame([{"blend_id":s.blend_id,"name":s.display_name,"method":s.method,
        "components":json.dumps(dict(s.components)),"allocation_window":s.allocation_window,
        "component_bounds":f"{s.component_min_weight:.0%}-{s.component_max_weight:.0%}",
        "minimum_hold_days":s.minimum_hold_days,"rebalance_interval_days":s.rebalance_interval_days,
        "enabled_by_default":s.enabled_by_default,"description":s.description} for s in _REGISTRY.values()]).set_index("blend_id")

def _project(raw, spec):
    w = raw.replace([np.inf,-np.inf],np.nan).fillna(0).clip(lower=0)
    w = spec.fixed_weights().reindex(raw.index) if w.sum() <= EPS else w/w.sum()
    lo, hi = spec.component_min_weight, spec.component_max_weight
    for _ in range(4*len(w)):
        w = w.clip(lo,hi); residual = 1-float(w.sum())
        if abs(residual) < 1e-12: break
        capacity = (hi-w).clip(lower=0) if residual > 0 else (w-lo).clip(lower=0)
        free = capacity > 1e-12
        if not free.any(): break
        w.loc[free] += residual*capacity.loc[free]/capacity.loc[free].sum()
    w = w.clip(lo,hi); return w/w.sum()

def resolve_component_weight_history(spec, results):
    returns = pd.DataFrame({sid:results[sid].pnl["net_ret"] for sid in spec.component_ids()}).sort_index()
    fixed, history = spec.fixed_weights().reindex(returns.columns), pd.DataFrame(index=returns.index,columns=returns.columns,dtype=float)
    if spec.method == "fixed": history.loc[:,:] = fixed.to_numpy(); return history
    lagged = returns.shift(1)
    vol = lagged.rolling(spec.allocation_window,min_periods=spec.allocation_min_history).std()*np.sqrt(ANN)
    mean = lagged.ewm(halflife=max(10,spec.allocation_window//3),min_periods=spec.allocation_min_history,adjust=False).mean()*ANN
    previous = fixed.copy()
    for pos,timestamp in enumerate(returns.index):
        sigma = vol.loc[timestamp]
        if sigma.notna().sum() < len(returns.columns): target = fixed.copy()
        else:
            raw = 1/(sigma+EPS)
            if spec.method == "alpha_risk":
                sharpe = (mean.loc[timestamp]/(sigma+EPS)).clip(-2.5,2.5)
                sample = lagged.iloc[max(0,pos-spec.allocation_window):pos].dropna(how="all")
                diversify = pd.Series(1.,index=returns.columns)
                if len(sample) >= spec.allocation_min_history:
                    corr = sample.corr().abs(); avg = (corr.sum(axis=1)-1)/max(1,len(corr)-1)
                    diversify = 1/np.sqrt(.5+avg.clip(0,1))
                raw = raw*np.exp(spec.alpha_tilt*sharpe)*diversify
            target = _project(raw,spec)
        previous = _project(spec.allocation_smooth_alpha*target+(1-spec.allocation_smooth_alpha)*previous,spec)
        history.loc[timestamp] = previous
    return history.ffill().fillna(fixed)

def resolve_component_weights(spec,results): return resolve_component_weight_history(spec,results).iloc[-1]

class BlendRunResult:
    def __init__(self,**kwargs): self.__dict__.update(kwargs); self.ensemble=SimpleNamespace(score=kwargs["score"]); self.risk=SimpleNamespace(kill_switch=kwargs["kill_switch"])

def _scores(results,allocations):
    num=den=None
    for sid in allocations.columns:
        frame=results[sid].ensemble.score; present=frame.notna()
        part=frame.where(present,0).mul(allocations[sid],axis=0); mass=present.astype(float).mul(allocations[sid],axis=0)
        num=part if num is None else num.add(part,fill_value=0); den=mass if den is None else den.add(mass,fill_value=0)
    return num.div(den.replace(0,np.nan))

def build_blend_result(spec,component_weights,results,panel:Panel,*,tag):
    allocations = resolve_component_weight_history(spec,results).reindex(panel.close.index).ffill().reindex(columns=list(spec.component_ids()))
    blended=None
    for sid in allocations.columns:
        part=results[sid].weights.fillna(0).mul(allocations[sid],axis=0); blended=part if blended is None else blended.add(part,fill_value=0)
    blended=blended.fillna(0); pnl=backtest_pnl(blended,panel.ret,spec.build_config()); pnl["benchmark_ret"]=panel.market_ret.reindex(pnl.index)
    kill=pd.Series(0.,index=blended.index)
    for sid in allocations.columns: kill=np.maximum(kill,results[sid].risk.kill_switch.fillna(0).where(allocations[sid]>1e-6,0))
    return BlendRunResult(weights=blended,pnl=pnl,score=_scores(results,allocations),kill_switch=pd.Series(kill,index=blended.index),component_weights=allocations.iloc[-1],component_weight_history=allocations,component_dirs={sid:str(results[sid].output_dir or "") for sid in allocations.columns},tag=tag,output_dir=None)

def write_blend_artifacts(spec,result,panel,output_root,*,tag):
    cfg=spec.build_config(); directory=Path(output_root)/f"candidate_{spec.blend_id}"/tag; directory.mkdir(parents=True,exist_ok=True)
    last=result.weights.index[-1]; today=result.weights.loc[last]; today[today>1e-12].rename("weight").to_csv(directory/"weights_today.csv")
    result.weights.iloc[-63:].to_csv(directory/"weights_history.csv"); result.pnl.iloc[-252:].to_csv(directory/"pnl_diag.csv"); result.component_weight_history.iloc[-252:].to_csv(directory/"component_weights_history.csv")
    prices=panel.close.loc[last].dropna().rename("price"); adv=panel.adv(cfg.adv_win).loc[last].dropna().rename("adv_dollars"); liquid=panel.liquidity_mask(cfg.min_adv,cfg.min_price,cfg.adv_win).loc[last].fillna(False).astype(bool).rename("is_liquid")
    pd.concat([prices,adv,liquid],axis=1).sort_index().to_csv(directory/"execution_inputs.csv")
    metrics=perf_summary(result.pnl["net_ret"].iloc[-252:],panel.market_ret.iloc[-252:]); pd.Series(metrics,name="value").to_csv(directory/"institutional_metrics.csv")
    composition={sid:round(float(w),6) for sid,w in result.component_weights.items()}
    (directory/"meta.json").write_text(json.dumps({"strategy_id":f"candidate_{spec.blend_id}","blend_id":spec.blend_id,"kind":"chimera_blend","method":spec.method,"components":composition,"component_output_dirs":result.component_dirs,"allocation":{"window":spec.allocation_window,"minimum_history":spec.allocation_min_history,"smooth_alpha":spec.allocation_smooth_alpha,"minimum_weight":spec.component_min_weight,"maximum_weight":spec.component_max_weight,"alpha_tilt":spec.alpha_tilt,"causal_history":True},"perf_1y_net":metrics,"tag":tag,"run_timestamp":datetime.now().isoformat(),"config_hash":cfg.config_hash(),"config":cfg.to_dict()},indent=2,sort_keys=True,default=str))
    (directory/"morning_report.md").write_text(f"# Chimera blend — {spec.display_name}\n\n{spec.description}\n\n"+"\n".join(f"- {sid}: {w:.1%}" for sid,w in composition.items())+f"\n\nMethod: {spec.method}; causal historical allocation.\n")
    result.output_dir=directory; return directory
