"""
Resultados reais: diário de operações, curva de patrimônio, desempenho por analista,
slippage em relação ao sinal, custos e exportação CSV.
"""
import csv
import io
from collections import defaultdict
from typing import Any, Dict, List, Optional

from src.core import db
from src.core.config import get_prefs
from src.core.market_hours import now_brt, to_brt
from src.services import journal, tax
from src.services.signals import hydrate


def _signals(conn, ids: List[str], prefs) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    ids = sorted(set(ids))
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for r in conn.execute(f"SELECT * FROM signals WHERE id IN ({','.join('?' * len(chunk))})", chunk):
            out[r["id"]] = hydrate(dict(r), prefs)
    return out


def _slip(mine: Optional[float], ref: Optional[float], worse_if_higher: bool) -> Optional[float]:
    """Slippage em % — positivo = pior que o analista."""
    if mine is None or not ref:
        return None
    pct = (mine / ref - 1) * 100
    return round(pct if worse_if_higher else -pct, 2)


def closed_trades(conn=None, date_from: Optional[str] = None, date_to: Optional[str] = None, account: str = "real") -> List[Dict[str, Any]]:
    prefs = get_prefs(conn)
    with db.connection(conn) as c:
        led = journal.ledger(c, account)
        sigs = _signals(c, [s for cy in led["cycles"] for s in cy["signal_ids"]], prefs)
    out = []
    for cy in led["cycles"]:
        if cy["status"] != "CLOSED":
            continue
        closed_day = (to_brt(cy["closed_at"]) or now_brt()).date().isoformat()
        if date_from and closed_day < date_from:
            continue
        if date_to and closed_day > date_to:
            continue
        sig = sigs.get(cy["signal_ids"][0]) if cy["signal_ids"] else None
        long = cy["direction"] == "LONG"
        my_entry = cy["avg_buy"] if long else cy["avg_sell"]
        my_exit = cy["avg_sell"] if long else cy["avg_buy"]
        sig_entry = sig.get("preco_entrada") if sig else None
        sig_exit = sig.get("preco_saida") if sig and sig["status"] == "CLOSED" else None
        out.append({
            **cy,
            "closed_day": closed_day,
            "trader": sig["trader"] if sig else None,
            "signal": {k: sig.get(k) for k in ("id", "trader", "ticker", "preco_entrada", "preco_saida", "status", "return_final_pct", "return_now_pct")} if sig else None,
            "my_entry": my_entry,
            "my_exit": my_exit,
            "entry_slippage_pct": _slip(my_entry, sig_entry, worse_if_higher=long),
            "exit_slippage_pct": _slip(my_exit, sig_exit, worse_if_higher=not long),
            "signal_return_pct": (sig.get("return_final_pct") if sig_exit else None) if sig else None,
        })
    out.sort(key=lambda t: t["closed_at"] or "", reverse=True)
    return out


