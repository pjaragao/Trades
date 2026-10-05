"""
Backtest "e se eu tivesse copiado este analista?" sobre o histórico de sinais (tabela signals).

Diferenças para o backtest antigo:
- usa MINHAS regras de tamanho (valor por trade, lote) e respeita o capital livre (posições simultâneas);
- inclui custos (corretagem + taxas B3) e um slippage de cópia manual na entrada e na saída;
- P&L considera o lado (compra/venda);
- opção de pular operações que abriram e fecharam no mesmo dia (difíceis de copiar à mão).
"""
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional

from src.core import db
from src.core.config import get_prefs
from src.core.market_hours import to_brt
from src.services.journal import estimate_fees

FUTURE_POINT_VALUE = {"WIN": 0.20, "WDO": 10.0, "IND": 1.0, "DOL": 50.0}
SUPPORTED = {"OPCAO", "ACAO", "FUTURO"}


def _point_value(ticker: str) -> Optional[float]:
    for prefix, v in FUTURE_POINT_VALUE.items():
        if ticker.startswith(prefix):
            return v
    return None


def run(
    traders: Optional[List[str]] = None,
    asset_classes: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    initial_capital: Optional[float] = None,
    value_per_trade: Optional[float] = None,
    slippage_pct: float = 1.0,
    skip_intraday: bool = True,
    conn=None,
) -> Dict[str, Any]:
    prefs = get_prefs(conn)
    capital0 = float(initial_capital if initial_capital is not None else prefs["capital"]["total"])
    per_trade = float(value_per_trade if value_per_trade is not None else prefs["sizing"]["value_per_trade"])
    lot = int(prefs["sizing"]["lot_step"] or 100)
    slip = max(0.0, float(slippage_pct)) / 100.0

    where, params = ["status = 'CLOSED'", "preco_entrada > 0", "preco_saida IS NOT NULL"], []
    if traders:
        where.append(f"lower(trader) IN ({','.join('?' * len(traders))})")
        params += [t.lower() for t in traders]
    classes = [c for c in (asset_classes or ["OPCAO", "ACAO"]) if c in SUPPORTED]
    where.append(f"asset_class IN ({','.join('?' * len(classes))})")
    params += classes
    if date_from:
        where.append("timestamp_entrada >= ?")
        params.append(date_from)
    if date_to:
        where.append("timestamp_entrada <= ?")
        params.append(date_to + "T23:59:59")
    with db.connection(conn) as c:
        rows = [dict(r) for r in c.execute(f"SELECT * FROM signals WHERE {' AND '.join(where)} ORDER BY timestamp_entrada", params)]

    skipped = defaultdict(int)
    candidates = []
    for r in rows:
        e, x = to_brt(r["timestamp_entrada"]), to_brt(r["timestamp_saida"])
        if not e or not x or x < e:
            skipped["sem datas"] += 1
            continue
        if skip_intraday and e.date() == x.date():
            skipped["intraday (mesmo dia)"] += 1
            continue
        candidates.append((e, x, r))

    equity = capital0
    allocated = 0.0
    open_pos: List[Dict[str, Any]] = []
    trades: List[Dict[str, Any]] = []
    curve: List[Dict[str, Any]] = []

    def close_until(t) -> None:
        nonlocal equity, allocated
        for p in sorted([p for p in open_pos if t is None or p["exit_dt"] <= t], key=lambda p: p["exit_dt"]):
            open_pos.remove(p)
            allocated -= p["allocated"]
            equity += p["pnl"]
            trades.append(p)
            curve.append({"date": p["exit_dt"].date().isoformat(), "equity": round(equity, 2)})

    for e, x, r in candidates:
        close_until(e)
        buy = r["lado"] == "BUY"
        entry = r["preco_entrada"] * (1 + slip if buy else 1 - slip)
        exit_ = r["preco_saida"] * (1 - slip if buy else 1 + slip)
        if r["asset_class"] == "FUTURO":
            pv = _point_value(r["ticker"])
            if pv is None:
                skipped["futuro sem valor do ponto"] += 1
                continue
            qty, alloc = 1.0, 0.0
            gross = ((exit_ - entry) if buy else (entry - exit_)) * pv
            fees = 0.0
        else:
            qty = float(math.floor(per_trade / entry / lot) * lot) if entry > 0 else 0.0
            if qty <= 0:
                skipped["capital insuficiente p/ 1 lote"] += 1
                continue
            alloc = qty * entry
            if alloc > equity - allocated:
                skipped["sem capital livre (posições abertas)"] += 1
                continue
            gross = ((exit_ - entry) if buy else (entry - exit_)) * qty
            fees = estimate_fees(r["asset_class"], qty * entry, prefs) + estimate_fees(r["asset_class"], qty * exit_, prefs)
        pnl = gross - fees
        allocated += alloc
        sign = 1 if buy else -1
        open_pos.append({
            "id": r["id"], "ticker": r["ticker"], "trader": r["trader"], "asset_class": r["asset_class"], "lado": r["lado"],
            "entry_dt": e, "exit_dt": x, "qty": qty, "entry": round(entry, 4), "exit": round(exit_, 4),
            "allocated": alloc, "fees": round(fees, 2), "pnl": round(pnl, 2),
            "return_pct": round(pnl / alloc * 100, 2) if alloc else None,
            "signal_return_pct": round(sign * (r["preco_saida"] / r["preco_entrada"] - 1) * 100, 2),
            "hold_days": round((x - e).total_seconds() / 86400, 1),
        })
    close_until(None)

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    peak, max_dd, eq = capital0, 0.0, capital0
    for pt in curve:
        eq = pt["equity"]
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)

    by_trader: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0, "fees": 0.0, "sig": []})
    monthly: Dict[str, float] = defaultdict(float)
    for t in trades:
        b = by_trader[t["trader"]]
        b["trades"] += 1
        b["wins"] += 1 if t["pnl"] > 0 else 0
        b["pnl"] += t["pnl"]
        b["fees"] += t["fees"]
        b["sig"].append(t["signal_return_pct"])
        monthly[t["exit_dt"].strftime("%Y-%m")] += t["pnl"]

    gross_win, gross_loss = sum(wins), abs(sum(losses))
    return {
        "params": {"initial_capital": capital0, "value_per_trade": per_trade, "lot": lot, "slippage_pct": slip * 100,
                   "skip_intraday": skip_intraday, "asset_classes": classes, "traders": traders or []},
        "summary": {
            "signals": len(rows),
            "trades": len(trades),
            "skipped": dict(skipped),
            "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else None,
            "net_pnl": round(sum(pnls), 2),
            "fees": round(sum(t["fees"] for t in trades), 2),
            "final_equity": round(capital0 + sum(pnls), 2),
            "return_pct": round(sum(pnls) / capital0 * 100, 2) if capital0 else None,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else (None if not wins else 99.0),
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round(max_dd / peak * 100, 2) if peak else None,
            "avg_hold_days": round(sum(t["hold_days"] for t in trades) / len(trades), 1) if trades else None,
            "avg_signal_return_pct": round(sum(t["signal_return_pct"] for t in trades) / len(trades), 2) if trades else None,
            "avg_my_return_pct": round(sum(t["return_pct"] or 0 for t in trades) / len(trades), 2) if trades else None,
        },
        "equity_curve": [{"date": None, "equity": capital0}] + curve,
        "by_trader": sorted([{
            "trader": k, "trades": v["trades"], "win_rate": round(v["wins"] / v["trades"] * 100, 1),
            "pnl": round(v["pnl"], 2), "fees": round(v["fees"], 2),
            "avg_signal_return_pct": round(sum(v["sig"]) / len(v["sig"]), 2),
        } for k, v in by_trader.items()], key=lambda x: x["pnl"], reverse=True),
        "monthly": [{"month": k, "pnl": round(v, 2)} for k, v in sorted(monthly.items())],
        "trades": [{**{k: v for k, v in t.items() if k not in ("entry_dt", "exit_dt", "allocated")},
                    "entry_at": t["entry_dt"].isoformat(), "exit_at": t["exit_dt"].isoformat()} for t in trades[-300:]][::-1],
    }
