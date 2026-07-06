from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from svyable.universe import (  # noqa: E402
    build_membership,
    load_index_changes,
    write_effective_universe_file,
)


def _events(path: Path) -> Path:
    path.write_text(
        "effective_date,index,action,symbol,source,note\n"
        "2026-07-07,NASDAQ100,add,SPCX,official,SpaceX inclusion\n"
        "2026-07-08,NASDAQ100,remove,OLD,official,scheduled removal\n"
    )
    return path


def test_effective_universe_applies_events_only_after_effective_date(tmp_path):
    seed = tmp_path / "seed.txt"
    seed.write_text("AAPL\nOLD\n")

    out = tmp_path / "effective.txt"
    before = write_effective_universe_file(
        seed, _events(tmp_path / "events.csv"), out, as_of="2026-07-06"
    )
    assert "SPCX" not in out.read_text().splitlines()
    assert "OLD" in out.read_text().splitlines()
    assert before["pending_events"] == 2

    after = write_effective_universe_file(
        seed, tmp_path / "events.csv", out, as_of="2026-07-08"
    )
    syms = set(out.read_text().splitlines())
    assert "SPCX" in syms
    assert "OLD" not in syms
    assert after["applied_events"] == 2


def test_membership_overlay_respects_effective_dates(tmp_path):
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()
    (snap_dir / "2026-07-06.json").write_text(json.dumps({
        "date": "2026-07-06",
        "listed_market": "XNAS",
        "symbols": ["AAPL", "OLD"],
    }))

    mem = build_membership(
        snap_dir,
        index_events=_events(tmp_path / "events.csv"),
        as_of="2026-07-08",
    )

    assert bool(mem.loc[pd.Timestamp("2026-07-06"), "SPCX"]) is False
    assert bool(mem.loc[pd.Timestamp("2026-07-07"), "SPCX"]) is True
    assert bool(mem.loc[pd.Timestamp("2026-07-07"), "OLD"]) is True
    assert bool(mem.loc[pd.Timestamp("2026-07-08"), "OLD"]) is False


def test_index_change_manifest_rejects_same_day_conflicts(tmp_path):
    events = tmp_path / "events.csv"
    events.write_text(
        "effective_date,index,action,symbol,source,note\n"
        "2026-07-07,NASDAQ100,add,SPCX,official,add\n"
        "2026-07-07,NASDAQ100,remove,SPCX,official,remove\n"
    )

    with pytest.raises(ValueError, match="conflicting same-day actions"):
        load_index_changes(events)
