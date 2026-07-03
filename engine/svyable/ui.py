"""Console launcher for the Streamlit dashboard."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    try:
        from streamlit.web import cli as stcli
    except ImportError as exc:
        raise SystemExit(
            "Streamlit is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    script = Path(__file__).with_name("streamlit_app.py")
    port = os.getenv("SVYABLE_STREAMLIT_PORT", "8501")
    address = os.getenv("SVYABLE_STREAMLIT_ADDRESS", "127.0.0.1")
    sys.argv = [
        "streamlit",
        "run",
        str(script),
        "--server.address",
        address,
        "--server.port",
        port,
        "--server.headless",
        "true",
    ]
    return int(stcli.main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
