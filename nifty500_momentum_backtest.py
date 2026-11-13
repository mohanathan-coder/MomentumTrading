#!/usr/bin/env python3
"""
Nifty 500 momentum backtest
===========================
Strategy
  * Universe : Nifty 500 (CSV with a 'Symbol' column from niftyindices.com)
  * Score    : average cross-sectional z-score of (return / volatility) over
               3, 6 and 9 month windows (63 / 126 / 189 trading days)
  * Hold     : top N stocks (default 20), equal weight at entry, whole shares
  * Rebalance: every 21 trading days. Signal on the close, trade at NEXT day's open
  * Exit rule: sell a holding when its rank falls below --exit-ranks
               (20 = your original rule, 40 = buffer version). New buys
               come only from the top N.
  * Costs    : STT, other charges, slippage, brokerage, DP charge per sell
  * Tax      : STCG 20% (<=12 months), LTCG 12.5% above Rs 1.25 lakh, +4% cess,
               settled at each financial-year end

Setup
  pip install pandas numpy matplotlib yfinance
Run
  python nifty500_momentum_backtest.py --universe ind_nifty500list.csv \
         --start 2015-01-01 --exit-ranks 20 40

WARNINGS
  * Uses TODAY's Nifty 500 list -> survivorship bias. Results will look better
    than reality. Treat them as an upper bound.
  * Cost/tax inputs are simplified assumptions. Check your broker's charges.
  * Not investment or tax advice.
"""
import argparse
import os
import warnings
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# --------------------------------------------------------------------------- #
# Parameters
# --------------------------------------------------------------------------- #
@dataclass
class Params:
    capital: float = 100_000
    n_hold: int = 20
    exit_rank: int = 40            # keep a holding while its rank <= exit_rank
    rebalance_days: int = 21
    lookbacks: tuple = (63, 126, 189)   # 3, 6, 9 months
    skip_days: int = 0             # set 21 to skip the most recent month
    vol_window: int = 252
    liquidity_window: int = 126
    liquidity_cut: float = 0.10    # drop bottom 10% by median traded value
    use_market_filter: bool = False  # go to cash when Nifty 500 < 200-day MA
    market_ma: int = 200
    # costs (assumptions - edit to match your broker)
    stt: float = 0.001             # 0.1% on both buy and sell (delivery)
    other_pct: float = 0.0003      # exchange + SEBI + stamp, approx
    slippage: float = 0.003        # 0.3% per side
    brokerage_per_order: float = 0.0
    dp_charge_per_sell: float = 15.0   # approx flat demat charge per scrip sold
    # tax
    stcg_rate: float = 0.20
    ltcg_rate: float = 0.125
    ltcg_exempt: float = 125_000
    cess: float = 0.04
    apply_tax: bool = True


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_universe(path):
    df = pd.read_csv(path)
    col = [c for c in df.columns if c.strip().lower() == "symbol"][0]
    return [f"{s.strip()}.NS" for s in df[col].dropna().unique()]


def download_data(tickers, start, cache_dir, refresh=False):
    """Returns (open, close, volume, benchmark_close) DataFrames. Cached on disk."""
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, "prices.pkl")
    if os.path.exists(cache) and not refresh:
        print(f"Loading cached prices from {cache}")
        return pd.read_pickle(cache)

    import yfinance as yf

    opens, closes, vols = [], [], []
    batch = 50
    for b in range(0, len(tickers), batch):
        chunk = tickers[b:b + batch]
        print(f"Downloading {b + 1}-{b + len(chunk)} of {len(tickers)} ...")
        d = yf.download(chunk, start=start, auto_adjust=True, progress=False,
                        threads=True, group_by="column")
        if d is None or d.empty:
            continue
        if not isinstance(d.columns, pd.MultiIndex):   # single ticker edge case
            d.columns = pd.MultiIndex.from_product([d.columns, chunk[:1]])
        opens.append(d["Open"])
        closes.append(d["Close"])
        vols.append(d["Volume"])

    o = pd.concat(opens, axis=1).sort_index()
    c = pd.concat(closes, axis=1).sort_index()
    v = pd.concat(vols, axis=1).sort_index()
    keep = c.columns[c.notna().sum() > 300]
    o, c, v = o[keep], c[keep], v[keep]

    bench = yf.download("^CRSLDX", start=start, auto_adjust=True, progress=False)["Close"]
    if isinstance(bench, pd.DataFrame):
        bench = bench.iloc[:, 0]
    bench = bench.reindex(c.index).ffill()

    out = (o, c, v, bench)
    pd.to_pickle(out, cache)
    return out


