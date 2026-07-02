"""Observability GUI — a self-contained HTML dashboard generated from the
ledger after every run. No server, no JS dependencies (inline SVG charts),
works offline, one file per env. Open engine/outputs/dashboard.html anytime;
the daily loop regenerates it.
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

import pandas as pd

from svyable.ledger import Ledger

_CSS = """
body{font:14px -apple-system,Helvetica,sans-serif;margin:24px;background:#0f1115;color:#d8dee9}
h1{font-size:20px} h2{font-size:15px;margin:22px 0 8px;color:#88c0d0}
table{border-collapse:collapse;width:100%;font-size:12.5px}
td,th{padding:4px 8px;border-bottom:1px solid #2e3440;text-align:left}
th{color:#81a1c1} .ok{color:#a3be8c}.warn{color:#ebcb8b}.crit{color:#bf616a}
.card{background:#161a22;border:1px solid #2e3440;border-radius:8px;padding:14px;margin:10px 0}
.kpis{display:flex;gap:14px;flex-wrap:wrap}
.kpi{background:#161a22;border:1px solid #2e3440;border-radius:8px;padding:10px 16px}
.kpi b{display:block;font-size:18px}.kpi span{font-size:11px;color:#81a1c1}
svg{background:#161a22;border:1px solid #2e3440;border-radius:8px}
"""


def _svg_line(series: pd.Series, w: int = 560, h: int = 120,
              color: str = "#88c0d0", label: str = "") -> str:
    s = series.dropna()
    if len(s) < 2:
        return f"<svg width='{w}' height='{h}'><text x='10' y='20' fill='#666'>no data: {label}</text></svg>"
    vals = s.to_numpy(dtype=float)
    lo, hi = float(vals.min()), float(vals.max())
    rng = (hi - lo) or 1.0
    pts = " ".join(
        f"{10 + i * (w - 20) / (len(vals) - 1):.1f},"
        f"{h - 15 - (v - lo) / rng * (h - 30):.1f}"
        for i, v in enumerate(vals))
    return (f"<svg width='{w}' height='{h}'>"
            f"<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='1.5'/>"
            f"<text x='10' y='14' fill='#81a1c1' font-size='11'>{html.escape(label)}"
            f"  [{lo:.4g} … {hi:.4g}]</text></svg>")


def _table(df: pd.DataFrame, cols: list[str], n: int = 12) -> str:
    if df is None or not len(df):
        return "<p class='warn'>none</p>"
    rows = ["<tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"]
    for _, r in df.head(n).iterrows():
        rows.append("<tr>" + "".join(
            f"<td>{html.escape(str(r.get(c, ''))[:90])}</td>" for c in cols) + "</tr>")
    return "<table>" + "".join(rows) + "</table>"


def generate(output_root: str | Path, env: str = "sandbox") -> Path:
    out = Path(output_root)
    led = Ledger(out / "ledger.db")
    health = led.health()
    runs = led.recent_runs(15)
    eq = led.equity_frame()
    warns = led.open_warnings(14)
    orders = pd.read_sql_query(
        "SELECT ts, broker, dry_run, symbol, side, qty, est_notional, status, reason"
        " FROM orders ORDER BY id DESC LIMIT 15", led.con)

    latest = out / "svyable_nasdaq_lo" / "LATEST.md"
    report_link = f"<a href='{latest.name}' style='color:#88c0d0'>morning report</a>" \
        if latest.exists() else ""

    kill = "clear"
    try:
        import json as _j
        m = _j.loads(runs.iloc[0]["metrics"]) if len(runs) else {}
        budget = m.get("budget", "—")
        positions = m.get("positions", "—")
    except Exception:  # noqa: BLE001
        budget = positions = "—"

    kpis = {
        "env": env,
        "last run": (health.get("last_daily_run") or {}).get("ts", "never"),
        "status": (health.get("last_daily_run") or {}).get("status", "—"),
        "budget": budget, "positions": positions,
        "tracking days": health.get("tracking_days"),
        "drift ≤30bps": health.get("drift_within_30bps_frac"),
        "warnings 7d": health.get("warnings_7d"),
        "critical 7d": health.get("critical_7d"),
    }
    kpi_html = "".join(f"<div class='kpi'><b>{html.escape(str(v))}</b>"
                       f"<span>{html.escape(k)}</span></div>" for k, v in kpis.items())

    eq_svg = _svg_line(eq.set_index("d")["shadow_nav"], label="shadow NAV") if len(eq) else \
        _svg_line(pd.Series(dtype=float), label="shadow NAV")
    drift_svg = _svg_line(eq.set_index("d")["drift_bps"], color="#ebcb8b",
                          label="live-vs-shadow drift (bps)") if len(eq) else \
        _svg_line(pd.Series(dtype=float), label="drift bps")

    doc = f"""<!doctype html><html><head><meta charset='utf-8'>
<title>Svyable — {env}</title><style>{_CSS}</style>
<meta http-equiv='refresh' content='300'></head><body>
<h1>Svyable Operations — <span class='{'warn' if env == 'production' else 'ok'}'>{env.upper()}</span>
 <small style='font-size:11px;color:#666'>generated {datetime.now().isoformat(timespec='seconds')}</small></h1>
<div class='kpis'>{kpi_html}</div>
<h2>Equity & tracking</h2>
<div>{eq_svg} {drift_svg}</div>
<h2>Recent runs {report_link}</h2>
<div class='card'>{_table(runs, ['ts', 'kind', 'status', 'data_last_date', 'config_hash'])}</div>
<h2>Recent orders</h2>
<div class='card'>{_table(orders, ['ts', 'broker', 'dry_run', 'symbol', 'side', 'qty', 'est_notional', 'status'])}</div>
<h2>Warnings (14d)</h2>
<div class='card'>{_table(warns, ['ts', 'level', 'source', 'message'])}</div>
</body></html>"""

    path = out / "dashboard.html"
    path.write_text(doc)
    led.close()
    return path
