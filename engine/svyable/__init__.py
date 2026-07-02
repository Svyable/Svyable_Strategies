"""Svyable engine — daily cross-sectional alpha, vendor-agnostic.

Pipeline: Panel -> factors -> sleeve IC weighting -> composite score
       -> seats/tilt/projection -> vol-target budget x dd throttle
       -> target weights + morning report.

See ../strategy.md for the full specification this implements.
"""

__version__ = "0.1.0"

from svyable.panel import Panel
from svyable.config import SvyableConfig, nasdaq_lo_config
