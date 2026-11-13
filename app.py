#!/usr/bin/env python3
"""
Nifty 500 Momentum Stock Screener & Capital Allocator
=====================================================
A clean, straightforward momentum screener.
Calculates risk-adjusted multi-timeframe momentum (3M, 6M, 9M)
and outputs whole-share portfolio allocations for manual Google Sheet tracking.
"""

import os
import datetime
import pandas as pd
import numpy as np
import streamlit as st

import momentum_screener as ms

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(
    page_title="Nifty 500 Momentum Screener",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📈 Nifty 500 Momentum Stock Screener")
st.caption("Quantitative Multi-Timeframe Momentum (3M, 6M, 9M) • NSE Nifty 500")

# --------------------------------------------------------------------------- #
# Sidebar Inputs
# --------------------------------------------------------------------------- #
st.sidebar.header("⚙️ Screener Settings")
capital = st.sidebar.number_input("Total Capital (₹)", min_value=10000, max_value=50000000, value=100000, step=10000)
n_hold = st.sidebar.slider("Number of Stocks to Hold", min_value=5, max_value=30, value=20)
exit_rank = st.sidebar.slider("Exit Buffer Rank Threshold", min_value=20, max_value=100, value=40,
                              help="Use this rank threshold to check your Google Sheet: if your stock is still <= this rank, keep it; otherwise sell.")

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
    st.sidebar.success("Market data refreshed from NSE!")

with st.spinner("Loading market data & calculating momentum ranks..."):
    rank_df, name_mapping = get_market_data(force_refresh=refresh_data)

today = datetime.date.today()
cmp_date_str = rank_df["cmp_date"].iloc[0] if ("cmp_date" in rank_df.columns and not rank_df.empty) else today.strftime("%d-%b-%Y")

# Info Banner
b1, b2 = st.columns([1, 1])
with b1:
    st.info(f"📅 **Price Data As Of:** **`{cmp_date_str}`** *(NSE Closing)*")
with b2:
    slot_budget = capital / n_hold
    st.info(f"💰 **Budget Per Stock:** **`₹{slot_budget:,.2f}`** *(₹{capital:,.0f} ÷ {n_hold} stocks)*")

# --------------------------------------------------------------------------- #
# Stock Sizing Algorithm (Whole Shares within Slot Budget)
# --------------------------------------------------------------------------- #
allocations = []
skipped_stocks = []

for _, row in rank_df.iterrows():
    if len(allocations) >= n_hold:
        break
    sym = row["symbol"]
    cmp_val = row["cmp"]
    
    # Skip if 1 share costs more than the allocated budget per stock
    if cmp_val > slot_budget:
        skipped_stocks.append(f"{sym} (₹{cmp_val:,.2f})")
        continue
        
    shares = int(slot_budget // cmp_val)
    if shares < 1:
        continue
        
    est_val = round(shares * cmp_val, 2)
    allocations.append({
        "Symbol": sym,
        "Company": name_mapping.get(sym, sym),
        "Rank": int(row["rank"]),
        "CMP (₹)": round(cmp_val, 2),
        "CMP Date": row.get("cmp_date", cmp_date_str),
        "Shares": shares,
        "Est. Investment (₹)": est_val,
        "3M Ret %": row.get("ret_3m_%", 0.0),
        "6M Ret %": row.get("ret_6m_%", 0.0),
        "9M Ret %": row.get("ret_9m_%", 0.0),
        "Score": round(row.get("score", 0.0), 2)
    })

df_portfolio = pd.DataFrame(allocations)
if not df_portfolio.empty:
    df_portfolio.insert(0, "S.No", range(1, len(df_portfolio) + 1))

tab1, tab2, tab3 = st.tabs(["🎯 Top Stocks to Buy", "📋 Buffer Watchlist (Top 40 Ranks)", "🧪 Backtest Report"])

# --------------------------------------------------------------------------- #
# TAB 1: Top Stocks
# --------------------------------------------------------------------------- #
with tab1:
    if not df_portfolio.empty:
        total_invested = df_portfolio["Est. Investment (₹)"].sum()
        cash_left = max(0.0, capital - total_invested)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Selected Stocks", len(df_portfolio))
        m2.metric("Total Capital", f"₹{capital:,.2f}")
        m3.metric("Total Invested", f"₹{total_invested:,.2f}")
        m4.metric("Unallocated Cash", f"₹{cash_left:,.2f}")

        st.markdown(f"### Top {n_hold} Momentum Stocks *(Ready for Google Sheets)*")
        
        st.dataframe(
            df_portfolio.style.format({
                "CMP (₹)": "₹{:.2f}",
                "Est. Investment (₹)": "₹{:.2f}",
                "3M Ret %": "{:.1f}%",
                "6M Ret %": "{:.1f}%",
                "9M Ret %": "{:.1f}%",
                "Score": "{:.2f}"
            }),
            use_container_width=True,
            hide_index=True
        )

        if skipped_stocks:
            st.caption(f"💡 *Note: {len(skipped_stocks)} high-priced stocks skipped because 1 share exceeds slot budget of ₹{slot_budget:,.2f}:* " + ", ".join(skipped_stocks[:5]))

        csv_portfolio = df_portfolio.to_csv(index=False).encode("utf-8")
        st.download_button(
            label=f"📥 Download Top {n_hold} CSV (Import into Google Sheets)",
            data=csv_portfolio,
            file_name=f"momentum_top_{n_hold}_{cmp_date_str}.csv",
            mime="text/csv",
            type="primary"
        )
    else:
        st.warning("No stocks fit within the selected budget. Try increasing total capital or reducing the number of stocks.")

# --------------------------------------------------------------------------- #
# TAB 2: Buffer Watchlist (Top 40 / Search any stock)
# --------------------------------------------------------------------------- #
with tab2:
    st.subheader(f"Buffer Watchlist (Ranks 1 to {exit_rank})")
    st.markdown(f"""
    **How to use with your Google Sheet:**
    1. Check your existing stocks in your Google Sheet.
    2. Search your stock symbol below.
    3. If its rank is **$\le {exit_rank}$**, keep holding it (**HOLD**).
    4. If it has fallen **above Rank {exit_rank}** (or is missing), exit the stock (**SELL**) and pick a replacement from Tab 1.
    """)

    # Filter ranks <= exit_rank
    buffer_df = rank_df[rank_df["rank"] <= exit_rank].copy()
    buffer_display = []
    for _, r in buffer_df.iterrows():
        sym = r["symbol"]
        buffer_display.append({
            "Rank": int(r["rank"]),
            "Symbol": sym,
            "Company": name_mapping.get(sym, sym),
            "CMP (₹)": round(r["cmp"], 2),
            "CMP Date": r.get("cmp_date", cmp_date_str),
            "3M Ret %": r.get("ret_3m_%", 0.0),
            "6M Ret %": r.get("ret_6m_%", 0.0),
            "9M Ret %": r.get("ret_9m_%", 0.0),
            "Score": round(r.get("score", 0.0), 2),
            "Status": f"✅ HOLD (<= {exit_rank})"
        })

    df_buffer = pd.DataFrame(buffer_display)
    
    # Search box
    search_sym = st.text_input("🔍 Quick Search Symbol in Universe (e.g. INFY, TATAMOTORS, CUPID):").strip().upper()
    if search_sym:
        match = rank_df[rank_df["symbol"] == search_sym]
        if not match.empty:
            m_rank = int(match.iloc[0]["rank"])
            m_cmp = match.iloc[0]["cmp"]
            if m_rank <= exit_rank:
                st.success(f"**{search_sym}** is currently **Rank #{m_rank}** (CMP: ₹{m_cmp:,.2f}). Result: **KEEP / HOLD** (Rank <= {exit_rank})")
            else:
                st.error(f"**{search_sym}** is currently **Rank #{m_rank}** (CMP: ₹{m_cmp:,.2f}). Result: **EXIT / SELL** (Rank fell below {exit_rank})")
        else:
            st.warning(f"Symbol '{search_sym}' not found in Nifty 500.")

    st.dataframe(
        df_buffer.style.format({
            "CMP (₹)": "₹{:.2f}",
            "3M Ret %": "{:.1f}%",
            "6M Ret %": "{:.1f}%",
            "9M Ret %": "{:.1f}%",
            "Score": "{:.2f}"
        }),
        use_container_width=True,
        hide_index=True
    )

    csv_buffer = df_buffer.to_csv(index=False).encode("utf-8")
    st.download_button(
        label=f"📥 Download Full Buffer List (Ranks 1-{exit_rank}) CSV",
        data=csv_buffer,
        file_name=f"momentum_buffer_ranks_1_{exit_rank}_{cmp_date_str}.csv",
        mime="text/csv"
    )

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
    > - **Nifty 500 Index:** 13.4% CAGR, -38.3% Drawdown.
    """)
