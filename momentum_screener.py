#!/usr/bin/env python3
"""
Nifty 500 Momentum Monthly Screener
====================================
Generates monthly rebalance signals and order execution sheets for a ₹1 Lakh
(or custom capital) momentum portfolio.

Features:
- Universe: Nifty 500 (from ind_nifty500list.csv)
- Momentum Formula: Composite risk-adjusted momentum (3M, 6M, 9M returns normalized by volatility)
- Caching: Uses `cache/prices.pkl` if available for instant execution (< 1 sec)
- Rebalance Rules:
    - Retain existing holdings if rank <= exit_rank (buffer rule, default: 40)
    - Fill available slots from Top 20 new entrants
    - Exact whole-share quantity and budget allocation per stock
- Tracks existing portfolio via `current_portfolio.csv`
- Generates `rebalance_orders_<date>.csv` with BUY/SELL/HOLD instructions.

Usage:
  # First time run (initializes your portfolio with the top 20 stocks):
  python momentum_screener.py --init --commit

  # Monthly rebalance run (compares current holdings vs new ranks):
  python momentum_screener.py --commit

  # Test without saving:
  python momentum_screener.py
"""

import argparse
import datetime
import os
import sys
import numpy as np
import pandas as pd
import yfinance as yf

# Resolve all paths relative to the script location (so it works from any directory)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_UNIVERSE = os.path.join(BASE_DIR, "ind_nifty500list.csv")
PORTFOLIO_FILE = os.path.join(BASE_DIR, "current_portfolio.csv")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "prices.pkl")


def load_universe(csv_path):
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Universe file {csv_path} not found.")
    df = pd.read_csv(csv_path)
    col = [c for c in df.columns if c.strip().lower() == "symbol"][0]
    name_col = [c for c in df.columns if "company" in c.strip().lower() or "name" in c.strip().lower()]
    name_col = name_col[0] if name_col else col
    mapping = dict(zip(df[col].astype(str).str.strip() + ".NS", df[name_col].astype(str).str.strip()))
    mapping.update(dict(zip(df[col].astype(str).str.strip(), df[name_col].astype(str).str.strip())))
    tickers = [f"{s.strip()}.NS" for s in df[col].dropna().unique()]
    return tickers, mapping


def load_or_fetch_prices(tickers, refresh=False):
    """
    Loads price history from local cache if present, otherwise downloads from yfinance.
    """
    if os.path.exists(CACHE_FILE) and not refresh:
        print(f"[*] Loading cached price data from {CACHE_FILE} ...")
        o, c, v, b = pd.read_pickle(CACHE_FILE)
        return c, v

    print(f"[*] Downloading market data for {len(tickers)} stocks via yfinance ...")
    os.makedirs(CACHE_DIR, exist_ok=True)
    batch_size = 50
    opens, closes, vols = [], [], []

    # Download at least 3-4 years so any selected historical date has sufficient lookback
    start_date = (datetime.datetime.today() - datetime.timedelta(days=1200)).strftime("%Y-%m-%d")
    for i in range(0, len(tickers), batch_size):
        chunk = tickers[i : i + batch_size]
        print(f"    Downloading {i + 1} to {min(i + batch_size, len(tickers))}...")
        try:
            d = yf.download(chunk, start=start_date, auto_adjust=True, progress=False, threads=True, group_by="column")
            if d is None or d.empty:
                continue
            if not isinstance(d.columns, pd.MultiIndex):
                d.columns = pd.MultiIndex.from_product([d.columns, chunk[:1]])
            opens.append(d["Open"])
            closes.append(d["Close"])
            vols.append(d["Volume"])
        except Exception as e:
            print(f"    Warning: batch failed: {e}")

    o = pd.concat(opens, axis=1).sort_index().ffill()
    c = pd.concat(closes, axis=1).sort_index().ffill()
    v = pd.concat(vols, axis=1).sort_index().ffill()

    bench = yf.download("^CRSLDX", start=start_date, auto_adjust=True, progress=False)["Close"]
    if isinstance(bench, pd.DataFrame):
        bench = bench.iloc[:, 0]
    bench = bench.reindex(c.index).ffill()

    pd.to_pickle((o, c, v, bench), CACHE_FILE)
    return c, v


