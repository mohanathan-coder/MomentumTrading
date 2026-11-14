#!/usr/bin/env python3
"""
Nifty 500 Momentum Stock Screener & Portfolio Reconciler
========================================================
Interactive momentum trading web app.
Features:
- Automated reconciliation of your bought stocks from Excel / CSV.
- Classifies each holding into CONTINUE TO HOLD, EXIT / SELL, or NEW BUY.
- Multi-timeframe momentum scoring (3M, 6M, 9M).
- As-of date selector for any past or present market close.
"""

import os
import io
import datetime
import pandas as pd
import numpy as np
import streamlit as st

import momentum_screener as ms

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(
    page_title="Nifty 500 Momentum & Reconciler",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📈 Nifty 500 Momentum Trading & Reconciler")
st.caption("Quantitative Multi-Timeframe Momentum • Portfolio Reconciliation & Rebalance Engine")

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
use_custom_date = st.sidebar.checkbox("Input Specific Closing Date", value=False, help="Check this to evaluate as of any date (e.g. 21/10/2026)")

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
    st.info(f"⏳ **Ranking Blend:** **`{lookback_tag}`** *(Buffer: Rank {exit_rank})*")

# --------------------------------------------------------------------------- #
# Stock Sizing Algorithm (Top Stocks for Fresh Allocation)
# --------------------------------------------------------------------------- #
allocations = []
skipped_stocks = []

for _, row in rank_df.iterrows():
    if len(allocations) >= n_hold:
        break
    sym = row["symbol"]
    cmp_val = row["cmp"]
    
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

tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 Top Stocks Screener",
    "📋 Buffer Watchlist",
    "🔄 Portfolio Reconciliation",
    "📜 Strategy Rules & Presets"
])

