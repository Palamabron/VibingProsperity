This is a comprehensive breakdown of the **IMC Prosperity 4** algorithmic trading strategy, translated into clear, professional English. I’ve distilled the dense technical jargon into actionable insights while maintaining the "quant" depth you need to succeed.

## ---

**1\. The Environment: AWS Lambda & High-Stakes Constraints**

The simulation runs on **AWS Lambda**, which introduces two critical challenges:

* **Statelessness:** Every time your run() method is called, the memory is wiped clean. You cannot use global variables to store price history.  
* **The traderData Workaround:** To "remember" data between timestamps, you must serialize your data into a string (using jsonpickle) and pass it into the traderData field.  
  * **Limit:** Exactly **50,000 characters**.  
  * **Risk:** If you exceed this limit or the **900ms execution time** (100ms is the "safe" target), your algorithm crashes, and you lose PnL.

## ---

**2\. Market Microstructure: No Latency, Pure Strategy**

Unlike real-world HFT (High-Frequency Trading), Prosperity 4 has **zero network latency**.

* All participants (you and the system bots) see the market and act in the same discrete time step.  
* **Implication:** You cannot "outrun" others with speed. You must win through **Market Making** (providing liquidity) and **Fair Value Prediction** (statistical modeling).

## ---

**3\. The Golden Rule: Position Risk Controls**

This is the most common cause of failure. Each asset has a **Position Limit** (e.g., 20 units).

**CRITICAL:** If the sum of your open orders *could* potentially push you over the limit, the exchange rejects **your entire order packet** for that asset.

**The Solution:** You must calculate your "remaining room" before every trade:

$$V\_{max\\\_buy} \= Limit \- CurrentPosition$$

$$V\_{max\\\_sell} \= \-Limit \- CurrentPosition$$  
Never send orders that exceed these values, even if you think a buy and sell will "cancel out" (netting). The exchange checks risk *before* execution.

## ---

**4\. Strategy Taxonomy: How to Win Each Round**

### **A. Market Making (The "Bread and Butter")**

For stable assets (like *Amethysts*), you want to capture the **Bid-Ask Spread**.

* **Fair Value:** Don't just use the mid-price. Use a **Volume-Weighted Average Price (VWAP)** to see where the "real" price is.  
* **Inventory Skewing:** If you are "long" (+15 out of 20), lower your buy price and lower your sell price to encourage the market to buy from you, returning your position to zero.

### **B. Momentum & Mean Reversion**

For volatile assets (like *Starfruit*), use an **Exponential Moving Average (EMA)**:

$$EMA\_t \= \\alpha \\cdot Price\_t \+ (1 \- \\alpha) \\cdot EMA\_{t-1}$$

* **Signal:** When the price deviates significantly from the EMA (check the **Z-score**), bet on it returning to the mean.

### **C. Statistical Arbitrage (StatArb)**

Later rounds introduce correlated pairs (e.g., *Coconuts* and *Pina Colada*).

* Monitor the **Spread** between the two.  
* If the spread widens beyond historical norms (Z-score \> 2), sell the expensive one and buy the cheap one.

### **D. Options & Volatility**

For "Vouchers" (Options), you must use the **Black-Scholes Model**.

* Calculate **Implied Volatility (IV)** by reversing the formula.  
* Look for "Volatility Smiles"—if one option is priced inconsistently compared to others, there is an arbitrage opportunity.

## ---

**5\. The "Bid Method" (Round 2 Game Theory)**

Round 2 features a secret auction. You must implement the bid() function.

* This is a **Nash Equilibrium** problem.  
* Historical data suggests that bidding around **980** (on a scale to 1000\) is a "safe" bet that captures high margins while still winning the auction against less rational bots.

## ---

**6\. Implementation Roadmap**

| Phase | Focus | Key Task |
| :---- | :---- | :---- |
| **I. Foundations** | Backtesting | Build a local Python emulator to test position limits. |
| **II. Stability** | State Management | Perfect jsonpickle serialization and 50k char pruning. |
| **III. Scaling** | Correlation | Implement Z-score models for ETFs and Pair Trading. |
| **IV. Endgame** | Bot Tracking | Identify specific bot names (e.g., "Vladimir") to copy-trade "informed" moves. |

## ---

**Starter Code Skeleton (Python)**

This structure handles the AWS Lambda state and basic risk checks.

Python

import jsonpickle  
from datamodel import TradingState, Order

class Trader:  
    def run(self, state: TradingState):  
        \# 1\. Load Memory  
        memory \= jsonpickle.decode(state.traderData) if state.traderData else {'ema': {}}  
          
        result \= {}  
        for product in state.order\_depths:  
            order\_depth \= state.order\_depths\[product\]  
            pos \= state.position.get(product, 0)  
            limit \= 20 \# Example limit  
              
            \# 2\. Calculate Fair Value (Simple Mid-Price)  
            best\_bid \= max(order\_depth.buy\_orders.keys())  
            best\_ask \= min(order\_depth.sell\_orders.keys())  
            fair\_value \= (best\_bid \+ best\_ask) / 2  
              
            \# 3\. Risk-Managed Order Placement  
            orders \= \[\]  
            buy\_room \= limit \- pos  
            if best\_ask \< fair\_value and buy\_room \> 0:  
                vol \= min(buy\_room, abs(order\_depth.sell\_orders\[best\_ask\]))  
                orders.append(Order(product, best\_ask, vol))  
              
            result\[product\] \= orders

        \# 4\. Save Memory (with character limit safety)  
        trader\_data \= jsonpickle.encode(memory)  
        if len(trader\_data) \> 48000: trader\_data \= ""   
          
        return result, 0, trader\_data  
