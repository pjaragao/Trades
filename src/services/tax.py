"""
Apuração mensal de IR sobre renda variável (estimativa).

Regras implementadas:
- Swing trade (operações comuns): 15% sobre o ganho líquido do mês.
  * Ações: isento se o total de VENDAS de ações no mês for <= R$ 20.000 (só para ações; opções não têm isenção).
  * Prejuízo de swing acumula e compensa ganhos de swing futuros (ações, opções, futuros).
- Day trade: 20% sobre o ganho líquido do mês; prejuízo de day trade só compensa day trade.
- IRRF ("dedo-duro") estimado: 0,005% sobre vendas em swing e 1% sobre o ganho de day trade — abatido do DARF.
- DARF (código 6015) abaixo de R$ 10,00 acumula para o mês seguinte. Vencimento: último dia útil do mês seguinte.

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


def _due_date(month: str) -> date:
    y, m = int(month[:4]), int(month[5:7])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    last = date(y, m, calendar.monthrange(y, m)[1])
    return previous_business_day(last)


def _months_between(first: str, last: str) -> List[str]:
    y, m = int(first[:4]), int(first[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def monthly_tax(events: List[Dict[str, Any]], until: Optional[str] = None,
                irrf_actual: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """
    events: saída de journal.compute_ledger()['events'].
    irrf_actual: IRRF de swing por mês lido das notas de corretagem (substitui a estimativa de 0,005%).
    """
    irrf_actual = irrf_actual or {}
    if not events:
        return []
    by_month: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for e in events:
        m = e["date"][:7]
        b = by_month[m]
        if e["kind"] == "day":
            b["day_pnl"] += e["pnl"]
        else:
            if e["asset_class"] == "ACAO":
                b["stock_swing_pnl"] += e["pnl"]
                b["stock_sales"] += e["sale_gross"]
            else:
                b["other_swing_pnl"] += e["pnl"]
            b["swing_sales"] += e["sale_gross"]

    months = _months_between(min(by_month), until or max(by_month))
    swing_loss, day_loss, carry_tax = 0.0, 0.0, 0.0
    out = []
    for m in months:
        b = by_month.get(m, {})
        stock_pnl = b.get("stock_swing_pnl", 0.0)
        stock_sales = b.get("stock_sales", 0.0)
        other_pnl = b.get("other_swing_pnl", 0.0)
        day_pnl = b.get("day_pnl", 0.0)

        exempt = stock_sales <= STOCK_EXEMPTION and stock_pnl > 0
        exempt_gain = stock_pnl if exempt else 0.0
        swing_taxable = (0.0 if exempt else stock_pnl) + other_pnl

        # compensação de prejuízos
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
        swing_irrf = irrf_actual[m] if m in irrf_actual else b.get("swing_sales", 0.0) * IRRF_SWING
        irrf = swing_irrf + max(day_pnl, 0.0) * IRRF_DAY
        due = max(0.0, swing_tax + day_tax - irrf) + carry_tax
        pay = due if due >= DARF_MIN else 0.0
        carry_tax = 0.0 if pay else due

        out.append({
            "month": m,
            "stock_sales": round(stock_sales, 2),
            "stock_swing_pnl": round(stock_pnl, 2),
            "stock_exempt": exempt,
            "exempt_gain": round(exempt_gain, 2),
            "other_swing_pnl": round(other_pnl, 2),
            "day_trade_pnl": round(day_pnl, 2),
            "swing_base": round(swing_base, 2),
            "day_base": round(day_base, 2),
            "swing_tax": round(swing_tax, 2),
            "day_tax": round(day_tax, 2),
            "irrf_estimate": round(irrf, 2),
            "irrf_source": "nota" if m in irrf_actual else "estimativa",
            "darf_value": round(pay, 2),
            "carried_to_next": round(carry_tax, 2),
            "swing_loss_carry": round(swing_loss, 2),
            "day_loss_carry": round(day_loss, 2),
            "due_date": _due_date(m).isoformat(),
            "darf_code": "6015",
        })
    return out
