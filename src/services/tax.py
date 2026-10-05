"""
Apuração mensal de IR sobre renda variável (operações reais).

Regras implementadas:
- Swing trade (operações comuns): 15% sobre o ganho líquido do mês.
  * Ações: isento se o total de VENDAS de ações no mês for <= R$ 20.000 (só para ações; opções não têm isenção).
  * Prejuízo de swing acumula e compensa ganhos de swing futuros (ações, opções, futuros).
- Day trade: 20% sobre o ganho líquido do mês; prejuízo de day trade só compensa day trade.
- IRRF ("dedo-duro"), por pregão: o valor da nota de corretagem quando importada; sem nota, estimado em
  0,005% das vendas em swing e 1% do ganho líquido de day trade do dia. É abatido do IR do mês; o que sobrar
  passa para os meses seguintes do mesmo ano.
- DARF (código 6015) abaixo de R$ 10,00 acumula para o mês seguinte. Vencimento: último dia útil do mês seguinte.
- Situação do mês: "fechado" só quando todos os pregões com operações têm nota de corretagem importada;
  caso contrário, "estimado".

Simplificações (avisadas na tela): FIIs (20%, sem isenção) e ETFs/BDRs (sem isenção) entram como "ações".
"""
import calendar
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Optional

from src.core.market_hours import previous_business_day

SWING_RATE = 0.15
DAY_RATE = 0.20
STOCK_EXEMPTION = 20000.0
IRRF_SWING = 0.00005
IRRF_DAY = 0.01
DARF_MIN = 10.0


def due_date(month: str) -> date:
    y, m = int(month[:4]), int(month[5:7])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    last = date(y, m, calendar.monthrange(y, m)[1])
    return previous_business_day(last)


_due_date = due_date


def _months_between(first: str, last: str) -> List[str]:
    y, m = int(first[:4]), int(first[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def monthly_tax(events: List[Dict[str, Any]], until: Optional[str] = None,
                irrf_days: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
                coverage: Optional[Dict[str, Any]] = None, current_month: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    events       : journal.compute_ledger()['events'] (conta real).
    irrf_days    : IRRF lido das notas por pregão {'AAAA-MM-DD': {'swing': x, 'day': y|None}} (brokerage_notes.irrf_by_day).
    coverage     : brokerage_notes.coverage() — define se o mês está "fechado" (todas as notas) ou "estimado".
    current_month: mês em andamento (marcado como parcial).
    """
    irrf_days = irrf_days or {}
    cov_months = (coverage or {}).get("months", {})
    if not events and not cov_months:
        return []
    by_month: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_day: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for e in events:
        m = e["date"][:7]
        b = by_month[m]
        d = by_day[e["date"]]
        if e["kind"] == "day":
            b["day_pnl"] += e["pnl"]
            d["day_pnl"] += e["pnl"]
        else:
            if e["asset_class"] == "ACAO":
                b["stock_swing_pnl"] += e["pnl"]
                b["stock_sales"] += e["sale_gross"]
            else:
                b["other_swing_pnl"] += e["pnl"]
            b["swing_sales"] += e["sale_gross"]
            d["swing_sales"] += e["sale_gross"]

    known = list(by_month) + list(cov_months)
    months = _months_between(min(known), until or max(known))
    swing_loss, day_loss, carry_tax, irrf_carry = 0.0, 0.0, 0.0, 0.0
    out = []
    for m in months:
        if m.endswith("-01"):
            irrf_carry = 0.0  # saldo de IRRF não passa de um ano para o outro
        b = by_month.get(m, {})
        stock_pnl = b.get("stock_swing_pnl", 0.0)
        stock_sales = b.get("stock_sales", 0.0)
        other_pnl = b.get("other_swing_pnl", 0.0)
        day_pnl = b.get("day_pnl", 0.0)

        exempt = stock_sales <= STOCK_EXEMPTION and stock_pnl > 0
        exempt_gain = stock_pnl if exempt else 0.0
        swing_taxable = (0.0 if exempt else stock_pnl) + other_pnl

        # compensação de prejuízos
        swing_loss_in, day_loss_in = swing_loss, day_loss
        swing_base = swing_taxable - swing_loss
        if swing_base < 0:
            swing_loss = -swing_base
            swing_base = 0.0
        else:
            swing_loss = 0.0
        day_base = day_pnl - day_loss
        if day_base < 0:
            day_loss = -day_base
            day_base = 0.0
        else:
            day_loss = 0.0

        swing_tax = swing_base * SWING_RATE
        day_tax = day_base * DAY_RATE

        # IRRF por pregão: nota quando houver, senão estimativa
        irrf_swing = irrf_day = 0.0
        days_with_events = covered = 0
        for d, v in by_day.items():
            if d[:7] != m:
                continue
            days_with_events += 1
            note = irrf_days.get(d)
            est_day = max(v.get("day_pnl", 0.0), 0.0) * IRRF_DAY
            if note is not None:
                covered += 1
                irrf_swing += float(note.get("swing") or 0.0)
                irrf_day += float(note["day"]) if note.get("day") is not None else est_day
            else:
                irrf_swing += v.get("swing_sales", 0.0) * IRRF_SWING
                irrf_day += est_day
        irrf = irrf_swing + irrf_day
        available = irrf + irrf_carry
        tax_gross = swing_tax + day_tax
        irrf_used = min(available, tax_gross)
        irrf_carry = available - irrf_used

        due = (tax_gross - irrf_used) + carry_tax
        pay = due if due >= DARF_MIN else 0.0
        carry_in = carry_tax
        carry_tax = 0.0 if pay else due

        cm = cov_months.get(m) or {}
        if coverage is None:
            status = "estimado"
        elif not cm.get("days"):
            status = "sem_operacoes"
        else:
            status = "fechado" if cm.get("complete") else "estimado"
        out.append({
            "month": m,
            "status": status,
            "in_progress": m == current_month,
            "coverage": {"days": cm.get("days", 0), "covered": cm.get("covered", 0)},
            "missing_days": cm.get("missing", []),
            "stock_sales": round(stock_sales, 2),
            "stock_swing_pnl": round(stock_pnl, 2),
            "stock_exempt": exempt,
            "exempt_gain": round(exempt_gain, 2),
            "other_swing_pnl": round(other_pnl, 2),
            "day_trade_pnl": round(day_pnl, 2),
            "swing_taxable": round(swing_taxable, 2),
            "swing_loss_used": round(min(swing_loss_in, max(swing_taxable, 0.0)), 2),
            "day_loss_used": round(min(day_loss_in, max(day_pnl, 0.0)), 2),
            "swing_base": round(swing_base, 2),
            "day_base": round(day_base, 2),
            "swing_tax": round(swing_tax, 2),
            "day_tax": round(day_tax, 2),
            "irrf_swing": round(irrf_swing, 2),
            "irrf_day": round(irrf_day, 2),
            "irrf_estimate": round(irrf, 2),
            "irrf_used": round(irrf_used, 2),
            "irrf_carry": round(irrf_carry, 2),
            "irrf_source": "nota" if days_with_events and covered == days_with_events else ("parcial" if covered else "estimativa"),
            "carried_from_previous": round(carry_in, 2),
            "tax_due": round(due, 2),
            "darf_value": round(pay, 2),
            "carried_to_next": round(carry_tax, 2),
            "swing_loss_carry": round(swing_loss, 2),
            "day_loss_carry": round(day_loss, 2),
            "due_date": due_date(m).isoformat(),
            "darf_code": "6015",
        })
    return out
