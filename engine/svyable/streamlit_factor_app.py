"""Standalone factor-governance page for Streamlit multipage discovery."""

from svyable.dashboard_factor_governance import render_factor_governance
from svyable.streamlit_app import configured_output_root, service_for
from svyable.broker_settings import TastySettings


def render() -> None:
    settings = TastySettings.from_env(require_credentials=False)
    service = service_for(configured_output_root(settings))
    render_factor_governance(service)


if __name__ == "__main__":
    render()
