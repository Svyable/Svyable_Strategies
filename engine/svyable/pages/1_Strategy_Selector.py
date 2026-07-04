"""Streamlit multipage entry for strategy registry and PM selection."""

import streamlit as st

from svyable.broker_settings import TastySettings
from svyable.dashboard_strategy_selector import render_strategy_selector
from svyable.streamlit_app import configured_output_root
from svyable.strategy_selection_service import StrategySelectionService


st.set_page_config(page_title="Svyable Strategy Selector", page_icon="🧠", layout="wide")
st.title("Strategy Registry & PM Selector")
settings = TastySettings.from_env(require_credentials=False)
service = StrategySelectionService(configured_output_root(settings))
status = service.frontier_status()

cols = st.columns(4)
cols[0].metric("Registered strategies", status["registry_strategy_count"])
cols[1].metric("Default strategies", status["default_strategy_count"])
cols[2].metric("Policy frontier", status["expected_candidate_count"])
cols[3].metric("Latest board", status["board_candidate_count"])
if status["is_incomplete_latest_board"]:
    st.warning(status["explanation"])
    if st.button("Enable every default strategy + chimera", type="primary"):
        path = service.save_full_frontier_policy()
        st.success(f"Saved full-frontier policy to `{path}`. Run a fresh candidate evaluation next.")
        st.rerun()

render_strategy_selector(service)
