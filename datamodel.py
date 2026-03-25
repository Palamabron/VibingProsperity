"""
Local shim so `from datamodel import ...` resolves when running backtests.

IMC Prosperity injects its own `datamodel` in the official environment; do not
upload this file as part of a submission (submit `algorithm.py` only).
"""

from prosperity4bt.datamodel import Order, OrderDepth, TradingState

__all__ = ["Order", "OrderDepth", "TradingState"]