# --------------------------------------------------------------------------- #
# Signal
# --------------------------------------------------------------------------- #
def score_at(i, close_np, value_np, p):
    """Cross-sectional momentum score at row i. NaN = not eligible."""
    e = i - p.skip_days
    window = close_np[e - p.vol_window:e + 1]
    logret = np.diff(np.log(window), axis=0)
    vol = np.nanstd(logret, axis=0, ddof=1) * np.sqrt(252)

    valid = np.isfinite(close_np[e]) & (np.isfinite(window).sum(axis=0) >= 0.9 * len(window))
    valid &= np.isfinite(vol) & (vol > 0)
    for lb in p.lookbacks:
        valid &= np.isfinite(close_np[e - lb])

    # liquidity filter on median traded value
    tv = np.nanmedian(value_np[i - p.liquidity_window:i + 1], axis=0)
    valid &= np.isfinite(tv)
    if valid.sum() < 10:
        return np.full(close_np.shape[1], np.nan)
    cutoff = np.percentile(tv[valid], 100 * p.liquidity_cut)
    valid &= tv >= cutoff

    zs = []
    for lb in p.lookbacks:
        ratio = (close_np[e] / close_np[e - lb] - 1.0) / np.where(valid, vol, np.nan)
        m, s = np.nanmean(ratio[valid]), np.nanstd(ratio[valid], ddof=1)
        zs.append((ratio - m) / s)
    score = np.nanmean(np.vstack(zs), axis=0)
    score[~valid] = np.nan
    return score


# --------------------------------------------------------------------------- #
# Tax
# --------------------------------------------------------------------------- #
def fy_tax(st, lt, p):
    net_st, net_lt = st, lt
    if net_st < 0:                 # short-term loss can offset long-term gain
        net_lt += net_st
        net_st = 0.0
    net_lt = max(net_lt, 0.0)      # long-term loss cannot offset short-term gain
    tax = p.stcg_rate * net_st + p.ltcg_rate * max(net_lt - p.ltcg_exempt, 0.0)
    return tax * (1 + p.cess)      # surcharge and loss carry-forward ignored


