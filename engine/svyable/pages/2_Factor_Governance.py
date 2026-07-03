"""Streamlit multipage entry for factor governance."""

import streamlit as st

from svyable.broker_settings import TastySettings
from svyable.dashboard_factor_governance import render_factor_governance
from svyable.streamlit_app import configured_output_root, service_for


st.set_page_config(page_title="Svyable Factor Governance", page_icon="🧭", layout="wide")
st.title("Factor Governance")
settings = TastySettings.from_env(require_credentials=False)
service = service_for(configured_output_root(settings))
render_factor_governance(service)