def compute_momentum_ranks(close_df, volume_df, lookbacks=(63, 126, 189), vol_window=252):
    """
    Computes cross-sectional momentum score:
    Score = average z-score of (Return_L / Volatility) for L in (3M, 6M, 9M).
    """
    close_np = close_df.values.astype(float)
    cols = list(close_df.columns)
    e = len(close_np) - 1

    # 1-year annualized volatility
    v_start = max(0, e - vol_window)
    window = close_np[v_start : e + 1]
    logret = np.diff(np.log(window), axis=0)
    vol = np.nanstd(logret, axis=0, ddof=1) * np.sqrt(252)

    valid = np.isfinite(close_np[e]) & (np.isfinite(window).sum(axis=0) >= 0.8 * len(window))
    valid &= np.isfinite(vol) & (vol > 0.05)

    for lb in lookbacks:
        if e >= lb:
            valid &= np.isfinite(close_np[e - lb])
        else:
            valid[:] = False

    # Liquidity check
    liq_window = min(126, len(close_np) - 1)
    val_np = close_np * volume_df.values.astype(float)
    med_turnover = np.nanmedian(val_np[e - liq_window : e + 1], axis=0)
    valid &= np.isfinite(med_turnover)
    if valid.sum() > 20:
        cutoff = np.percentile(med_turnover[valid], 10)
        valid &= med_turnover >= cutoff

    # Compute all standard return windows for display
    return_dict = {}
    for lb in (63, 126, 189):
        if e >= lb:
            return_dict[lb] = close_np[e] / close_np[e - lb] - 1.0

    # Build composite z-score strictly from the user's selected lookbacks
    zs = []
    with np.errstate(invalid="ignore", divide="ignore"):
        for lb in lookbacks:
            if lb in return_dict:
                ret = return_dict[lb]
                ratio = ret / np.where(valid, vol, np.nan)
                m = np.nanmean(ratio[valid])
                s = np.nanstd(ratio[valid], ddof=1)
                zs.append((ratio - m) / s)

        if zs:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                composite_score = np.nanmean(np.vstack(zs), axis=0)
        else:
            composite_score = np.full(len(cols), np.nan)
    composite_score[~valid] = np.nan

    latest_prices = close_np[e]
    latest_date_str = pd.to_datetime(close_df.index[e]).strftime("%d-%b-%Y")
    results = []
    for idx, col in enumerate(cols):
        if not valid[idx] or np.isnan(composite_score[idx]):
            continue
        results.append({
            "ticker": col,
            "symbol": col.replace(".NS", ""),
            "cmp": round(latest_prices[idx], 2),
            "cmp_date": latest_date_str,
            "ret_3m_%": round(return_dict[63][idx] * 100, 1) if 63 in return_dict else 0.0,
            "ret_6m_%": round(return_dict[126][idx] * 100, 1) if 126 in return_dict else 0.0,
            "ret_9m_%": round(return_dict[189][idx] * 100, 1) if 189 in return_dict else 0.0,
            "vol_ann_%": round(vol[idx] * 100, 1),
            "score": composite_score[idx]
        })

    rank_df = pd.DataFrame(results)
    rank_df = rank_df.sort_values(by="score", ascending=False).reset_index(drop=True)
    rank_df["rank"] = rank_df.index + 1
    return rank_df


def load_current_portfolio():
    if not os.path.exists(PORTFOLIO_FILE):
        return pd.DataFrame(columns=["symbol", "ticker", "shares", "avg_price", "invested"])
    return pd.read_csv(PORTFOLIO_FILE)


def save_current_portfolio(df):
    df.to_csv(PORTFOLIO_FILE, index=False)
    print(f"[✓] Saved updated portfolio to {PORTFOLIO_FILE}")


