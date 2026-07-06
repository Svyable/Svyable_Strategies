"""Svyable engine — daily cross-sectional alpha and portfolio selection.

Pipeline: Panel -> factors -> sleeve IC weighting -> construction -> regime-aware
risk budget -> registered strategies/chimeras -> canonical Tastytrade target.
"""

__version__ = "0.3.0"

from svyable.panel import Panel
from svyable.config import SvyableConfig, nasdaq_lo_config

# Register production/frontier extensions at package import time so research,
# strategy validation, and the daily pipeline share one factor catalog.
from svyable import factor_institutional as _factor_institutional  # noqa: F401,E402
from svyable import factor_price_action_frontier as _factor_pa_ext  # noqa: F401,E402
from svyable import factor_tape_acceleration as _factor_tape_acceleration  # noqa: F401,E402
from svyable import factor_alpha_catalyst as _factor_alpha_catalyst  # noqa: F401,E402
from svyable import factor_leadership_quality as _factor_leadership_quality  # noqa: F401,E402
from svyable import factor_downside_resilience as _factor_downside_resilience  # noqa: F401,E402
from svyable import factor_rotation_breadth as _factor_rotation_breadth  # noqa: F401,E402