def summary(date_from: Optional[str] = None, date_to: Optional[str] = None, conn=None, account: str = "real") -> Dict[str, Any]:
    prefs = get_prefs(conn)
    capital = float(prefs["capital"]["total"])
    with db.connection(conn) as c:
        led = journal.ledger(c, account)
        trades = closed_trades(c, date_from, date_to, account)

    events = [e for e in led["events"] if (not date_from or e["date"] >= date_from) and (not date_to or e["date"] <= date_to)]
    pnls = [t["realized_pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    fees = sum(t["fees"] for t in trades)
    realized = round(sum(e["pnl"] for e in events), 2)

    # curva de patrimônio (realizado, por dia) — começa no capital configurado
    before = sum(e["pnl"] for e in led["events"] if date_from and e["date"] < date_from)
    daily: Dict[str, float] = defaultdict(float)
    for e in events:
        daily[e["date"]] += e["pnl"]
    equity, peak, max_dd = capital + before, capital + before, 0.0
    curve = [{"date": None, "equity": round(equity, 2), "pnl": 0.0}]
    for d in sorted(daily):
        equity += daily[d]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        curve.append({"date": d, "equity": round(equity, 2), "pnl": round(daily[d], 2)})

    # por analista
    per: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0, "fees": 0.0, "my_ret": [], "sig_ret": [], "entry_slip": [], "exit_slip": []})
    for t in trades:
        k = t["trader"] or "Sem sinal (manual)"
        p = per[k]
        p["trades"] += 1
        p["wins"] += 1 if t["realized_pnl"] > 0 else 0
        p["pnl"] += t["realized_pnl"]
        p["fees"] += t["fees"]
        if t["return_pct"] is not None:
            p["my_ret"].append(t["return_pct"])
        if t["signal_return_pct"] is not None:
            p["sig_ret"].append(t["signal_return_pct"])
        if t["entry_slippage_pct"] is not None:
            p["entry_slip"].append(t["entry_slippage_pct"])
        if t["exit_slippage_pct"] is not None:
            p["exit_slip"].append(t["exit_slippage_pct"])

    def avg(xs):
        return round(sum(xs) / len(xs), 2) if xs else None

    by_trader = [{
        "trader": k,
        "trades": v["trades"],
        "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else None,
        "pnl": round(v["pnl"], 2),
        "fees": round(v["fees"], 2),
        "avg_my_return_pct": avg(v["my_ret"]),
        "avg_signal_return_pct": avg(v["sig_ret"]),
        "avg_entry_slippage_pct": avg(v["entry_slip"]),
        "avg_exit_slippage_pct": avg(v["exit_slip"]),
    } for k, v in per.items()]
    by_trader.sort(key=lambda r: r["pnl"], reverse=True)

    entry_slips = [t["entry_slippage_pct"] for t in trades if t["entry_slippage_pct"] is not None]
    exit_slips = [t["exit_slippage_pct"] for t in trades if t["exit_slippage_pct"] is not None]
    return {
        "capital": capital,
        "realized_pnl": realized,
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else (None if not wins else 99.0),
        "avg_win": round(gross_win / len(wins), 2) if wins else None,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else None,
        "fees": round(fees, 2),
        "fees_pct_of_gross": round(fees / (gross_win + gross_loss) * 100, 2) if (gross_win + gross_loss) else None,
        "max_drawdown": round(max_dd, 2),
        "return_on_capital_pct": round(realized / capital * 100, 2) if capital else None,
        "avg_entry_slippage_pct": avg(entry_slips),
        "avg_exit_slippage_pct": avg(exit_slips),
        "day_trade_pnl": round(sum(e["pnl"] for e in events if e["kind"] == "day"), 2),
        "equity_curve": curve,
        "by_trader": by_trader,
        "closed_trades": trades,
    }


def tax_report(conn=None) -> Dict[str, Any]:
    with db.connection(conn) as c:
        led = journal.ledger(c)
    from src.services.brokerage_notes import irrf_by_month

    rows = tax.monthly_tax(led["events"], until=now_brt().date().isoformat()[:7], irrf_actual=irrf_by_month())
    return {
        "months": rows,
        "total_darf": round(sum(r["darf_value"] for r in rows), 2),
        "notes": [
            "Estimativa. Confira com o relatório da sua corretora/contador antes de pagar.",
            "FIIs, ETFs e BDRs são tratados como ações (a isenção de R$ 20 mil vale só para ações).",
            "IRRF: usa o valor das notas importadas; sem nota, estima 0,005% sobre vendas (swing). Day trade: 1% do ganho (estimado).",
        ],
    }


def executions_csv(conn=None, account: str = "real") -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["id", "data_hora", "ativo", "lado", "quantidade", "preco", "custos", "classe", "sinal_id", "observacao"])
    for e in journal.list_executions(account=account, conn=conn):
        w.writerow([e["id"], e["executed_at"], e["ticker"], "COMPRA" if e["side"] == "BUY" else "VENDA",
                    _br(e["quantity"]), _br(e["price"]), _br(e["fees"]), e["asset_class"], e["signal_id"] or "", e["note"] or ""])
    return buf.getvalue()


def trades_csv(conn=None, account: str = "real") -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["ativo", "analista", "direcao", "abertura", "encerramento", "qtd_comprada", "preco_medio_compra",
                "qtd_vendida", "preco_medio_venda", "custos", "resultado", "resultado_pct", "day_trade", "slippage_entrada_pct"])
    for t in closed_trades(conn, account=account):
        w.writerow([t["ticker"], t["trader"] or "", t["direction"], t["opened_at"], t["closed_at"], _br(t["buy_qty"]),
                    _br(t["avg_buy"]), _br(t["sell_qty"]), _br(t["avg_sell"]), _br(t["fees"]), _br(t["realized_pnl"]),
                    _br(t["return_pct"]), _br(t["day_trade_pnl"]), _br(t["entry_slippage_pct"])])
    return buf.getvalue()


def _br(v) -> str:
    if v is None:
        return ""
    return f"{v}".replace(".", ",")