def generate_rebalance_orders(rank_df, name_mapping, capital=50000, n_hold=10, exit_rank=40):
    """
    Evaluates current holdings against new ranks and allocates capital.
    """
    current_df = load_current_portfolio()
    
    rank_lookup = dict(zip(rank_df["symbol"], rank_df["rank"]))
    cmp_lookup = dict(zip(rank_df["symbol"], rank_df["cmp"]))
    date_lookup = dict(zip(rank_df["symbol"], rank_df["cmp_date"])) if "cmp_date" in rank_df.columns else {}
    latest_date_str = rank_df["cmp_date"].iloc[0] if "cmp_date" in rank_df.columns and not rank_df.empty else datetime.datetime.today().strftime("%d-%b-%Y")

    decisions = []
    held_to_keep = []
    
    for _, row in current_df.iterrows():
        sym = str(row["symbol"]).strip()
        sh = int(row["shares"])
        avg_px = float(row["avg_price"])
        curr_px = cmp_lookup.get(sym, avg_px)
        curr_rank = rank_lookup.get(sym, 9999)
        curr_date = date_lookup.get(sym, latest_date_str)
        curr_val = round(sh * curr_px, 2)
        pnl = round(curr_val - (sh * avg_px), 2)
        pnl_pct = round((pnl / (sh * avg_px)) * 100, 2) if (sh * avg_px) > 0 else 0.0

        if curr_rank <= exit_rank:
            decisions.append({
                "action": "HOLD",
                "symbol": sym,
                "company": name_mapping.get(sym, sym),
                "rank": curr_rank,
                "cmp": curr_px,
                "cmp_date": curr_date,
                "shares": sh,
                "est_value": curr_val,
                "pnl": pnl,
                "pnl_%": pnl_pct,
                "reason": f"Rank #{curr_rank} <= exit threshold #{exit_rank}"
            })
            held_to_keep.append(sym)
        else:
            decisions.append({
                "action": "SELL",
                "symbol": sym,
                "company": name_mapping.get(sym, sym),
                "rank": curr_rank,
                "cmp": curr_px,
                "cmp_date": curr_date,
                "shares": sh,
                "est_value": curr_val,
                "pnl": pnl,
                "pnl_%": pnl_pct,
                "reason": f"Rank #{curr_rank} fell below #{exit_rank}"
            })

    num_kept = len(held_to_keep)
    slots_to_fill = max(0, n_hold - num_kept)
    
    kept_value = sum(d["est_value"] for d in decisions if d["action"] == "HOLD")
    free_capital = max(0.0, capital - kept_value)
    slot_budget = (free_capital / slots_to_fill) if slots_to_fill > 0 else 0.0

    print("\n" + "=" * 90)
    print(f"REBALANCE SUMMARY: Target Holdings = {n_hold} | Retained = {num_kept} | New Buys = {slots_to_fill}")
    print(f"Total Capital = Rs {capital:,.0f} | Retained Value = Rs {kept_value:,.0f} | Capital for New Buys = Rs {free_capital:,.0f}")
    if slots_to_fill > 0:
        print(f"Budget per new slot = ~Rs {slot_budget:,.0f}")
    print("=" * 90)

    new_buys = []
    for _, row in rank_df.iterrows():
        if len(new_buys) >= slots_to_fill:
            break
        sym = row["symbol"]
        cmp_val = row["cmp"]
        
        if sym in held_to_keep:
            continue
            
        if cmp_val > slot_budget:
            continue
            
        shares_to_buy = int(slot_budget // cmp_val)
        if shares_to_buy < 1:
            continue

        est_invest = round(shares_to_buy * cmp_val, 2)
        new_buys.append({
            "action": "BUY",
            "symbol": sym,
            "company": name_mapping.get(sym, sym),
            "rank": row["rank"],
            "cmp": cmp_val,
            "cmp_date": row.get("cmp_date", latest_date_str),
            "shares": shares_to_buy,
            "est_value": est_invest,
            "pnl": 0.0,
            "pnl_%": 0.0,
            "reason": f"Rank #{row['rank']} (Score: {row['score']:.2f})"
        })

    all_orders = pd.DataFrame(decisions + new_buys)
    return all_orders, rank_df


def main():
    parser = argparse.ArgumentParser(description="Nifty 500 Monthly Momentum Screener")
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE, help="Path to Nifty 500 CSV")
    parser.add_argument("--capital", type=float, default=50000, help="Total portfolio capital (Rs)")
    parser.add_argument("--n-hold", type=int, default=10, help="Number of stocks to hold (default 10)")
    parser.add_argument("--exit-rank", type=int, default=40, help="Exit buffer rank threshold (default 40)")
    parser.add_argument("--init", action="store_true", help="Initialize portfolio with fresh top 20")
    parser.add_argument("--commit", action="store_true", help="Save the resulting portfolio to current_portfolio.csv")
    parser.add_argument("--refresh", action="store_true", help="Force fresh download from Yahoo Finance")
    args = parser.parse_args()

    print("[*] Starting Nifty 500 Momentum Monthly Screener")
    tickers, name_mapping = load_universe(args.universe)
    print(f"[*] Universe loaded: {len(tickers)} symbols from {args.universe}")

    close_df, volume_df = load_or_fetch_prices(tickers, refresh=args.refresh)
    print(f"[*] Price data loaded: {close_df.shape[0]} trading days, latest date: {close_df.index[-1].date()}")

    rank_df = compute_momentum_ranks(close_df, volume_df)
    print(f"[*] Computed momentum scores for {len(rank_df)} eligible stocks.")

    today_str = datetime.datetime.today().strftime("%Y-%m-%d")
    rank_file = os.path.join(BASE_DIR, f"nifty500_momentum_rank_{today_str}.csv")
    rank_df.to_csv(rank_file, index=False)
    print(f"[✓] Saved full momentum ranking to {rank_file}")

    if args.init and os.path.exists(PORTFOLIO_FILE):
        print(f"[*] Resetting existing {PORTFOLIO_FILE} for initial portfolio creation...")
        os.remove(PORTFOLIO_FILE)

    orders_df, _ = generate_rebalance_orders(
        rank_df,
        name_mapping,
        capital=args.capital,
        n_hold=args.n_hold,
        exit_rank=args.exit_rank
    )

    order_file = os.path.join(BASE_DIR, f"rebalance_orders_{today_str}.csv")
    orders_df.to_csv(order_file, index=False)
    print(f"\n[✓] Generated Rebalance Orders Sheet: {order_file}\n")

    display_cols = ["action", "symbol", "company", "rank", "cmp", "cmp_date", "shares", "est_value", "reason"]
    print(orders_df[display_cols].to_string(index=False))

    if args.commit:
        new_portfolio = []
        for _, r in orders_df.iterrows():
            if r["action"] in ["HOLD", "BUY"]:
                new_portfolio.append({
                    "symbol": r["symbol"],
                    "company": r["company"],
                    "ticker": f"{r['symbol']}.NS",
                    "shares": r["shares"],
                    "avg_price": r["cmp"],
                    "invested": r["est_value"]
                })
        save_current_portfolio(pd.DataFrame(new_portfolio))


if __name__ == "__main__":
    main()
