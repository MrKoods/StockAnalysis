# SHARED: Centralized logging setup for both models and backtesting.
# All modules obtain a logger via get_logger() so log format and level are controlled in one place.

import logging


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Return a configured logger for the given module name."""
    pass
