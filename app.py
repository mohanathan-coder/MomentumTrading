#!/usr/bin/env python3
"""
Streamlit Web Dashboard for Nifty 500 Momentum Strategy
========================================================
Interactive web app for tracking and executing the Nifty 500
Multi-Timeframe Momentum Strategy.
"""

import os
import datetime
import pandas as pd
import numpy as np
import streamlit as st

import momentum_screener as ms

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(
    page_title="Nifty 500 Momentum",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .buy-tag { color: #198754; font-weight: bold; }
    .sell-tag { color: #dc3545; font-weight: bold; }
    .hold-tag { color: #ffc107; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("📈 Nifty 500 Momentum Trading Dashboard")
st.caption("Quantitative Multi-Timeframe Momentum (3M, 6M, 9M) Screener & Portfolio Manager")

# Sidebar Configuration
st.sidebar.header("⚙️ Strategy Settings")
capital = st.sidebar.number_input("Total Capital (₹)", min_value=10000, max_value=50000000, value=100000, step=10000)
n_hold = st.sidebar.slider("Number of Stocks to Hold", min_value=5, max_value=30, value=20)
exit_rank = st.sidebar.slider("Exit Buffer Rank", min_value=20, max_value=50, value=40, 
                              help="Hold current stocks if rank is within this threshold to avoid excessive churn.")

# Rebalance Frequency
st.sidebar.markdown("---")
st.sidebar.subheader("🗓️ Rebalance Frequency")
rebalance_freq = st.sidebar.selectbox(
    "Choose Frequency:",
    ["Monthly (Recommended)", "Weekly", "Daily"]
)

today = datetime.date.today()
if rebalance_freq.startswith("Monthly"):
    rebalance_day = st.sidebar.number_input("Monthly Rebalance Day (e.g. 21st)", min_value=1, max_value=28, value=21)
    if today.day < rebalance_day:
        next_rebalance_date = datetime.date(today.year, today.month, rebalance_day)
    else:
        next_m = today.month + 1 if today.month < 12 else 1
        next_y = today.year if today.month < 12 else today.year + 1
        next_rebalance_date = datetime.date(next_y, next_m, rebalance_day)
    rebalance_label = f"Monthly (Day {rebalance_day}) • Next Due: {next_rebalance_date.strftime('%d-%b-%Y')}"

elif rebalance_freq.startswith("Weekly"):
    weekly_day = st.sidebar.selectbox("Weekly Execution Day", ["Friday Market Close", "Monday Market Open"])
    target_weekday = 4 if "Friday" in weekly_day else 0
    days_ahead = (target_weekday - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    next_weekly_date = today + datetime.timedelta(days=days_ahead)
    rebalance_label = f"Weekly ({weekly_day}) • Next Due: {next_weekly_date.strftime('%d-%b-%Y')}"

else: # Daily
    st.sidebar.warning("⚠️ **Note on Daily Rebalance:** Checking and trading daily with ₹1 Lakh incurs high flat DP charges (~₹16/sale) and short-term taxes. Monthly rebalance is quantitatively superior.")
    next_trading_day = today + datetime.timedelta(days=1 if today.weekday() < 4 else (7 - today.weekday()))
    rebalance_label = f"Daily • Next Due: {next_trading_day.strftime('%d-%b-%Y')}"

st.sidebar.markdown("---")
refresh_data = st.sidebar.button("🔄 Force Refresh Market Data from NSE")

# Fast Cached Data Loader
@st.cache_data(ttl=3600, show_spinner=False)
def get_market_data(force_refresh=False):
    tickers, name_mapping = ms.load_universe(ms.DEFAULT_UNIVERSE)
    close_df, volume_df = ms.load_or_fetch_prices(tickers, refresh=force_refresh)
    rank_df = ms.compute_momentum_ranks(close_df, volume_df)
    return rank_df, name_mapping

if refresh_data:
    st.cache_data.clear()
    st.sidebar.success("Market data cache refreshed!")

with st.spinner("Loading market data & momentum ranks..."):
    rank_df, name_mapping = get_market_data(force_refresh=refresh_data)

# Determine the exact date of CMP
cmp_date_str = rank_df["cmp_date"].iloc[0] if ("cmp_date" in rank_df.columns and not rank_df.empty) else today.strftime("%d-%b-%Y")

# Prominent Info Banner
b_col1, b_col2 = st.columns([1, 1])
with b_col1:
    st.info(f"📅 **Current Market Price (CMP) Date:** **`{cmp_date_str}`** *(NSE Closing)*")
with b_col2:
    st.info(f"⏰ **Rebalance Schedule:** **`{rebalance_label}`**")

tab1, tab2, tab3 = st.tabs(["🚀 Rebalance Screener", "📊 Active Portfolio", "🧪 Backtest Report"])

# --------------------------------------------------------------------------- #
# TAB 1: Live Screener (Re-calculates dynamically on Capital change)
# --------------------------------------------------------------------------- #
with tab1:
    st.subheader(f"Orders & Capital Allocation ({rebalance_freq.split()[0]} Frequency)")
    
    col_mode1, col_mode2 = st.columns([3, 2])
    with col_mode1:
        mode = st.radio(
            "Select Screener Mode:",
            ["Initial / Fresh Allocation (Scale to entered Capital)", 
             "Rebalance Check (Compare against Active Portfolio)"],
            horizontal=True
        )

    # 1. Fresh Allocation Mode
    if mode.startswith("Initial"):
        slot_budget = capital / n_hold
        allocations = []
        for _, row in rank_df.iterrows():
            if len(allocations) >= n_hold:
                break
            sym = row["symbol"]
            cmp_val = row["cmp"]
            if cmp_val > slot_budget:
                continue
            shares = int(slot_budget // cmp_val)
            if shares < 1:
                continue
            allocations.append({
                "action": "BUY",
                "symbol": sym,
                "company": name_mapping.get(sym, sym),
                "rank": row["rank"],
                "cmp": cmp_val,
                "cmp_date": row.get("cmp_date", cmp_date_str),
                "shares": shares,
                "est_value": round(shares * cmp_val, 2),
                "reason": f"Rank #{row['rank']} (Score: {row['score']:.2f})"
            })
        df_orders = pd.DataFrame(allocations)

    # 2. Rebalance Mode
    else:
        df_orders, _ = ms.generate_rebalance_orders(
            rank_df,
            name_mapping,
            capital=capital,
            n_hold=n_hold,
            exit_rank=exit_rank
        )

    # Display Metrics
    if not df_orders.empty:
        holds = (df_orders["action"] == "HOLD").sum()
        sells = (df_orders["action"] == "SELL").sum()
        buys = (df_orders["action"] == "BUY").sum()
        deployed = df_orders[df_orders["action"].isin(["HOLD", "BUY"])]["est_value"].sum()
        cash_left = max(0.0, capital - deployed)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Keep / HOLD", holds, help="Stocks remaining in Top 40")
        m2.metric("Exit / SELL", sells, help="Stocks falling below Rank 40")
        m3.metric("New BUYs", buys, help="New entrants from Top 20")
        m4.metric("Capital Deployed", f"₹{deployed:,.2f}", delta=f"Free Cash: ₹{cash_left:,.2f}")

        st.markdown(f"### Actionable Order Sheet *(Prices as of {cmp_date_str})*")
        
        def style_action(val):
            if val == "BUY":
                return "background-color: #d1e7dd; color: #0f5132; font-weight: bold;"
            elif val == "SELL":
                return "background-color: #f8d7da; color: #842029; font-weight: bold;"
            elif val == "HOLD":
                return "background-color: #fff3cd; color: #664d03; font-weight: bold;"
            return ""

        display_cols = ["action", "symbol", "company", "rank", "cmp", "cmp_date", "shares", "est_value", "reason"]
        display_df = df_orders[display_cols]
        st.dataframe(
            display_df.style.map(style_action, subset=["action"]),
            use_container_width=True,
            hide_index=True
        )

        btn_c1, btn_c2 = st.columns([2, 5])
        with btn_c1:
            if st.button("💾 Save as Active Portfolio", type="primary"):
                new_portfolio = []
                for _, r in df_orders.iterrows():
                    if r["action"] in ["HOLD", "BUY"]:
                        new_portfolio.append({
                            "symbol": r["symbol"],
                            "company": r["company"],
                            "ticker": f"{r['symbol']}.NS",
                            "shares": r["shares"],
                            "avg_price": r["cmp"],
                            "invested": r["est_value"],
                            "bought_date": cmp_date_str
                        })
                ms.save_current_portfolio(pd.DataFrame(new_portfolio))
                st.success("✅ Portfolio saved! Check Tab 2 to view your active holdings.")
        
        with btn_c2:
            csv_data = display_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label=f"📥 Download Order Sheet (as of {cmp_date_str})",
                data=csv_data,
                file_name=f"momentum_orders_{cmp_date_str}.csv",
                mime="text/csv"
            )

# --------------------------------------------------------------------------- #
# TAB 2: Active Portfolio Tracker
# --------------------------------------------------------------------------- #
with tab2:
    st.subheader("Current Active Portfolio Holdings")
    port_path = os.path.join(BASE_DIR, "current_portfolio.csv")
    
    if os.path.exists(port_path):
        port_df = pd.read_csv(port_path)
        if not port_df.empty:
            total_invested = port_df["invested"].sum()
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Holdings", len(port_df))
            c2.metric("Total Invested Value", f"₹{total_invested:,.2f}")
            c3.metric("Cash Balance", f"₹{max(0.0, capital - total_invested):,.2f}")

            st.dataframe(port_df, use_container_width=True, hide_index=True)
            
            if st.button("🗑️ Reset Portfolio (Clear All)"):
                os.remove(port_path)
                st.rerun()
        else:
            st.info("Portfolio is empty. Save a new portfolio from Tab 1.")
    else:
        st.info("No active portfolio found. Save a new portfolio from Tab 1.")

# --------------------------------------------------------------------------- #
# TAB 3: Backtest Performance
# --------------------------------------------------------------------------- #
with tab3:
    st.subheader("Historical Quantitative Backtest (2019 – Present)")
    summary_path = os.path.join(BASE_DIR, "results", "summary.csv")
    chart_path = os.path.join(BASE_DIR, "results", "equity_curve.png")
    
    if os.path.exists(summary_path):
        summary_df = pd.read_csv(summary_path)
        st.dataframe(summary_df, use_container_width=True, hide_index=True)
    
    if os.path.exists(chart_path):
        st.image(chart_path, caption="Equity Growth: Momentum Strategy vs Nifty 500 Index (Log Scale)", use_container_width=True)
        
    st.markdown("""
    > **Key Backtest Findings:**
    > - **Monthly Rebalance with Rank 40 Buffer:** **39.2% CAGR**, 854 trades, **saved ₹36,000+** in DP fees compared to strict exit.
    > - **Why Weekly or Daily has higher friction:** Delivery sales in Indian markets incur flat DP charges (~₹16/sale). Daily or weekly churn increases transaction drag. Monthly rebalancing provides optimal trend capture with minimal fees.
    > - **Nifty 500 Index:** 13.4% CAGR, -38.3% Drawdown.
    """)
