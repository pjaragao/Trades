"""
Calculadora de IRPF (renda variável, conta real).

- report()             : apuração mês a mês (fechado com notas x estimado), saldos de prejuízo, resumo anual
                         para a declaração e a cobertura das notas de corretagem.
- simulate_close_all() : quanto de IR eu pagaria se encerrasse agora todas as posições abertas — usa as mesmas
                         regras da apuração (isenção de R$ 20 mil, day trade, prejuízos a compensar) comparando o
                         mês com e sem as vendas hipotéticas.
"""
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core import db
from src.core.config import get_prefs
from src.core.market_hours import now_brt
from src.services import brokerage_notes as bn
from src.services import journal, portfolio, tax

NOTES = [
    "Só fecha com nota: um mês fica \"fechado\" quando todos os pregões com operações têm a nota de corretagem importada. "
    "Sem isso, preços, custos e IRRF podem estar estimados e o valor é uma estimativa.",
    "Swing trade 15% (ações isentas se as vendas de ações no mês forem até R$ 20 mil; opções não têm isenção). "
    "Day trade 20%. Prejuízo de swing compensa swing; de day trade, só day trade.",
    "IRRF: o da nota quando importada; sem nota, 0,005% das vendas (swing) e 1% do ganho de day trade do dia. "
    "O que sobra do IRRF passa para os meses seguintes do mesmo ano.",
    "DARF código 6015, vencimento no último dia útil do mês seguinte; abaixo de R$ 10 acumula para o próximo.",
    "FIIs, ETFs e BDRs são tratados como ações (a isenção de R$ 20 mil vale só para ações). Confira com seu contador.",
]


def report(conn=None) -> Dict[str, Any]:
    month = now_brt().date().isoformat()[:7]
    with db.connection(conn) as c:
        led = journal.ledger(c, "real")
        cov = bn.coverage(c)
        rows = tax.monthly_tax(led["events"], until=month, irrf_days=bn.irrf_by_day(), coverage=cov, current_month=month)

    years: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"exempt_gains": 0.0, "stock_swing": 0.0, "other_swing": 0.0,
                                                             "day_trade": 0.0, "darf": 0.0, "irrf": 0.0, "months": 0, "closed": 0})
    for r in rows:
        y = years[r["month"][:4]]
        y["exempt_gains"] += r["exempt_gain"]
        y["stock_swing"] += 0.0 if r["stock_exempt"] else r["stock_swing_pnl"]
        y["other_swing"] += r["other_swing_pnl"]
        y["day_trade"] += r["day_trade_pnl"]
        y["darf"] += r["darf_value"]
        y["irrf"] += r["irrf_estimate"]
        if r["status"] != "sem_operacoes":
            y["months"] += 1
            y["closed"] += 1 if r["status"] == "fechado" else 0
        y["swing_loss_end"] = r["swing_loss_carry"]
        y["day_loss_end"] = r["day_loss_carry"]
    years_out = [{"year": k, **{kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()},
                  "status": "fechado" if v["months"] and v["closed"] == v["months"] else "estimado"}
                 for k, v in sorted(years.items(), reverse=True)]

    today = now_brt().date().isoformat()
    upcoming = [r for r in rows if r["darf_value"] and r["due_date"] >= today]
    last = rows[-1] if rows else None
    return {
        "months": rows,
        "years": years_out,
        "coverage": {"days_total": cov["days_total"], "days_covered": cov["days_covered"],
                     "missing": [d for m in sorted(cov["months"]) for d in cov["months"][m]["missing"]]},
        "next_darf": ({"month": upcoming[0]["month"], "value": upcoming[0]["darf_value"], "due_date": upcoming[0]["due_date"],
                       "status": upcoming[0]["status"]} if upcoming else None),
        "loss_carry": {"swing": last["swing_loss_carry"] if last else 0.0, "day": last["day_loss_carry"] if last else 0.0},
        "total_darf": round(sum(r["darf_value"] for r in rows), 2),
        "notes": NOTES,
    }


def _slim(row: Optional[Dict[str, Any]], month: str) -> Dict[str, Any]:
    keys = ("stock_sales", "stock_swing_pnl", "stock_exempt", "exempt_gain", "other_swing_pnl", "day_trade_pnl", "swing_base",
            "day_base", "swing_tax", "day_tax", "irrf_estimate", "irrf_used", "tax_due", "darf_value", "swing_loss_carry",
            "day_loss_carry", "status")
    if row is None:
        return {k: (False if k == "stock_exempt" else ("estimado" if k == "status" else 0.0)) for k in keys} | {
            "month": month, "due_date": tax.due_date(month).isoformat()}
    return {k: row[k] for k in keys} | {"month": row["month"], "due_date": row["due_date"]}


