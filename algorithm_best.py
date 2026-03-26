import math
from typing import cast

import jsonpickle
from datamodel import Order, TradingState


class TradingConstants:
    POSITION_LIMITS = {"EMERALDS": 20, "TOMATOES": 20}
    TOMATOES_ALPHA = 0.44
    EMERALDS_FIXED_FAIR = 10000
    SERIALIZATION_THRESHOLD = 45000
    # Changed TAKER_THRESHOLD from 1.0 to 0.5.
    # Data analytics showed very low taker opportunity rates, suggesting the previous threshold (1.0)
    # was too conservative, missing profitable taker trades on small price deviations.
    TAKER_THRESHOLD = 0.5
    DEFAULT_LIMIT = 20
    # Initial offset from fair_value for EMERALDS maker orders
    # A larger value means bids are placed lower and asks higher, widening the strategy's own spread.
    EMERALDS_MAKER_SPREAD_OFFSET = 2


class TraderState:
    def __init__(self) -> None:
        self.tomatoes_ema: float | None = None
        self.iteration: int = 0


class Trader:
    def bid(self) -> int:
        """
        Dummy bid function, can be used for specific rounds if needed.
        """
        return 980

    def _get_state(self, state_data: str) -> TraderState:
        if not state_data:
            return TraderState()
        try:
            return cast(TraderState, jsonpickle.decode(state_data))
        except Exception:
            # Fallback to a fresh state if deserialization fails
            return TraderState()

    def _serialize_state(self, memory: TraderState) -> str:
        encoded = jsonpickle.encode(memory)
        # Reset state if it grows too large to avoid hitting submission limits
        if len(encoded) > TradingConstants.SERIALIZATION_THRESHOLD:
            return cast(str, jsonpickle.encode(TraderState()))
        return cast(str, encoded)

    def _compute_micro_price(
        self, buy_orders: list[tuple[int, int]], sell_orders: list[tuple[int, int]]
    ) -> float:
        """
        Calculates a micro-price based on the best bid and ask, weighted by their volumes.
        """
        # This function is called only if buy_book and sell_book are not empty,
        # so best_bid/ask will exist.
        best_bid, best_bid_vol = buy_orders[0]
        best_ask, best_ask_vol = sell_orders[0]
        best_ask_vol = abs(best_ask_vol)  # Volume for asks is negative, use absolute

        # Defensive check: if total volume at best bid/ask is zero, fall back to mid-price.
        if (best_bid_vol + best_ask_vol) == 0:
            return float((best_bid + best_ask) / 2)

        return (best_bid * best_ask_vol + best_ask * best_bid_vol) / (best_bid_vol + best_ask_vol)

    def _calculate_fair_value(self, product: str, micro_price: float, memory: TraderState) -> float:
        """
        Determines the fair value for a product.
        EMERALDS use a fixed fair value. TOMATOES use an Exponential Moving Average.
        """
        if product == "EMERALDS":
            return float(TradingConstants.EMERALDS_FIXED_FAIR)

        if product == "TOMATOES":
            if memory.tomatoes_ema is None:
                memory.tomatoes_ema = micro_price
            else:
                alpha = TradingConstants.TOMATOES_ALPHA
                memory.tomatoes_ema = (alpha * micro_price) + (1 - alpha) * memory.tomatoes_ema
            return memory.tomatoes_ema

        return micro_price  # Default for other products, if any

    def _calculate_inventory_skew(self, current_pos: int, limit: int) -> float:
        """
        Calculates an inventory skew to adjust bid/ask prices based on current position.
        Positive skew pushes bid down and ask up (encourages selling).
        Negative skew pushes bid up and ask down (encourages buying).
        """
        skew = (current_pos / limit) * 2.0
        # Increase skew aggressiveness when closer to position limits
        if abs(current_pos) >= (limit * 0.75):
            skew *= 3.0
        return skew

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        """
        Main trading logic. Iterates through products, calculates fair values,
        and places taker/maker orders.
        """
        result = {}
        conversions = 0  # No conversions implemented in this iteration
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

            # Taker strategy: try to take existing liquidity if profitable
            for price, vol in sell_book:  # Iterate through asks (sell offers)
                # If ask price is below our fair value minus a threshold, it's a good buy opportunity
                if price < fair_value - TradingConstants.TAKER_THRESHOLD and max_buy_vol > 0:
                    quantity = min(max_buy_vol, abs(vol))
                    orders.append(Order(product, price, quantity))
                    max_buy_vol -= quantity

            for price, vol in buy_book:  # Iterate through bids (buy offers)
                # If bid price is above our fair value plus a threshold, it's a good sell opportunity
                if price > fair_value + TradingConstants.TAKER_THRESHOLD and max_sell_vol > 0:
                    quantity = min(max_sell_vol, vol)
                    orders.append(Order(product, price, -quantity))
                    max_sell_vol -= quantity

            # Maker strategy: place limit orders if remaining volume
            if max_buy_vol > 0 or max_sell_vol > 0:
                best_bid, _ = buy_book[0]
                best_ask, _ = sell_book[0]

                bid_offset = 1
                ask_offset = 1
                bid_cap_modifier = 1
                ask_floor_modifier = 1

                if product == "EMERALDS":
                    # For EMERALDS, given its stable fair value and wide market spread,
                    # we now aim to place orders aggressively, 1 tick inside the market spread.
                    bid_offset = TradingConstants.EMERALDS_MAKER_SPREAD_OFFSET
                    ask_offset = TradingConstants.EMERALDS_MAKER_SPREAD_OFFSET
                    # CHANGED: These modifiers now make EMERALDS maker orders more aggressive.
                    bid_cap_modifier = 1  # Bid 1 tick inside best_bid
                    ask_floor_modifier = 1  # Ask 1 tick inside best_ask

                # Calculate base bid/ask price, adjusted by offset and skew.
                # The min/max with best_bid/ask +/- modifier ensures orders are competitive
                # but respects our desired spread and current market conditions.
                adjusted_fair_bid = fair_value - bid_offset - skew
                adjusted_fair_ask = fair_value + ask_offset - skew

                base_bid = min(math.floor(adjusted_fair_bid), best_bid + bid_cap_modifier)
                base_ask = max(math.ceil(adjusted_fair_ask), best_ask - ask_floor_modifier)

                # Custom, more aggressive layering for EMERALDS to maximize fills at competitive prices.
                if product == "EMERALDS":
                    if max_buy_vol > 0:
                        # Place a significant portion at the most competitive price point
                        vol1 = min(max_buy_vol, int(limit * 0.6))
                        orders.append(Order(product, base_bid, vol1))
                        max_buy_vol -= vol1

                        if max_buy_vol > 0:
                            # Place remaining volume one tick lower
                            orders.append(Order(product, base_bid - 1, max_buy_vol))

                    if max_sell_vol > 0:
                        # Place a significant portion at the most competitive price point
                        vol1 = min(max_sell_vol, int(limit * 0.6))
                        orders.append(Order(product, base_ask, -vol1))
                        max_sell_vol -= vol1

                        if max_sell_vol > 0:
                            # Place remaining volume one tick higher
                            orders.append(Order(product, base_ask + 1, -max_sell_vol))
                else:  # TOMATOES and other products, use the original 3-layer approach
                    # Place multiple layers of bids to fill up remaining buy volume
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

                    # Place multiple layers of asks to fill up remaining sell volume
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