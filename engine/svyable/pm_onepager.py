"""Portfolio-manager one-pager for a Svyable strategy run.

Renders a single self-contained markdown briefing from a completed
``RunResult`` — the active strategy identity, risk posture, regime stack, sleeve
allocation with live IC health, the factor stack that is switched on, the
construction knobs, the price-action Markov regime read, and the resulting
holdings. It exists so a human validating a run (or the codebase behind it) can
see *exactly what is active* on one page, with every number traceable to a real
pipeline field.

Determinism: the renderer emits no timestamps or environment detail, so on a
pinned synthetic panel the output is reproducible and safe to track as a
contract snapshot (``tests/golden_weights_human.md``). Risk/health/Markov values
are rounded for display to keep cross-BLAS float dust out of the diff; the
holdings table keeps full precision because it mirrors the CI weights contract.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from svyable import factor_library as flib
from svyable.markov_regime import MarkovRegime


def synthetic_ticker_aliases(symbols, universe_file: str | Path) -> dict[str, str]:
    """Deterministic display aliases for a synthetic universe.

    Maps ``SYN{i:03d}`` → the i-th real ticker in the NASDAQ seed universe (file
    order). These are *illustrative labels only* so a synthetic run reads with
    recognisable names; the underlying price paths are still synthetic. Real-data
    runs already carry real symbols and need no aliasing.
    """
    path = Path(universe_file)
    if not path.exists():
        return {}
    tickers = [ln.strip() for ln in path.read_text().splitlines()
               if ln.strip() and not ln.lstrip().startswith("#")]
    out: dict[str, str] = {}
    for sym in symbols:
        s = str(sym)
        if s.startswith("SYN") and s[3:].isdigit():
            idx = int(s[3:])
            if 0 <= idx < len(tickers):
                out[s] = tickers[idx]
    return out


def _last(series, default=float("nan")) -> float:
    try:
        s = pd.Series(series).dropna()
        return float(s.iloc[-1]) if len(s) else default
    except Exception:  # noqa: BLE001
        return default


def _f(x, nd=3) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "n/a"
    return "n/a" if not np.isfinite(v) else f"{v:.{nd}f}"


def _pct(x, nd=2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "n/a"
    return "n/a" if not np.isfinite(v) else f"{v * 100:.{nd}f}%"


def holdings_table(res, symbol_labels: dict[str, str] | None = None) -> pd.DataFrame:
    """Latest long book, ranked by weight (the tracked weights contract).

    When ``symbol_labels`` is given, a ``ticker`` column carries the display alias
    for each raw ``symbol`` (see :func:`synthetic_ticker_aliases`).
    """
    last = res.weights.index[-1]
    latest = res.weights.loc[last].dropna()
    latest = latest[latest > 0].sort_values(ascending=False)
    table = latest.rename("weight").reset_index().rename(columns={"index": "symbol"})
    table.insert(0, "rank", range(1, len(table) + 1))
    table["weight"] = table["weight"].astype(float).round(8)
    table["weight_pct"] = (table["weight"] * 100.0).round(4)
    cols = ["rank", "symbol", "weight", "weight_pct"]
    if symbol_labels:
        table["ticker"] = table["symbol"].map(lambda s: symbol_labels.get(s, s))
        cols = ["rank", "ticker", "symbol", "weight", "weight_pct"]
    return table[cols]


def _reproducibility(cfg, res, table, *, weights_hash, config_hash,
                     provider_repr, config_repr) -> list[str]:
    last = res.weights.index[-1]
    last_date = str(last.date() if hasattr(last, "date") else last)
    total_weight = float(table["weight"].sum()) if len(table) else 0.0
    return [
        "## 1 · Provenance & reproducibility contract",
        "",
        f"- strategy: `{cfg.strategy_id}` v`{cfg.version}`",
        f"- weights_hash: `{weights_hash}`  ·  config_hash: `{config_hash}`",
        f"- provider: `{provider_repr}`",
        f"- config: `{config_repr}`",
        f"- as-of (synthetic) date: `{last_date}`",
        f"- positions: `{len(table)}`  ·  gross book / total weight: "
        f"`{total_weight:.8f}`",
        f"- factor universe: `{len(res.factor_names)}` factors registered "
        "(see §7)",
        "",
        "> Not a live-capital recommendation. This is the deterministic CI "
        "behaviour contract for the pinned synthetic provider/configuration; the "
        "weights_hash is the hard regression gate.",
        "",
    ]


def _risk_posture(cfg, res) -> list[str]:
    budget = _last(res.budget)
    rvol = _last(getattr(res.risk, "realized_vol", None))
    overlay = _last(getattr(res.risk, "overlay", None))
    throttle = _last(getattr(res.risk, "throttle", None))
    kill = _last(getattr(res.risk, "kill_switch", None), 0.0)
    turnover = _last(getattr(res.construct, "turnover", None))
    seats = _last(getattr(res.construct, "seats", None))
    vol_use = "stressed" if (np.isfinite(rvol) and rvol > cfg.target_vol) else "normal"
    kill_state = "TRIPPED ⛔" if kill and kill > 0 else "armed (clear)"
    return [
        "## 3 · Risk posture (today)",
        "",
        "| Control | Value | Setting |",
        "| --- | ---: | --- |",
        f"| Gross book (leverage budget) | {_f(budget)} | "
        f"cap {_f(cfg.lev_cap)} / floor {_f(cfg.lev_min)} |",
        f"| Realized vol (EWMA, ann.) | {_pct(rvol)} | "
        f"target {_pct(cfg.target_vol)} · stressed {_pct(cfg.target_vol_stressed)} "
        f"→ regime: {vol_use} |",
        f"| Vol-overlay multiplier | {_f(overlay)} | "
        f"clip {cfg.overlay_clip} on {cfg.overlay_vol_win}d vol |",
        f"| Regime throttle | {_f(throttle)} | "
        f"risk-off floor {_f(cfg.risk_off_floor)} |",
        f"| Circuit breaker | {kill_state} | "
        f"trip {_pct(cfg.backtest_max_dd)} dd × {_f(cfg.kill_dd_mult)} → "
        f"lev {_f(cfg.kill_lev)} |",
        f"| Seats live / turnover | {int(seats) if np.isfinite(seats) else 'n/a'}"
        f" / {_pct(turnover)} | no-trade band {_pct(cfg.no_trade_band)} |",
        "",
    ]


def _regime_stack(cfg, res) -> list[str]:
    reg = getattr(res.risk, "regime", None)
    out = ["## 4 · Regime stack (causal turbulence / breadth / panic)", ""]
    toggles = (f"turbulence={'on' if cfg.turbulence_enabled else 'off'} "
               f"(win {cfg.turb_win}, on≥p{int(cfg.turb_on_pct * 100)}), "
               f"breadth (win {cfg.breadth_win}), "
               f"panic (vol z-on {_f(cfg.panic_vol_z_on, 1)} / "
               f"dd-on {_pct(cfg.panic_dd_on)})")
    out.append(f"- modules: {toggles}")
    if reg is None or not len(reg):
        out += ["- regime frame unavailable for this run.", ""]
        return out
    row = reg.iloc[-1]

    def g(col):
        return _f(row[col]) if col in reg.columns else "n/a"

    out += [
        "",
        "| Signal | Reading | Interpretation |",
        "| --- | ---: | --- |",
        f"| Turbulence percentile | {g('turb_pct')} | "
        f"structural dislocation vs {cfg.turb_rank_win}d |",
        f"| Breadth | {g('breadth')} | participation (low = narrow) |",
        f"| Absorption ratio | {g('absorption')} | "
        f"top-{int(cfg.absorption_top_frac * 100)}% eigenvalue crowding |",
        f"| Market drawdown | {g('market_drawdown')} | own-market peak-to-trough |",
        f"| Market vol (ann.) / z | {g('market_realized_vol')} / "
        f"{g('market_vol_z')} | panic vol gauge |",
        f"| Panic signal | {g('panic_signal')} | 0 = calm, 1 = full de-risk |",
        f"| **Net regime multiplier** | **{g('multiplier')}** | "
        f"whole-book exposure scalar (ready={g('regime_ready')}) |",
        "",
    ]
    return out


def _markov_section(mk: MarkovRegime) -> list[str]:
    if mk is None:
        return []
    labels = mk.labels
    edges = ", ".join(_f(e, 1) for e in mk.z_edges)
    out = [
        "## 5 · Price-action Markov regime (price path only)",
        "",
        "First-order Markov chain over vol-standardised daily market returns — "
        "*no factors, no fundamentals*. State = today's return in units of "
        f"trailing {mk.vol_win}d volatility, bucketed at z ∈ {{{edges}}}. "
        f"Estimated on {mk.n_obs} causal day-to-day transitions.",
        "",
        f"- **Current state: `{mk.current_label}`**  ·  "
        f"self-persistence `{_f(mk.persistence)}`  ·  "
        f"expected dwell `{_f(mk.expected_dwell, 1)}` trading days  ·  "
        f"next-step entropy `{_f(mk.entropy_bits, 2)}` bits",
        "- modal forward path (argmax each step): "
        + " → ".join([mk.current_label] + mk.modal_path_labels()),
        "",
        "**Most-likely state distribution, h days ahead (row = horizon; "
        "bold = modal):**",
        "",
        "| h | " + " | ".join(labels) + " |",
        "| ---: | " + " | ".join(["---:"] * len(labels)) + " |",
    ]
    for h in range(1, mk.horizon + 1):
        probs = mk.forecast[h]
        argmax = int(probs.argmax())
        cells = []
        for j, p in enumerate(probs):
            cell = _f(p, 3)
            cells.append(f"**{cell}**" if j == argmax else cell)
        out.append(f"| +{h} | " + " | ".join(cells) + " |")
    out += [
        "| _∞ (stationary)_ | "
        + " | ".join(f"_{_f(p, 3)}_" for p in mk.stationary) + " |",
        "",
        "**Empirical transition matrix P (row = from-state → col = to-state):**",
        "",
        "| from \\ to | " + " | ".join(labels) + " |",
        "| --- | " + " | ".join(["---:"] * len(labels)) + " |",
    ]
    for i, lab in enumerate(labels):
        marker = "→ " if i == mk.current_state else ""
        cells = " | ".join(_f(p, 3) for p in mk.transition[i])
        out.append(f"| {marker}**{lab}** | {cells} |")
    out.append("")
    return out


def _sleeve_section(cfg, res) -> list[str]:
    sw = res.ensemble.sleeve_weights
    health = getattr(res.ensemble, "sleeve_health", None)
    last = sw.iloc[-1] if len(sw) else pd.Series(dtype=float)
    spec = {s.name: s for s in cfg.sleeves}
    out = [
        "## 6 · Sleeve allocation & live IC health",
        "",
        "Sleeves are meta-learned by trailing information coefficient; an "
        "untrusted (shadow) sleeve is allowed to bleed to zero, a proven sleeve "
        "keeps an anti-collapse floor.",
        "",
        "| Sleeve | Live wt | IC-IR | Hit | mean-IC | Horizons | Stress prior | "
        "Trust |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for name, sp in spec.items():
        trust = "proven" if sp.proven else "shadow"
        horizons = "/".join(str(h) for h in sp.horizons)
        if name in getattr(last, "index", []):
            wt = _f(last.get(name), 4)
            hr = health.loc[name] if health is not None and name in health.index else None
            icir = _f(hr["ic_ir"]) if hr is not None else "n/a"
            hit = _pct(hr["hit_rate"]) if hr is not None else "n/a"
            mic = _f(hr["mean_ic"]) if hr is not None else "n/a"
            out.append(f"| {name} | {wt} | {icir} | {hit} | {mic} | {horizons} | "
                       f"{_f(sp.stress_mult, 2)} | {trust} |")
        else:
            state = "disabled (ml_enabled=False)" if name == "ml" else "inactive"
            out.append(f"| {name} | — | — | — | — | {horizons} | "
                       f"{_f(sp.stress_mult, 2)} | {trust} · {state} |")
    out.append("")
    return out


def _factor_section(cfg, res, *, top_n: int = 8) -> list[str]:
    meta = flib.factor_metadata()
    active = [f for f in res.factor_names if f in meta.index]
    sub = meta.loc[active]
    proven = int((sub["stage"] == "proven").sum()) if "stage" in sub.columns else 0
    shadow = len(sub) - proven
    out = [
        "## 7 · Factor stack (what is switched on)",
        "",
        f"- **{len(active)}** factors active — **{proven} proven** "
        f"(guaranteed floor {_pct(cfg.factor_min_weight)}) + **{shadow} shadow** "
        "(no floor; earn weight via IC or decay out).",
    ]
    if "sleeve" in sub.columns and "stage" in sub.columns:
        tab = pd.crosstab(sub["sleeve"], sub["stage"])
        cols = [c for c in ("proven", "shadow") if c in tab.columns]
        out += ["", "| Sleeve | " + " | ".join(c.capitalize() for c in cols)
                + " | Total |", "| --- | " + " | ".join(["---:"] * len(cols))
                + " | ---: |"]
        for sleeve, r in tab.iterrows():
            vals = " | ".join(str(int(r[c])) for c in cols)
            out.append(f"| {sleeve} | {vals} | {int(r[cols].sum())} |")

    # Top live factors inside the dominant sleeve today.
    sw = res.ensemble.sleeve_weights
    fw = getattr(res.ensemble, "factor_weights", {}) or {}
    if len(sw) and fw:
        dom = str(sw.iloc[-1].astype(float).idxmax())
        if dom in fw and len(fw[dom]):
            row = fw[dom].iloc[-1].dropna()
            top = row.reindex(row.abs().sort_values(ascending=False).index).head(top_n)
            out += ["", f"**Top {min(top_n, len(top))} factors driving the "
                    f"dominant `{dom}` sleeve today:**", ""]
            for name, w in top.items():
                in_meta = name in meta.index
                stage = str(meta.loc[name, "stage"]) if in_meta else ""
                desc = str(meta.loc[name, "description"]) if in_meta else ""
                if not desc.strip() and in_meta:      # fall back to lineage
                    desc = str(meta.loc[name, "lineage"])
                desc = desc.strip()
                desc = (desc[:60] + "…") if len(desc) > 61 else desc
                line = f"- `{name}` ({stage}, wt {_f(w, 3)})"
                out.append(f"{line} — {desc}" if desc else line)
    out.append("")
    return out


def _construction_section(cfg, res) -> list[str]:
    seats = _last(getattr(res.construct, "seats", None))
    return [
        "## 8 · Construction & universe",
        "",
        f"- seats: live `{int(seats) if np.isfinite(seats) else 'n/a'}` "
        f"(adaptive {cfg.seats_adaptive}; base {cfg.seats_base}, "
        f"min {cfg.seats_min}, max {cfg.seats_max}, disp-slope "
        f"{_f(cfg.seats_disp_slope, 1)})",
        f"- position bounds: max {_pct(cfg.max_pos)} / min {_pct(cfg.min_pos)} "
        f"· softmax tilt α {_f(cfg.softmax_tilt_alpha, 2)} · seat weighting "
        f"`{cfg.seat_weighting}`",
        f"- smoothing: score {cfg.score_smooth_win}d · weight-EMA α "
        f"{_f(cfg.weight_smooth_alpha, 2)} · no-trade band {_pct(cfg.no_trade_band)}",
        f"- cluster caps: corr>{_f(cfg.cluster_corr_thresh, 2)} over "
        f"{cfg.cluster_corr_win}d capped at {_pct(cfg.cluster_weight_cap)}",
        f"- universe filters: price ≥ ${_f(cfg.min_price, 2)} · "
        f"ADV ≥ ${cfg.min_adv:,.0f} over {cfg.adv_win}d",
        f"- costs assumed: {_f(cfg.tc_bps, 1)} bps + "
        f"{_pct(cfg.adv_participation_cap)} ADV participation cap",
        "",
    ]


def _holdings_section(table) -> list[str]:
    aliased = "ticker" in table.columns
    rows = ["## 2 · Holdings (weights contract)", ""]
    if aliased:
        rows += [
            "Ticker = deterministic illustrative alias mapped from the synthetic "
            "universe (`SYN0NN` → NASDAQ seed order); price paths are synthetic, "
            "names are for readability. Synthetic ID is the raw contract key.",
            "",
            "| Rank | Ticker | Synthetic ID | Weight | Weight % |",
            "| ---: | --- | --- | ---: | ---: |",
        ]
        for row in table.to_dict(orient="records"):
            rows.append(
                f"| {int(row['rank'])} | {row['ticker']} | {row['symbol']} | "
                f"{float(row['weight']):.8f} | {float(row['weight_pct']):.4f}% |"
            )
    else:
        rows += ["| Rank | Symbol | Weight | Weight % |",
                 "| ---: | --- | ---: | ---: |"]
        for row in table.to_dict(orient="records"):
            rows.append(
                f"| {int(row['rank'])} | {row['symbol']} | "
                f"{float(row['weight']):.8f} | {float(row['weight_pct']):.4f}% |"
            )
    rows.append("")
    return rows


def render_pm_onepager(cfg, res, panel, *, weights_hash: str, config_hash: str,
                       provider_repr: str, config_repr: str,
                       markov: MarkovRegime | None = None,
                       symbol_labels: dict[str, str] | None = None) -> str:
    """Assemble the full PM one-pager markdown for a completed run.

    ``symbol_labels`` maps raw symbols to display tickers (see
    :func:`synthetic_ticker_aliases`); when given, holdings show the ticker.
    """
    table = holdings_table(res, symbol_labels)
    parts: list[str] = [
        "# Svyable strategy run — PM one-pager",
        "",
        "Single-page validation briefing: what strategy, what risk state, what "
        "regime, which sleeves and factors are live, and the resulting book. "
        "Generated deterministically by `tests/test_regression.py`.",
        "",
    ]
    parts += _reproducibility(cfg, res, table, weights_hash=weights_hash,
                              config_hash=config_hash, provider_repr=provider_repr,
                              config_repr=config_repr)
    parts += _holdings_section(table)        # §2 — book up top, real tickers first
    parts += _risk_posture(cfg, res)
    parts += _regime_stack(cfg, res)
    parts += _markov_section(markov)
    parts += _sleeve_section(cfg, res)
    parts += _factor_section(cfg, res)
    parts += _construction_section(cfg, res)
    return "\n".join(parts).rstrip() + "\n"