def simulate_close_all(conn=None, at: Optional[datetime] = None) -> Dict[str, Any]:
    """IR do mês se eu encerrar agora todas as posições abertas (conta real), ao preço atual e com custos estimados."""
    now = (at or now_brt())
    today = now.date().isoformat()
    month = today[:7]
    prefs = get_prefs(conn)
    with db.connection(conn) as c:
        execs = journal.list_executions(account="real", conn=c)
        positions = portfolio.positions(c, account="real")
        cov = bn.coverage(c)
    irrf_days = bn.irrf_by_day()

    hypo, items, missing = [], [], []
    for i, p in enumerate(positions):
        side = "SELL" if p["side"] == "LONG" else "BUY"
        qty = float(p["quantity"])
        book = p.get("last_bid") if side == "SELL" else p.get("last_ask")
        if book and p.get("quote_live"):
            price, source = float(book), "MT5 ao vivo (oferta de " + ("compra)" if side == "SELL" else "venda)")
        elif p.get("last_price") is not None:
            price, source = float(p["last_price"]), {"mt5": "MT5", "brapi": "brapi", "tradingfloors": "TradingFloors",
                                                     "manual": "manual"}.get(p.get("last_price_source"), "último preço")
        else:
            missing.append(p["ticker"])
            continue
        gross = qty * price
        fees = journal.estimate_fees(p["asset_class"], gross, prefs)
        hypo.append({"id": 10**12 + i, "signal_id": None, "ticker": p["ticker"], "side": side, "quantity": qty, "price": price,
                     "fees": fees, "executed_at": now.isoformat(timespec="seconds"), "asset_class": p["asset_class"]})
        items.append({"ticker": p["ticker"], "asset_class": p["asset_class"], "position": p["side"], "side": side, "quantity": qty,
                      "avg_price": p["avg_price"], "price": round(price, 4), "price_source": source, "gross": round(gross, 2),
                      "fees": fees, "opened_at": p["opened_at"]})

    base = journal.compute_ledger(execs)["events"]
    sim = journal.compute_ledger(execs + hypo)["events"]

    def month_row(events):
        rows = tax.monthly_tax(events, until=month, irrf_days=irrf_days, coverage=cov, current_month=month)
        return next((r for r in rows if r["month"] == month), None)

    before, after = _slim(month_row(base), month), _slim(month_row(sim), month)

    def today_totals(events, ticker):
        evs = [e for e in events if e["ticker"] == ticker and e["date"] == today]
        return (sum(e["pnl"] for e in evs), sum(e["qty"] for e in evs if e["kind"] == "day"),
                sum(e["qty"] for e in evs if e["kind"] != "day"))

    for it in items:  # efeito de encerrar = eventos de hoje com a venda hipotética menos os que já existiam
        pnl_s, day_s, swing_s = today_totals(sim, it["ticker"])
        pnl_b, day_b, swing_b = today_totals(base, it["ticker"])
        it["pnl"] = round(pnl_s - pnl_b, 2)
        new_day, new_swing = day_s - day_b > 1e-9, swing_s - swing_b > 1e-9
        it["kind"] = "day" if new_day and not new_swing else ("misto" if new_day else "swing")

    warnings: List[Dict[str, str]] = []
    if missing:
        warnings.append({"level": "warning", "text": f"Sem cotação para {', '.join(missing)} — ficaram fora da simulação. Informe o preço na Carteira."})
    if before["stock_sales"] <= tax.STOCK_EXEMPTION < after["stock_sales"] and after["stock_swing_pnl"] > 0:
        warnings.append({"level": "danger", "text": (
            f"Vender tudo levaria as vendas de ações no mês a R$ {after['stock_sales']:,.2f} (acima de R$ 20 mil): "
            f"o lucro com ações do mês (R$ {after['stock_swing_pnl']:,.2f}) deixa de ser isento.").replace(",", "X").replace(".", ",").replace("X", ".")})
    day_items = [it["ticker"] for it in items if it["kind"] in ("day", "misto")]
    if day_items:
        warnings.append({"level": "warning", "text": f"{', '.join(day_items)}: comprado(s) hoje — encerrar hoje é day trade (20%)."})
    if before["status"] != "fechado":
        warnings.append({"level": "info", "text": "O mês ainda não está fechado com notas de corretagem: valores estimados."})

    totals = {"gross": round(sum(i["gross"] for i in items), 2), "fees": round(sum(i["fees"] for i in items), 2),
              "pnl": round(sum(i["pnl"] for i in items), 2)}
    return {
        "at": now.isoformat(timespec="seconds"),
        "month": month,
        "due_date": after["due_date"],
        "positions": items,
        "missing_quotes": missing,
        "totals": totals,
        "before": before,
        "after": after,
        "additional_tax": round(after["tax_due"] - before["tax_due"], 2),
        "warnings": warnings,
        "estimated": True,
    }


__all__ = ["report", "simulate_close_all", "NOTES"]
