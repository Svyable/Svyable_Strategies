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
render_strategy_selector(service)
