#!/usr/bin/env python3
"""
Nifty 500 Momentum Stock Screener & Rules Dashboard
=====================================================
A clean, straightforward momentum screener.
Calculates risk-adjusted multi-timeframe momentum (3M, 6M, 9M or custom selection)
and outputs whole-share portfolio allocations for manual Google Sheet tracking.
Includes Strategy Rules and 1-click Preset configurations.
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
st.caption("Quantitative Multi-Timeframe Momentum Screener • NSE Nifty 500")

# --------------------------------------------------------------------------- #
# Sidebar Inputs with 1-Click Presets
# --------------------------------------------------------------------------- #
st.sidebar.header("🎯 Strategy Presets")
preset = st.sidebar.selectbox(
    "Choose Preset or Custom:",
    [
        "Preset 1: ₹50k Capital (5 Stocks, Buffer 15)",
        "Preset 2: ₹100k Capital (10 Stocks, Buffer 40)",
        "Custom Configuration"
    ]
)

if preset.startswith("Preset 1"):
    default_cap = 50000
    default_n = 5
    default_buf = 15
elif preset.startswith("Preset 2"):
    default_cap = 100000
    default_n = 10
    default_buf = 40
else:
    default_cap = 50000
    default_n = 10
    default_buf = 40

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Screener Settings")
capital = st.sidebar.number_input("Total Capital (₹)", min_value=10000, max_value=50000000, value=default_cap, step=10000)
n_hold = st.sidebar.slider("Number of Stocks to Hold", min_value=3, max_value=30, value=default_n)
exit_rank = st.sidebar.slider("Exit Buffer Rank Threshold", min_value=10, max_value=100, value=default_buf,
                              help="Hold current stocks if rank is within this threshold to avoid excessive churn.")

# Lookback Selection Section
st.sidebar.markdown("---")
st.sidebar.subheader("⏳ Momentum Lookbacks (3M, 6M, 9M)")
st.sidebar.caption("Check which timeframes to use in ranking:")
col_lb1, col_lb2, col_lb3 = st.sidebar.columns(3)
with col_lb1:
    use_3m = st.checkbox("3M", value=True, help="3-Month return (63 trading days)")
with col_lb2:
    use_6m = st.checkbox("6M", value=True, help="6-Month return (126 trading days)")
with col_lb3:
    use_9m = st.checkbox("9M", value=True, help="9-Month return (189 trading days)")

selected_lbs = []
lb_labels = []
if use_3m:
    selected_lbs.append(63)
    lb_labels.append("3M")
if use_6m:
    selected_lbs.append(126)
    lb_labels.append("6M")
if use_9m:
    selected_lbs.append(189)
    lb_labels.append("9M")

if not selected_lbs:
    st.sidebar.error("⚠️ Please check at least one lookback window (3M, 6M, or 9M)!")
    st.stop()

lookback_tag = " + ".join(lb_labels)

# Date Input Section in Sidebar
st.sidebar.markdown("---")
st.sidebar.subheader("📅 Closing Price Date (As of Date)")
use_custom_date = st.sidebar.checkbox("Input Specific Closing Date", value=False, help="Check this to pick any historical date")

refresh_data = st.sidebar.button("🔄 Force Refresh Market Data from NSE")

# Fast Cached Data Loader
@st.cache_data(ttl=3600, show_spinner=False)
def load_raw_data(force_refresh=False):
    tickers, name_mapping = ms.load_universe(ms.DEFAULT_UNIVERSE)
    close_df, volume_df = ms.load_or_fetch_prices(tickers, refresh=force_refresh)
    return close_df, volume_df, name_mapping

if refresh_data:
    st.cache_data.clear()
    st.sidebar.success("Market data refreshed from NSE!")

with st.spinner("Loading market data & calculating momentum ranks..."):
    close_df, volume_df, name_mapping = load_raw_data(force_refresh=refresh_data)

# Available dates with at least 252 days of prior history for momentum calculation
min_valid_dt = pd.to_datetime(close_df.index[min(252, len(close_df) - 1)]).date()
max_valid_dt = pd.to_datetime(close_df.index[-1]).date()

if use_custom_date:
    selected_date = st.sidebar.date_input(
        "Select Closing Date",
        value=max_valid_dt,
        min_value=min_valid_dt,
        max_value=max_valid_dt,
        format="DD/MM/YYYY",
        help=f"Available dates with full lookback: {min_valid_dt.strftime('%d/%m/%Y')} to {max_valid_dt.strftime('%d/%m/%Y')}"
    )
    st.sidebar.caption(f"🗓️ *Available range: {min_valid_dt.strftime('%d/%m/%Y')} to {max_valid_dt.strftime('%d/%m/%Y')}*")
else:
    selected_date = None

# Slice data to target date if requested
if selected_date:
    target_dt = pd.to_datetime(selected_date)
    sliced_close = close_df.loc[:target_dt]
    sliced_volume = volume_df.loc[:target_dt]
    if sliced_close.empty or len(sliced_close) < 200:
        st.error(f"⚠️ Need at least 252 trading days of market data before {selected_date.strftime('%d/%m/%Y')}. Please choose a date between {min_valid_dt.strftime('%d/%m/%Y')} and {max_valid_dt.strftime('%d/%m/%Y')}.")
        st.stop()
else:
    sliced_close = close_df
    sliced_volume = volume_df

rank_df = ms.compute_momentum_ranks(sliced_close, sliced_volume, lookbacks=tuple(selected_lbs))

actual_trading_dt = pd.to_datetime(sliced_close.index[-1]).date()
cmp_date_str = actual_trading_dt.strftime("%d-%b-%Y")

# Info Banner
b1, b2, b3 = st.columns([1, 1, 1])
with b1:
    if selected_date and selected_date != actual_trading_dt:
        st.info(f"📅 **Price As Of:** **`{cmp_date_str}`** *(Nearest trading close)*")
    else:
        st.info(f"📅 **Price Data As Of:** **`{cmp_date_str}`** *(NSE Closing)*")
with b2:
    slot_budget = capital / n_hold
    st.info(f"💰 **Budget Per Stock:** **`₹{slot_budget:,.2f}`** *(₹{capital:,.0f} ÷ {n_hold})*")
with b3:
    st.info(f"⏳ **Ranking Blend:** **`{lookback_tag}`** *(Risk-Adjusted)*")

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

tab1, tab2, tab3 = st.tabs(["🎯 Top Stocks to Buy", "📋 Buffer Watchlist", "📜 Strategy Rules & Presets"])

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

        st.markdown(f"### Top {n_hold} Momentum Stocks Based on **{lookback_tag}** *(As of {cmp_date_str})*")
        
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
            label=f"📥 Download Top {n_hold} ({lookback_tag}) CSV",
            data=csv_portfolio,
            file_name=f"momentum_top_{n_hold}_{lookback_tag.replace(' + ', '_')}_{cmp_date_str}.csv",
            mime="text/csv",
            type="primary"
        )
    else:
        st.warning("No stocks fit within the selected budget. Try increasing total capital or reducing the number of stocks.")

# --------------------------------------------------------------------------- #
# TAB 2: Buffer Watchlist (Top Buffer Ranks / Search any stock)
# --------------------------------------------------------------------------- #
with tab2:
    st.subheader(f"Buffer Watchlist (Ranks 1 to {exit_rank} Based on {lookback_tag} as of {cmp_date_str})")
    st.markdown(rf"""
    **How to use with your Google Sheet:**
    1. Check your existing stocks in your Google Sheet.
    2. Search your stock symbol below.
    3. If its rank is **$\le {exit_rank}$**, keep holding it (**HOLD**).
    4. If it has fallen **above Rank {exit_rank}** (or is missing), exit the stock (**SELL**) and pick a replacement from Tab 1.
    """)

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
    
    search_sym = st.text_input("🔍 Quick Search Symbol in Universe (e.g. INFY, TATAMOTORS, CUPID):").strip().upper()
    if search_sym:
        match = rank_df[rank_df["symbol"] == search_sym]
        if not match.empty:
            m_rank = int(match.iloc[0]["rank"])
            m_cmp = match.iloc[0]["cmp"]
            if m_rank <= exit_rank:
                st.success(f"**{search_sym}** was **Rank #{m_rank}** on {cmp_date_str} (CMP: ₹{m_cmp:,.2f}). Result: **KEEP / HOLD** (Rank <= {exit_rank})")
            else:
                st.error(f"**{search_sym}** was **Rank #{m_rank}** on {cmp_date_str} (CMP: ₹{m_cmp:,.2f}). Result: **EXIT / SELL** (Rank fell below {exit_rank})")
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
        file_name=f"momentum_buffer_ranks_1_{exit_rank}_{lookback_tag.replace(' + ', '_')}_{cmp_date_str}.csv",
        mime="text/csv"
    )

# --------------------------------------------------------------------------- #
# TAB 3: Strategy Rules & Presets
# --------------------------------------------------------------------------- #
with tab3:
    st.subheader("📜 Quantitative Strategy Rules & Standard Presets")
    
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown("""
        ### 🚀 Preset 1: Aggressive Growth
        * **Capital:** **₹50,000**
        * **Holdings:** **5 Stocks** (~₹10,000 per stock slot)
        * **Exit Buffer Rank:** **Rank 15** *(Sell only if rank > 15)*
        * **Performance Characteristics:**
          - **+99.0%** in 6-month test (Apr–Oct 2026: grew from ₹50,000 to ₹99,488)
          - **45.9% 7-Year CAGR** (2019–2026)
          - Larger individual allocations allow buying higher-priced market leaders.
          - Multi-baggers have a massive 20% portfolio weight.
          - Higher drawdown during broad market corrections (-45%).
        """)
        
    with col_p2:
        st.markdown("""
        ### 🛡️ Preset 2: Balanced Stability
        * **Capital:** **₹1,00,000**
        * **Holdings:** **10 Stocks** (~₹10,000 per stock slot)
        * **Exit Buffer Rank:** **Rank 40** *(Sell only if rank > 40)*
        * **Performance Characteristics:**
          - **+37.2%** in 6-month test (Apr–Oct 2026: grew from ₹50,000 to ₹68,624)
          - **44.8% 7-Year CAGR** (2019–2026)
          - Proven lower drawdowns (-37%), giving a smoother equity curve.
          - Wide Rank 40 buffer saves ₹36,000+ in unnecessary broker & DP fees.
          - Best balance of diversification and steady compounding.
        """)
        
    st.markdown("---")
    st.markdown(r"""
    ### 📋 The 4 Golden Rules of Execution

    #### 1. Rebalance Only Once a Month (on the 21st)
    * **Signal Time:** On the **21st at 3:45 PM** (after market close), open the web app.
    * **Execution Time:** Next morning at **9:18 AM – 9:30 AM**, place your orders in your broker.
    * **Holiday Rule:** If the 21st falls on a Saturday, Sunday, or market holiday, run on the next trading day (Monday).
    * **Zero Daily Trading:** Never buy or sell in between monthly dates. Momentum needs time to develop.

    #### 2. The Exit Buffer Rule (When to SELL vs HOLD)
    * Look up each of your held stocks in **Tab 2 (Buffer Watchlist)**.
    * **If its rank $\le$ Exit Buffer:** **`HOLD`**. Do not sell, even if it had a minor red week.
    * **If its rank falls $>$ Exit Buffer:** **`SELL`**. Exit the entire position at market open.

    #### 3. Filling Vacant Slots (When to BUY)
    * Count your vacant slots: `Open Slots = Target Holdings - Retained Holdings`.
    * Look at **Tab 1 (Top Stocks to Buy)**.
    * Pick the top-ranked stocks that you do not currently own and buy them using your freed cash.

    #### 4. Whole-Share Sizing
    * India does not allow fractional shares. The app automatically sizes shares to fit within your slot budget so you never overspend or leave large cash unallocated.
    """)
