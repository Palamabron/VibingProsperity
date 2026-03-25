import math
from typing import cast

import jsonpickle
from datamodel import Order, TradingState


class TradingConstants:
    POSITION_LIMITS = {"EMERALDS": 20, "TOMATOES": 20}
    TOMATOES_ALPHA = 0.44
    EMERALDS_FIXED_FAIR = 10000
    SERIALIZATION_THRESHOLD = 45000
    TAKER_THRESHOLD = 0.5
    DEFAULT_LIMIT = 20


class TraderState:
    def __init__(self) -> None:
        self.tomatoes_ema: float | None = None
        self.iteration: int = 0


class Trader:
    def bid(self) -> int:
        return 980

    def _get_state(self, state_data: str) -> TraderState:
        if not state_data:
            return TraderState()
        try:
            return cast(TraderState, jsonpickle.decode(state_data))
        except Exception:
            return TraderState()

    def _serialize_state(self, memory: TraderState) -> str:
        encoded = jsonpickle.encode(memory)
        if len(encoded) > TradingConstants.SERIALIZATION_THRESHOLD:
            return cast(str, jsonpickle.encode(TraderState()))
        return cast(str, encoded)

    def _compute_micro_price(
        self, buy_orders: list[tuple[int, int]], sell_orders: list[tuple[int, int]]
    ) -> float:
        best_bid, best_bid_vol = buy_orders[0]
        best_ask, best_ask_vol = sell_orders[0]
        best_ask_vol = abs(best_ask_vol)

        return (best_bid * best_ask_vol + best_ask * best_bid_vol) / (best_bid_vol + best_ask_vol)

    def _calculate_fair_value(self, product: str, micro_price: float, memory: TraderState) -> float:
        if product == "EMERALDS":
            return float(TradingConstants.EMERALDS_FIXED_FAIR)

        if product == "TOMATOES":
            if memory.tomatoes_ema is None:
                memory.tomatoes_ema = micro_price
            else:
                alpha = TradingConstants.TOMATOES_ALPHA
                memory.tomatoes_ema = (alpha * micro_price) + (1 - alpha) * memory.tomatoes_ema
            return memory.tomatoes_ema

        return micro_price

    def _calculate_inventory_skew(self, current_pos: int, limit: int) -> float:
        skew = (current_pos / limit) * 2.0
        if abs(current_pos) >= (limit * 0.75):
            skew *= 3.0
        return skew

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        result = {}
        conversions = 0
        memory = self._get_state(state.traderData)
        memory.iteration += 1

        for product, order_depth in state.order_depths.items():
            orders: list[Order] = []
            current_pos = state.position.get(product, 0)
            limit = TradingConstants.POSITION_LIMITS.get(product, TradingConstants.DEFAULT_LIMIT)

            buy_book = sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)
            sell_book = sorted(order_depth.sell_orders.items(), key=lambda x: x[0])

            if not buy_book or not sell_book:
                continue

            micro_price = self._compute_micro_price(buy_book, sell_book)
            fair_value = self._calculate_fair_value(product, micro_price, memory)
            skew = self._calculate_inventory_skew(current_pos, limit)

            max_buy_vol = limit - current_pos
            max_sell_vol = limit + current_pos

            for price, vol in sell_book:
                if price < fair_value - TradingConstants.TAKER_THRESHOLD and max_buy_vol > 0:
                    quantity = min(max_buy_vol, abs(vol))
                    orders.append(Order(product, price, quantity))
                    max_buy_vol -= quantity

            for price, vol in buy_book:
                if price > fair_value + TradingConstants.TAKER_THRESHOLD and max_sell_vol > 0:
                    quantity = min(max_sell_vol, vol)
                    orders.append(Order(product, price, -quantity))
                    max_sell_vol -= quantity

            if max_buy_vol > 0 or max_sell_vol > 0:
                best_bid, _ = buy_book[0]
                best_ask, _ = sell_book[0]

                base_bid = min(math.floor(fair_value - 1 - skew), best_bid + 1)
                base_ask = max(math.ceil(fair_value + 1 - skew), best_ask - 1)

                if max_buy_vol > 0:
                    t1 = min(max_buy_vol, 5)
                    orders.append(Order(product, base_bid, t1))
                    max_buy_vol -= t1

                    if max_buy_vol > 0:
                        t2 = min(max_buy_vol, 10)
                        orders.append(Order(product, base_bid - 2, t2))
                        max_buy_vol -= t2

                    if max_buy_vol > 0:
                        orders.append(Order(product, base_bid - 4, max_buy_vol))

                if max_sell_vol > 0:
                    t1 = min(max_sell_vol, 5)
                    orders.append(Order(product, base_ask, -t1))
                    max_sell_vol -= t1

                    if max_sell_vol > 0:
                        t2 = min(max_sell_vol, 10)
                        orders.append(Order(product, base_ask + 2, -t2))
                        max_sell_vol -= t2

                    if max_sell_vol > 0:
                        orders.append(Order(product, base_ask + 4, -max_sell_vol))

            result[product] = orders

        return result, conversions, self._serialize_state(memory)
