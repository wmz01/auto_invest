# FinancialManager: Dynamic Regime-Switching DCA Engine

## Overview
FinancialManager is an automated, quantitative Dollar-Cost Averaging (DCA) execution engine. Unlike standard recurring investments that blindly buy the market regardless of conditions, this system utilizes a closed-loop state machine to dynamically scale execution size based on market volatility, mathematical overextension, and internal portfolio health. 

The architecture is designed to cleanly separate state management, market data ingestion, and trade execution, making it fully compatible with asynchronous broker integrations (e.g., `ib_async`).

## Core Architecture

The system is built on three modular pillars:
1. **Financial Manager (State):** Manages a strict three-bucket accounting system (Emergency Fund, Lump Sum, and active War Chest) to eliminate cash-drag ambiguity and route funds properly.
2. **Market Fetcher (Data):** Compiles daily technicals including 252-day Drawdown, 14-day RSI, and VIX to determine the current market regime.
3. **Decision Engine (Logic):** Maps the market state and portfolio health to a precise daily execution dollar amount.

## The Three-Bucket Accounting System
To mathematically decouple ongoing cash flow from existing deployable capital, the engine tracks cash in distinct silos:
* **The Untouchable Floor (Emergency):** Locked liquidity, completely hidden from the algorithm.
* **The Stock (Lump Sum):** Existing capital slowly deployed via a static weekly tranche to mitigate entry timing risk.
* **The Flow (War Chest):** Ongoing net cash flow (Income - Expenses). The engine targets an 85% deployment ratio, holding 15% as dynamic "dry powder" to buy market crashes.

---

## Hyperparameter Reference Guide

The core behavior of the `DecisionEngine` is controlled by a strictly defined set of hyperparameters. These variables dictate how the system classifies the market environment and how aggressively it scales capital deployment.

### 1. System Health & Baseline Sizing
These parameters control the underlying daily rhythm of the algorithm and how it manages the War Chest.

* **`trading_days_per_week`** (Default: 5.0)
  * *Function:* The divisor used to convert the calculated weekly surplus into a daily baseline target ($B).
* **`lambda_replenish`** (Default: 0.5)
  * *Function:* The aggressiveness of the War Chest replenishment scalar ($\Theta$). 
  * *Intuition:* If the War Chest drops below its 15% target, the engine throttles daily buying to rebuild cash. A higher $\lambda$ (e.g., 0.8) means the system will aggressively slash buys to refill the War Chest faster. A lower $\lambda$ (e.g., 0.2) allows the War Chest to refill slowly, favoring continued market exposure.

### 2. Regime Detection Triggers
The engine evaluates the market from highest risk to lowest risk. It uses these thresholds to categorize the current environment.

**CRISIS Regime (Structural Panic)**
* **`crisis_vix_threshold`** (Default: 30.0)
  * *Function:* Activates CRISIS mode if the CBOE Volatility Index exceeds this level, signaling widespread market panic.
* **`crisis_spread_threshold`** (Default: 5.0)
  * *Function:* Activates CRISIS mode if the High Yield Corporate Bond Spread exceeds 5%. This indicates severe structural liquidity issues in the credit markets.
* **`crisis_fg_threshold`** (Default: 20)
  * *Function:* Activates CRISIS mode if the CNN Fear & Greed Index drops into "Extreme Fear."

**GREEDY Regime (Mathematical Overextension)**
*Requires all conditions to be met simultaneously to prevent false positives during healthy bull markets.*
* **`greedy_rsi_threshold`** (Default: 75.0)
  * *Function:* The 14-day Relative Strength Index level indicating the asset is technically overbought.
* **`greedy_drawdown_threshold`** (Default: -0.015)
  * *Function:* Ensures the asset is trading within 1.5% of its 252-day All-Time High. 
* **`greedy_fg_threshold`** (Default: 75)
  * *Function:* CNN Fear & Greed Index must be showing "Extreme Greed."

### 3. Execution Sizing Multipliers
Once the regime is determined, these parameters calculate the exact multiplier applied to the daily baseline.

**REGULAR Execution Parameters**
* **`regular_dip_threshold_tau`** ($\tau$) (Default: 0.02)
  * *Function:* The noise filter (deadband). The market must drop by this percentage (e.g., 2%) before the algorithm begins scaling up its buy size.
* **`regular_aggressiveness_alpha`** ($\alpha$) (Default: 2.0)
  * *Function:* The slope of the continuous buy curve during standard market dips.
  * *Math:* `Multiplier = 1 + alpha * max(0, Drawdown - tau)`
  * *Intuition:* If $\alpha$ = 2.0, a 5% drawdown (which is 3% past the $\tau$ threshold) will result in a multiplier of 1.06 (buying 6% more than the daily baseline).

**CRISIS Execution Parameters**
* **`crisis_weight_W`** ($W$) (Default: 4.0)
  * *Function:* The baseline step-up. The moment a crisis is declared, the engine immediately multiplies its daily baseline by $W$, effectively pulling future cash forward.
* **`crisis_aggressiveness_beta`** ($\beta$) (Default: 4.0)
  * *Function:* The steepness of the buy curve during severe crashes. Because it operates in a high-volatility environment, there is no deadband ($\tau$).
  * *Math:* `Multiplier = W * (1 + beta * Drawdown)`
  * *Intuition:* If $\beta$ = 4.0 and $W$ = 4.0, a 20% drawdown results in a total multiplier of 7.2x the daily baseline. The engine is aggressively draining the War Chest to buy the bottom.

**GREEDY Execution Parameters**
* **`greedy_capital_preservation`** (Default: 0.5)
  * *Function:* The throttling scalar. When the market is mathematically overextended, the daily buy is multiplied by this fraction (e.g., 0.5 cuts the buy in half), intentionally starving the market to horde cash in the War Chest.

---

## Backtesting & Performance Edge
While trailing a 100% invested baseline in absolute Net Worth CAGR due to structural cash drag, the Dynamic Engine optimizes for the **Sortino Ratio**. By reducing portfolio Beta and dramatically slashing the Maximum Drawdown (MDD) and Time to Watermark, it generates a superior risk-adjusted return profile.