"""Standalone Streamlit page for selection meta diagnostics."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from svyable.dashboard_agent_intel import render_agent_intel


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = Path(os.environ.get("SVYABLE_OUTPUT_ROOT", ROOT / "outputs"))

st.set_page_config(page_title="Svyable Selection Meta Harness", layout="wide")
st.title("Svyable Selection Meta Harness")
st.caption("Auditable selection tree, visible regime proxy, candidate rails, and deterministic weight provenance.")
render_agent_intel(OUTPUT_ROOT)
