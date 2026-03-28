"""
Local shim so `from datamodel import ...` resolves when developing offline.

IMC Prosperity injects its own `datamodel` in the official environment; do not
upload this file as part of a submission (submit `algorithm.py` only).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Order:
    symbol: str
    price: int
    quantity: int


@dataclass(slots=True)
class OrderDepth:
    buy_orders: dict[int, int] = field(default_factory=dict)
    sell_orders: dict[int, int] = field(default_factory=dict)


@dataclass(slots=True)
class TradingState:
    traderData: str
    order_depths: dict[str, OrderDepth]
    position: dict[str, int]


__all__ = ["Order", "OrderDepth", "TradingState"]