# --------------------------------------------------------------------------- #
# TAB 1: Top Stocks Screener (Fresh Allocation)
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
            mime="text/csv"
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
    4. If it has fallen **above Rank {exit_rank}** (or is missing), exit the stock (**SELL**) and pick a replacement from **Tab 1 (Top Stocks Screener)** or **Tab 3 (Portfolio Reconciliation)**.
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
# TAB 3: Portfolio Reconciliation Engine (Upload Excel / CSV)
# --------------------------------------------------------------------------- #
with tab3:
    st.subheader(f"Portfolio Reconciliation as of {cmp_date_str}")
    st.markdown(rf"""
    Upload the list of stocks you bought on an earlier date (e.g., **13/09/2026**).
    The engine will compare your stocks against market rankings on **{cmp_date_str}** and classify them into:
    * 🟢 **HOLD:** Rank $\le {exit_rank}$ *(Keep position)*
    * 🔴 **EXIT:** Rank $> {exit_rank}$ *(Sell at open)*
    * 🔵 **NEW BUY:** Top replacement stocks to fill vacant slots.
    """)

    # Download Sample Excel / CSV Template
    sample_df = pd.DataFrame({
        "Symbol": ["STLTECH", "WELCORP", "HFCL", "CUPID", "LAURUSLABS"],
        "Shares": [11, 3, 42, 35, 5],
        "Buy Price": [897.40, 2676.60, 233.47, 280.00, 1968.16]
    })
    
    col_up1, col_up2 = st.columns([3, 1])
    with col_up1:
        uploaded_file = st.file_uploader(
            "📤 Upload Your Bought Stocks File (Excel .xlsx or CSV .csv):",
            type=["xlsx", "csv"],
            help="File should have at least a 'Symbol' column. 'Shares' and 'Buy Price' columns are optional."
        )
    with col_up2:
        st.write("")
        st.write("")
        sample_csv = sample_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Sample Template (CSV)",
            data=sample_csv,
            file_name="my_bought_stocks_template.csv",
            mime="text/csv",
            help="Click to download a ready-to-fill sample template."
        )

    # Optional manual quick-paste text area (empty by default)
    with st.expander("Or Paste Stock Symbols Directly (No file required)"):
        manual_symbols = st.text_area(
            "Enter symbols separated by comma or new line:",
            value="",
            placeholder="e.g. STLTECH, WELCORP, HFCL, CUPID, LAURUSLABS"
        )

    user_holdings_df = None
    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith(".xlsx"):
                user_holdings_df = pd.read_excel(uploaded_file)
            else:
                user_holdings_df = pd.read_csv(uploaded_file)
            st.success(f"✅ Loaded file: `{uploaded_file.name}` ({len(user_holdings_df)} stocks)")
        except Exception as e:
            st.error(f"Error reading uploaded file: {e}")
    elif manual_symbols.strip():
        # Parse text area
        syms = [s.strip().upper().replace(".NS", "") for s in manual_symbols.replace("\n", ",").split(",") if s.strip()]
        if syms:
            user_holdings_df = pd.DataFrame({"Symbol": syms, "Shares": [1]*len(syms), "Buy Price": [0.0]*len(syms)})

    if user_holdings_df is not None and not user_holdings_df.empty:
        # Normalize Column Names
        sym_col = [c for c in user_holdings_df.columns if any(k in c.lower() for k in ["sym", "stock", "ticker", "scrip"])]
        sh_col = [c for c in user_holdings_df.columns if any(k in c.lower() for k in ["share", "qty", "quantity"])]
        px_col = [c for c in user_holdings_df.columns if any(k in c.lower() for k in ["buy", "price", "cost", "avg", "rate"])]

        if not sym_col:
            st.error("Uploaded file must have a 'Symbol' or 'Stock' column.")
        else:
            s_col = sym_col[0]
            user_holdings_df["CleanSymbol"] = user_holdings_df[s_col].astype(str).str.strip().str.upper().str.replace(".NS", "")
            
            rank_lookup = dict(zip(rank_df["symbol"], rank_df["rank"]))
            cmp_lookup = dict(zip(rank_df["symbol"], rank_df["cmp"]))

            reconciled_rows = []
            retained_symbols = set()
            freed_cash = 0.0
            total_current_val = 0.0
            total_invested_val = 0.0

            # 1. Process Existing Holdings (HOLD vs SELL)
            for _, r in user_holdings_df.iterrows():
                sym = r["CleanSymbol"]
                sh = int(r[sh_col[0]]) if sh_col and pd.notna(r[sh_col[0]]) and r[sh_col[0]] > 0 else 1
                curr_cmp = cmp_lookup.get(sym, None)
                
                # If buy price missing, default to CMP
                if px_col and pd.notna(r[px_col[0]]) and r[px_col[0]] > 0:
                    bp = float(r[px_col[0]])
                else:
                    bp = curr_cmp if curr_cmp is not None else 0.0

                curr_rank = rank_lookup.get(sym, 9999)

                if curr_cmp is not None:
                    curr_val = round(sh * curr_cmp, 2)
                    inv_val = round(sh * bp, 2)
                    pnl = round(curr_val - inv_val, 2)
                    pnl_pct = round((pnl / inv_val) * 100, 2) if inv_val > 0 else 0.0
                else:
                    curr_cmp = bp
                    curr_val = round(sh * bp, 2)
                    inv_val = curr_val
                    pnl = 0.0
                    pnl_pct = 0.0

                if curr_rank <= exit_rank:
                    action = "HOLD"
                    status = f"✅ Keep (Rank #{curr_rank} <= Buffer #{exit_rank})"
                    retained_symbols.add(sym)
                    total_current_val += curr_val
                    total_invested_val += inv_val
                else:
                    action = "SELL"
                    status = f"🔴 Exit (Rank #{curr_rank} fell below #{exit_rank})" if curr_rank != 9999 else "🔴 Exit (Fell out of Nifty 500)"
                    freed_cash += curr_val
                    total_invested_val += inv_val

                reconciled_rows.append({
                    "Action": action,
                    "Symbol": sym,
                    "Company": name_mapping.get(sym, sym),
                    "Rank on " + cmp_date_str: curr_rank if curr_rank != 9999 else "Out",
                    "Buy Price (₹)": bp,
                    "CMP (₹)": curr_cmp,
                    "Shares": sh,
                    "Invested (₹)": inv_val,
                    "Current Value (₹)": curr_val,
                    "P&L (₹)": pnl,
                    "P&L %": pnl_pct,
                    "Reason / Status": status
                })

            # 2. Process Replacement Buys (NEW BUY)
            num_retained = len(retained_symbols)
            open_slots = max(0, n_hold - num_retained)
            
            # Available capital for new buys: freed cash from sells + remaining unallocated capital
            unallocated_cash = max(0.0, capital - (total_current_val + freed_cash))
            total_buy_budget = freed_cash + unallocated_cash
            slot_new_budget = (total_buy_budget / open_slots) if open_slots > 0 else 0.0

            new_buys_count = 0
            for _, row in rank_df.iterrows():
                if new_buys_count >= open_slots:
                    break
                sym = row["symbol"]
                cmp_val = row["cmp"]
                
                if sym in retained_symbols:
                    continue
                if cmp_val > slot_new_budget:
                    continue
                    
                shares_to_buy = int(slot_new_budget // cmp_val)
                if shares_to_buy < 1:
                    continue

                est_invest = round(shares_to_buy * cmp_val, 2)
                reconciled_rows.append({
                    "Action": "BUY",
                    "Symbol": sym,
                    "Company": name_mapping.get(sym, sym),
                    "Rank on " + cmp_date_str: int(row["rank"]),
                    "Buy Price (₹)": cmp_val,
                    "CMP (₹)": cmp_val,
                    "Shares": shares_to_buy,
                    "Invested (₹)": est_invest,
                    "Current Value (₹)": est_invest,
                    "P&L (₹)": 0.0,
                    "P&L %": 0.0,
                    "Reason / Status": f"🔵 New Entrant (Rank #{row['rank']}, Score: {row['score']:.2f})"
                })
                new_buys_count += 1
                total_current_val += est_invest

            df_reconciled = pd.DataFrame(reconciled_rows)

            # Display Summary Metrics
            holds = (df_reconciled["Action"] == "HOLD").sum()
            sells = (df_reconciled["Action"] == "SELL").sum()
            buys = (df_reconciled["Action"] == "BUY").sum()
            total_pnl = df_reconciled[df_reconciled["Action"].isin(["HOLD", "SELL"])]["P&L (₹)"].sum()
            total_pnl_pct = (total_pnl / total_invested_val * 100) if total_invested_val > 0 else 0.0

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("🟢 Keep / HOLD", holds)
            m2.metric("🔴 Exit / SELL", sells)
            m3.metric("🔵 New BUYs", buys)
            m4.metric("Portfolio Value", f"₹{total_current_val:,.2f}")
            m5.metric("Total P&L", f"₹{total_pnl:,.2f}", f"{total_pnl_pct:+.2f}%")

            # Color Styling
            def style_action_recon(val):
                if val == "HOLD":
                    return "background-color: #d1e7dd; color: #0f5132; font-weight: bold;"
                elif val == "SELL":
                    return "background-color: #f8d7da; color: #842029; font-weight: bold;"
                elif val == "BUY":
                    return "background-color: #cff4fc; color: #055160; font-weight: bold;"
                return ""

            st.markdown(f"### Reconciled Action Plan *(Market Prices as of {cmp_date_str})*")
            st.dataframe(
                df_reconciled.style.map(style_action_recon, subset=["Action"]).format({
                    "Buy Price (₹)": "₹{:.2f}",
                    "CMP (₹)": "₹{:.2f}",
                    "Invested (₹)": "₹{:.2f}",
                    "Current Value (₹)": "₹{:.2f}",
                    "P&L (₹)": "₹{:.2f}",
                    "P&L %": "{:+.2f}%"
                }),
                use_container_width=True,
                hide_index=True
            )

            # Download Reconciled Orders
            csv_reconciled = df_reconciled.to_csv(index=False).encode("utf-8")
            st.download_button(
                label=f"📥 Download Reconciled Rebalance Orders (CSV)",
                data=csv_reconciled,
                file_name=f"reconciled_orders_{cmp_date_str}.csv",
                mime="text/csv",
                type="primary"
            )
    else:
        st.info("ℹ️ **No portfolio data entered.**\n\nPlease upload an Excel (`.xlsx`) or CSV (`.csv`) file above, or paste your stock symbols in the text box above to view your reconciled action plan.")

# --------------------------------------------------------------------------- #
# TAB 4: Strategy Rules & Presets
# --------------------------------------------------------------------------- #
with tab4:
    st.subheader("📜 Quantitative Strategy Rules & Standard Presets")
    
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown("""
        ### 🚀 Preset 1: Aggressive Growth
        * **Capital:** **₹50,000** (or ₹30,000)
        * **Holdings:** **5 Stocks** (~₹10,000 per stock slot)
        * **Exit Buffer Rank:** **Rank 15** *(Sell only if rank > 15)*
        * **Performance Characteristics:**
          - **+99.0%** in 6-month test (Apr–Oct 2026: grew from ₹50,000 to ₹99,488)
          - **45.9% 7-Year CAGR** (2019–2026)
          - Multi-baggers have a massive 20% portfolio weight.
          - Low churn (~1 sell per month).
        """)
        
    with col_p2:
        st.markdown("""
        ### 🛡️ Preset 2: Balanced Stability
        * **Capital:** **₹1,00,000**
        * **Holdings:** **10 Stocks** (~₹10,000 per stock slot)
        * **Exit Buffer Rank:** **Rank 40** *(Sell only if rank > 40)*
        * **Performance Characteristics:**
          - **+44.9%** in 6-month test (Apr–Oct 2026: grew from ₹50,000 to ₹72,442)
          - **44.8% 7-Year CAGR** (2019–2026)
          - Proven lower drawdowns (-37%), giving a smoother equity curve.
          - Wide Rank 40 buffer saves ₹36,000+ in unnecessary broker & DP fees.
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
    * Look up each of your held stocks in **Tab 2 (Buffer Watchlist)** or **Tab 3 (Portfolio Reconciliation)**.
    * **If its rank $\le$ Exit Buffer:** **`HOLD`**. Do not sell, even if it had a minor red week.
    * **If its rank falls $>$ Exit Buffer:** **`SELL`**. Exit the entire position at market open.

    #### 3. Filling Vacant Slots (When to BUY)
    * Count your vacant slots: `Open Slots = Target Holdings - Retained Holdings`.
    * Look at **Tab 1 (Top Stocks Screener)** or **Tab 3 (Portfolio Reconciliation)**.
    * The engine automatically calculates the exact shares to buy for replacement stocks.

    #### 4. Whole-Share Sizing
    * India does not allow fractional shares. The app automatically sizes shares to fit within your slot budget so you never overspend or leave large cash unallocated.
    """)
