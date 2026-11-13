# Nifty 500 Momentum Trading System

A quantitative, multi-timeframe cross-sectional momentum trading framework designed for Indian equities (NSE Nifty 500).

---

## 1. Strategy Parameters

| Parameter | Setting | Description |
| :--- | :--- | :--- |
| **Universe** | Nifty 500 | Filtered from `ind_nifty500list.csv` |
| **Lookback Windows** | 3M, 6M, 9M | 63, 126, 189 trading days |
| **Score Formula** | Multi-timeframe Sharpe | Average cross-sectional z-score of $(Return / \sigma_{1Y})$ |
| **Portfolio Size** | 20 stocks | Equal weight target (~₹5,000 / stock on ₹1 Lakh) |
| **Rebalance Day** | 21st of each month | Generates signals on close; execute next market open |
| **Exit Threshold** | Buffer (Rank 35/40) | Prevents whipsaw and excessive DP transaction charges |

---

## 2. Backtest Results (2019 - Present, ₹1,00,000 Initial Capital)

| Strategy | Final Value (₹) | CAGR % | Max Drawdown % | Sharpe | Trades | Total Costs (₹) | Total Taxes (₹) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Exit > 20 (Strict Rule, Post-Tax)** | ₹9,13,245 | 38.3% | -37.2% | 1.42 | 1,354 | ₹1,12,753 | ₹89,273 |
| **Exit > 40 (Buffer Rule, Post-Tax)** | **₹9,56,668** | **39.2%** | **-33.5%** | **1.45** | **854** | **₹76,727** | **₹99,776** |
| **Nifty 500 Buy & Hold** | ₹2,35,294 | 13.4% | -38.3% | 0.81 | - | - | - |

> **Key takeaway:** The **Rank Buffer rule** saved **₹36,000+** in broker fees, eliminated 500 churn trades, lowered maximum drawdown, and increased net final wealth.

---

## 3. How to Use

### A. First-Time Setup (Month 1: Initial 20 Stocks)
To generate your first 20-stock portfolio and save it:
```powershell
& "C:\Users\KMCL BHARATH\AppData\Local\Programs\Python\Python314\python.exe" momentum_screener.py --init --commit
```
This writes:
1. `current_portfolio.csv`: Tracks your 20 stocks.
2. `rebalance_orders_YYYY-MM-DD.csv`: Exact whole-share quantities and prices to place in your broker.

### B. Monthly Rebalance (Every 21st of the month)
On the evening of the 21st (or market close):
```powershell
& "C:\Users\KMCL BHARATH\AppData\Local\Programs\Python\Python314\python.exe" momentum_screener.py --commit
```
The script will:
- Check your holdings in `current_portfolio.csv`.
- Retain any stock whose new momentum rank is within the Top 35 (`HOLD`).
- Flag any stock that slipped below rank 35 (`SELL`).
- Select top-ranked new entrants to fill the open slots (`BUY`).
- Generate your execution sheet `rebalance_orders_YYYY-MM-DD.csv`.

### C. Launch Web Dashboard (Optional UI)
```powershell
& "C:\Users\KMCL BHARATH\AppData\Local\Programs\Python\Python314\python.exe" -m streamlit run app.py
```
View interactive equity curves, live signals, and portfolio status on your browser.
