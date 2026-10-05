"""
Checagens de risco antes de enviar uma ordem.

Ordem manual (eu cliquei e confirmei): limites viram AVISOS, exceto os que impedem erro grosseiro.
Ordem da automação: todo limite é BLOQUEIO.
"""
from typing import Any, Dict, Optional

from src.core import db
from src.core.config import get_prefs
from src.core.market_hours import market_status, now_brt
from src.services import journal


def orders_today(account: str, origin: Optional[str] = None, conn=None) -> int:
    day = now_brt().date().isoformat()
    sql = "SELECT COUNT(*) FROM orders WHERE account = ? AND purpose = 'entry' AND substr(created_at, 1, 10) >= ? AND status NOT IN ('rejected', 'error')"
    params = [account, day]
    if origin:
        sql += " AND origin = ?"
        params.append(origin)
    with db.connection(conn) as c:
        return c.execute(sql, params).fetchone()[0]


def realized_today(account: str, conn=None) -> float:
    day = now_brt().date().isoformat()
    return round(sum(e["pnl"] for e in journal.ledger(conn, account)["events"] if e["date"] == day), 2)


def check_order(*, ticker: str, side: str, quantity: float, price: Optional[float], purpose: str, origin: str,
                account: str, lot: int = 100, conn=None, prefs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    prefs = prefs or get_prefs(conn)
    auto = prefs["execution"]["auto"]
    capital = float(prefs["capital"]["total"])
    blocks, warns = [], []
    is_auto = origin == "auto"

    def limit(msg: str) -> None:
        (blocks if is_auto else warns).append(msg)

    if quantity <= 0:
        blocks.append("Quantidade deve ser maior que zero.")
    if price is not None and price <= 0:
        blocks.append("Preço limite inválido.")
    if lot > 1 and quantity % lot:
        warns.append(f"Quantidade fora do lote padrão de {lot}.")

    ms = market_status()
    if not ms["is_open"]:
        limit(f"{ms['label']} ({ms['detail']}) — a ordem pode ser rejeitada ou ficar parada.")

    led = journal.ledger(conn, account)
    pos = next((p for p in led["positions"] if p["ticker"] == ticker), None)
    held = pos["qty"] if pos else 0.0
    value = quantity * (price or 0)
    snapshot: Dict[str, Any] = {"held": held, "value": round(value, 2), "market": ms["phase"]}

    if purpose == "exit":
        closing_long = side == "SELL" and held > 0
        closing_short = side == "BUY" and held < 0
        if not (closing_long or closing_short):
            blocks.append("Não há posição nesse sentido para encerrar.")
        elif quantity > abs(held) + 1e-9:
            blocks.append(f"Quantidade maior que a posição ({abs(held):,.0f}).".replace(",", "."))
    else:
        if side == "SELL" and held <= 0:
            blocks.append("Venda sem posição (a descoberto) não é permitida pelo Copiloto.")
        exposure = sum(p["invested"] for p in led["positions"])
        snapshot["exposure"] = round(exposure, 2)
        if capital > 0 and value > capital - exposure + 1e-6:
            limit(f"Valor da ordem (R$ {value:,.2f}) maior que o capital livre (R$ {capital - exposure:,.2f}).")
        if capital > 0 and (exposure + value) / capital * 100 > auto["max_exposure_pct"]:
            limit(f"Exposição passaria de {auto['max_exposure_pct']:.0f}% do capital.")
        if is_auto:
            if value > auto["max_trade_value"]:
                blocks.append(f"Valor acima do máximo por ordem automática (R$ {auto['max_trade_value']:,.2f}).")
            n = orders_today(account, "auto", conn)
            snapshot["auto_orders_today"] = n
            if n >= auto["max_orders_per_day"]:
                blocks.append(f"Limite de {auto['max_orders_per_day']} entradas automáticas no dia atingido.")
        pnl_day = realized_today(account, conn)
        snapshot["realized_today"] = pnl_day
        if auto["max_daily_loss"] > 0 and pnl_day <= -auto["max_daily_loss"]:
            limit(f"Perda do dia (R$ {pnl_day:,.2f}) atingiu o limite de R$ {auto['max_daily_loss']:,.2f}.")

    return {"ok": not blocks, "blocks": blocks, "warnings": warns, "snapshot": snapshot}


__all__ = ["check_order", "orders_today", "realized_today"]