# --------------------------------------------------------------------------- #
# Backtest
# --------------------------------------------------------------------------- #
def run_backtest(open_, close, volume, bench, p):
    close = close.ffill()
    cols = list(close.columns)
    dates = close.index
    close_np = close.values.astype(float)
    open_np = open_.reindex(index=dates, columns=cols).values.astype(float)
    value_np = close_np * volume.reindex(index=dates, columns=cols).values.astype(float)

    bench_ma = bench.rolling(p.market_ma).mean()

    first = max(max(p.lookbacks) + p.skip_days, p.vol_window, p.liquidity_window) + 1
    sig_to_exec = {i + 1: i for i in range(first, len(dates) - 1, p.rebalance_days)}

    cash = p.capital
    hold = {}                      # col index -> dict(sh, cost, date)
    fy_gains = {}                  # fy -> [short, long]
    trades, snapshots = [], []
    equity, cum_tax_path = [], []
    cum_tax, total_costs, traded_value = 0.0, 0.0, 0.0
    cur_fy = None
    idx_out = []

    def settle(fy):
        nonlocal cash, cum_tax
        if not p.apply_tax or fy not in fy_gains:
            return
        tax = fy_tax(*fy_gains[fy], p)
        cash -= tax                # cash may go negative: tax is paid out of pocket
        cum_tax += tax

    for k in range(first, len(dates)):
        d = dates[k]
        fy = d.year if d.month >= 4 else d.year - 1
        if cur_fy is not None and fy != cur_fy:
            settle(cur_fy)
        cur_fy = fy

        if k in sig_to_exec:
            i = sig_to_exec[k]
            score = score_at(i, close_np, value_np, p)
            risk_off = False
            if p.use_market_filter and np.isfinite(bench_ma.iloc[i]):
                risk_off = bench.iloc[i] < bench_ma.iloc[i]

            order = np.argsort(-np.where(np.isfinite(score), score, -np.inf))
            n_valid = int(np.isfinite(score).sum())
            rank = np.full(len(cols), 10**9)
            rank[order[:n_valid]] = np.arange(1, n_valid + 1)

            # ---- sells
            for j in list(hold):
                if risk_off or rank[j] > p.exit_rank:
                    h = hold.pop(j)
                    px = open_np[k, j] if np.isfinite(open_np[k, j]) else close_np[k, j]
                    px *= (1 - p.slippage)
                    gross = h["sh"] * px
                    cost = gross * (p.stt + p.other_pct) + p.brokerage_per_order + p.dp_charge_per_sell
                    cash += gross - cost
                    total_costs += cost + h["sh"] * (open_np[k, j] if np.isfinite(open_np[k, j]) else close_np[k, j]) * p.slippage
                    traded_value += gross
                    gain = gross - cost - h["sh"] * h["cost"]
                    is_long = (d - h["date"]).days > 365
                    fy_gains.setdefault(fy, [0.0, 0.0])[1 if is_long else 0] += gain
                    trades.append((d, cols[j], "SELL", h["sh"], px, gain))

            # ---- buys
            if not risk_off:
                slots = p.n_hold - len(hold)
                for j in order[:p.n_hold]:
                    if slots <= 0:
                        break
                    if j in hold or not np.isfinite(score[j]):
                        continue
                    if not np.isfinite(open_np[k, j]) or open_np[k, j] <= 0:
                        continue
                    budget = cash / slots
                    px = open_np[k, j] * (1 + p.slippage)
                    unit = px * (1 + p.stt + p.other_pct)
                    sh = int((budget - p.brokerage_per_order) // unit)
                    if sh < 1:         # share too expensive for the slot size
                        continue
                    gross = sh * px
                    cost = gross * (p.stt + p.other_pct) + p.brokerage_per_order
                    cash -= gross + cost
                    total_costs += cost + sh * open_np[k, j] * p.slippage
                    traded_value += gross
                    hold[j] = dict(sh=sh, cost=(gross + cost) / sh, date=d)
                    trades.append((d, cols[j], "BUY", sh, px, 0.0))
                    slots -= 1
            snapshots.append((d, [cols[j] for j in hold]))

        val = cash + sum(h["sh"] * close_np[k, j] for j, h in hold.items())
        equity.append(val)
        cum_tax_path.append(cum_tax)
        idx_out.append(d)

    settle(cur_fy)                                  # final FY
    equity[-1] = cash + sum(h["sh"] * close_np[-1, j] for j, h in hold.items())
    cum_tax_path[-1] = cum_tax

    eq = pd.Series(equity, index=idx_out, name="post_tax")
    pre = eq + pd.Series(cum_tax_path, index=idx_out)
    tr = pd.DataFrame(trades, columns=["date", "symbol", "side", "shares", "price", "realised_gain"])
    return dict(equity=eq, pretax=pre, trades=tr, snapshots=snapshots,
                total_costs=total_costs, total_tax=cum_tax, traded_value=traded_value)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def metrics(curve, label):
    curve = curve.dropna()
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    cagr = (curve.iloc[-1] / curve.iloc[0]) ** (1 / years) - 1
    dd = (curve / curve.cummax() - 1).min()
    r = curve.pct_change().dropna()
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan
    return {"Strategy": label, "Final (Rs)": round(curve.iloc[-1]),
            "CAGR %": round(100 * cagr, 1), "Max DD %": round(100 * dd, 1),
            "Sharpe": round(sharpe, 2)}


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", required=True, help="Nifty 500 CSV with a Symbol column")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--n-hold", type=int, default=20)
    ap.add_argument("--exit-ranks", type=int, nargs="+", default=[20, 40])
    ap.add_argument("--rebalance-days", type=int, default=21)
    ap.add_argument("--skip-days", type=int, default=0)
    ap.add_argument("--market-filter", action="store_true")
    ap.add_argument("--no-tax", action="store_true")
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--out", default="results")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    o, c, v, bench = download_data(load_universe(a.universe), a.start, a.cache_dir, a.refresh)
    print(f"{c.shape[1]} stocks, {c.index[0].date()} to {c.index[-1].date()}")

    base = Params(capital=a.capital, n_hold=a.n_hold, rebalance_days=a.rebalance_days,
                  skip_days=a.skip_days, use_market_filter=a.market_filter,
                  apply_tax=not a.no_tax)
    rows, curves = [], {}
    for er in a.exit_ranks:
        p = replace(base, exit_rank=er)
        res = run_backtest(o, c, v, bench, p)
        tag = f"exit>{er}"
        curves[tag + " (post-tax)"] = res["equity"]
        curves[tag + " (pre-tax)"] = res["pretax"]
        row = metrics(res["equity"], tag + " post-tax")
        row.update({"Trades": len(res["trades"]),
                    "Costs (Rs)": round(res["total_costs"]),
                    "Tax (Rs)": round(res["total_tax"])})
        rows.append(row)
        rows.append(metrics(res["pretax"], tag + " pre-tax"))
        res["trades"].to_csv(os.path.join(a.out, f"trades_exit{er}.csv"), index=False)
        pd.DataFrame([(d, ",".join(s)) for d, s in res["snapshots"]],
                     columns=["date", "holdings"]).to_csv(
            os.path.join(a.out, f"holdings_exit{er}.csv"), index=False)

    start_date = min(s.index[0] for s in curves.values())
    b = bench.loc[start_date:].dropna()
    b = b / b.iloc[0] * a.capital
    curves["Nifty 500 buy & hold"] = b
    rows.append(metrics(b, "Nifty 500 buy & hold"))

    table = pd.DataFrame(rows).fillna("")
    print("\n" + table.to_string(index=False))
    table.to_csv(os.path.join(a.out, "summary.csv"), index=False)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 6))
    for k, s in curves.items():
        ax.plot(s.index, s.values, label=k, lw=1.2, ls="--" if "pre-tax" in k else "-")
    ax.set_yscale("log")
    ax.set_title("Momentum strategy vs Nifty 500 (Rs, log scale)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.savefig(os.path.join(a.out, "equity_curve.png"), dpi=130, bbox_inches="tight")
    print(f"\nSaved results to {a.out}/")
    print("Reminder: current-constituent universe => survivorship bias.")


if __name__ == "__main__":
    main()
