"""Svyable engine — daily cross-sectional alpha and portfolio selection.

Pipeline: Panel -> factors -> sleeve IC weighting -> construction -> regime-aware
risk budget -> registered strategies/chimeras -> canonical Tastytrade target.
"""

__version__ = "0.3.0"

from svyable.panel import Panel
from svyable.config import SvyableConfig, nasdaq_lo_config

# Register production price-action extensions at package import time so research,
# strategy validation, and the daily pipeline share one factor catalog.
from svyable import factor_institutional as _factor_institutional  # noqa: F401,E402
