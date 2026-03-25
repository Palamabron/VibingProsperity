class Order:
    def __init__(self, symbol: str, price: int, quantity: int) -> None: ...

class OrderDepth:
    buy_orders: dict[int, int]
    sell_orders: dict[int, int]

class TradingState:
    order_depths: dict[str, OrderDepth]
    position: dict[str, int]
    traderData: str
