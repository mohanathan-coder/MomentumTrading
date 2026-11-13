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
st.caption("Quantitative Multi-Timeframe Momentum (3M, 6M, 9M) with Monthly Rebalancing")

# Sidebar Configuration
st.sidebar.header("⚙️ Strategy Settings")
capital = st.sidebar.number_input("Total Capital (₹)", min_value=10000, max_value=50000000, value=100000, step=10000)
n_hold = st.sidebar.slider("Number of Stocks to Hold", min_value=5, max_value=30, value=20)
exit_rank = st.sidebar.slider("Exit Buffer Rank", min_value=20, max_value=50, value=40, 
                              help="Hold current stocks if rank is within this threshold to avoid excessive churn.")
rebalance_day = st.sidebar.number_input("Monthly Rebalance Day", min_value=1, max_value=28, value=21)

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

tab1, tab2, tab3 = st.tabs(["🚀 Rebalance Screener", "📊 Active Portfolio", "🧪 Backtest Report"])

# --------------------------------------------------------------------------- #
# TAB 1: Live Screener (Re-calculates dynamically on Capital change)
# --------------------------------------------------------------------------- #
with tab1:
    st.subheader("Monthly Orders & Capital Allocation")
    
    col_mode1, col_mode2 = st.columns([3, 2])
    with col_mode1:
        mode = st.radio(
            "Select Screener Mode:",
            ["Initial / Fresh Allocation (Scale to entered Capital)", 
             "Monthly Rebalance (Compare against Active Portfolio)"],
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
                "shares": shares,
                "est_value": round(shares * cmp_val, 2),
                "reason": f"Rank #{row['rank']} (Score: {row['score']:.2f})"
            })
        df_orders = pd.DataFrame(allocations)

    # 2. Monthly Rebalance Mode
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

        st.markdown("### Actionable Order Sheet")
        
        def style_action(val):
            if val == "BUY":
                return "background-color: #d1e7dd; color: #0f5132; font-weight: bold;"
            elif val == "SELL":
                return "background-color: #f8d7da; color: #842029; font-weight: bold;"
            elif val == "HOLD":
                return "background-color: #fff3cd; color: #664d03; font-weight: bold;"
            return ""

        display_df = df_orders[["action", "symbol", "company", "rank", "cmp", "shares", "est_value", "reason"]]
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
                            "invested": r["est_value"]
                        })
                ms.save_current_portfolio(pd.DataFrame(new_portfolio))
                st.success("✅ Portfolio saved! Check Tab 2 to view your active holdings.")
        
        with btn_c2:
            csv_data = display_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Download Order Sheet (CSV)",
                data=csv_data,
                file_name=f"momentum_orders_{datetime.datetime.today().strftime('%Y-%m-%d')}.csv",
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
    > - **Strict Exit (Exit > 20):** 38.3% CAGR, 1,354 trades, ₹1,12,753 paid in fees & DP charges.
    > - **Buffer Exit (Exit > 40):** **39.2% CAGR**, 854 trades, **₹76,727 paid in fees** (Saved ₹36,000+ in friction).
    > - **Nifty 500 Index:** 13.4% CAGR, -38.3% Drawdown.
    """)
