"""
Detecção e histórico de sinais que voltaram ao preço originalmente operado.

Quando um usuário ignora um sinal porque "o preço já andou demais", o monitor
continua acompanhando as cotações ao vivo. Se o preço retornar para o valor
original de entrada (ou melhor), o sistema:
1. Registra o evento no histórico (com tempo decorrido, preço original e preço de retorno).
2. Emite um alerta de ação ("Voltou ao preço").
3. Apresenta o sinal no dashboard como oportunidade de reentrada.
"""
from datetime import datetime
import json
import logging
from typing import Any, Dict, List, Optional

from src.core import db
from src.core.config import now_iso
from src.core.market_hours import now_brt, to_brt
from src.services import alerts
from src.services.quotes import live_quote

log = logging.getLogger("copiloto.price_returns")

DRIFT_KEYWORDS = ("andou", "preco", "preço", "longe", "afastou", "distante", "tarde")


def is_price_drift_reason(reason: Optional[str]) -> bool:
    if not reason:
        return False
    r = reason.lower().strip()
    return any(k in r for k in DRIFT_KEYWORDS)


def fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return "menos de 1 min"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    rem_min = minutes % 60
    if hours < 24:
        return f"{hours}h {rem_min}min" if rem_min else f"{hours}h"
    days = hours // 24
    rem_hours = hours % 24
    return f"{days}d {rem_hours}h" if rem_hours else f"{days}d"


def _fmt_price(v: Optional[float]) -> str:
    return "—" if v is None else f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def check_price_returns(conn=None) -> List[Dict[str, Any]]:
    """
    Verifica sinais abertos que foram ignorados por preço e cujo preço atual
    voltou ao patamar da entrada original.
    """
    detected: List[Dict[str, Any]] = []
    now = now_brt()
    now_iso_str = now_iso()
    today_str = now.date().isoformat()

    with db.transaction(conn) as c:
        # Busca sinais abertos que foram ignorados
        rows = [dict(r) for r in c.execute("""
            SELECT s.*, d.reason, d.decided_at, d.status as decision_status
            FROM signals s
            JOIN decisions d ON d.signal_id = s.id
            WHERE s.status = 'OPEN' AND d.status = 'ignored'
        """)]

        for row in rows:
            reason = row.get("reason")
            if not is_price_drift_reason(reason):
                continue

            entry_price = float(row.get("preco_entrada") or 0.0)
            if entry_price <= 0:
                continue

            ticker = row.get("ticker")
            if not ticker:
                continue

            # Cotação ao vivo
            quote = live_quote(ticker)
            if not quote or quote.get("price") is None:
                # Fallback para tabela quotes
                q_row = c.execute("SELECT price, updated_at FROM quotes WHERE ticker = ?", (ticker,)).fetchone()
                if not q_row or q_row["price"] is None:
                    continue
                current_price = float(q_row["price"])
            else:
                current_price = float(quote["price"])

            side = row.get("lado") or ("BUY" if row.get("operacao") == "COMPRA" else "SELL")
            # Critério de retorno ao preço:
            # BUY: preço recuou para <= entry_price (+ tolerância 0.2% para ruído de spread)
            # SELL: preço subiu para >= entry_price (- tolerância 0.2%)
            is_returned = False
            if side == "BUY" and current_price <= (entry_price * 1.002):
                is_returned = True
            elif side == "SELL" and current_price >= (entry_price * 0.998):
                is_returned = True

            if not is_returned:
                continue

            # Calcula tempo decorrido desde a decisão
            decided_dt = to_brt(row.get("decided_at")) or now
            duration_sec = max(0, int((now - decided_dt).total_seconds()))
            dur_fmt = fmt_duration(duration_sec)

            # Verifica se já registramos esse retorno hoje
            existing = c.execute("""
                SELECT id FROM signal_price_returns
                WHERE signal_id = ? AND date(returned_at) = ?
            """, (row["id"], today_str)).fetchone()

            if not existing:
                c.execute("""
                    INSERT INTO signal_price_returns(
                        signal_id, ticker, side, entry_price, ignored_price,
                        returned_price, decided_at, returned_at, duration_seconds,
                        notified, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """, (
                    row["id"], ticker, side, entry_price, row.get("preco_atual"),
                    current_price, row.get("decided_at") or now_iso_str, now_iso_str,
                    duration_sec, now_iso_str,
                ))

            # Cria alerta
            verb = "comprou" if side == "BUY" else "vendeu"
            title = f"Voltou ao preço: {row.get('trader')} {verb} {ticker}"
            body = (
                f"Preço voltou para {_fmt_price(current_price)} (entrada original: {_fmt_price(entry_price)}). "
                f"Demorou {dur_fmt} para voltar após você ignorar."
            )
            dedup = f"price_return:{row['id']}:{today_str}"
            alerts.create_alert(
                c, "price_returned", title, body,
                signal_id=row["id"], ticker=ticker, severity="action", dedup_key=dedup,
            )

            detected.append({
                "signal_id": row["id"],
                "ticker": ticker,
                "side": side,
                "trader": row.get("trader"),
                "entry_price": entry_price,
                "returned_price": current_price,
                "duration_seconds": duration_sec,
                "duration_formatted": dur_fmt,
                "returned_at": now_iso_str,
            })

    return detected


def list_price_returns(limit: int = 50, conn=None) -> List[Dict[str, Any]]:
    """Lista histórico de sinais que voltaram ao preço."""
    with db.connection(conn) as c:
        rows = [dict(r) for r in c.execute(f"""
            SELECT pr.*, s.trader, s.operacao, s.status as signal_status, s.ativo, s.asset_class
            FROM signal_price_returns pr
            JOIN signals s ON s.id = pr.signal_id
            ORDER BY pr.returned_at DESC, pr.id DESC
            LIMIT ?
        """, (limit,))]
    for r in rows:
        r["duration_formatted"] = fmt_duration(r.get("duration_seconds", 0))
    return rows


def active_price_returns(conn=None) -> List[Dict[str, Any]]:
    """
    Retorna os sinais que estão abertos e com retorno de preço recente ativo.
    """
    now = now_brt()
    today_str = now.date().isoformat()
    with db.connection(conn) as c:
        rows = [dict(r) for r in c.execute("""
            SELECT pr.*, s.trader, s.operacao, s.status as signal_status, s.ativo, s.asset_class
            FROM signal_price_returns pr
            JOIN signals s ON s.id = pr.signal_id
            WHERE s.status = 'OPEN' AND pr.dismissed = 0 AND date(pr.returned_at) = ?
            ORDER BY pr.returned_at DESC
        """, (today_str,))]
    for r in rows:
        r["duration_formatted"] = fmt_duration(r.get("duration_seconds", 0))
    return rows


def dismiss_price_return(signal_id: str, conn=None) -> None:
    with db.transaction(conn) as c:
        c.execute("UPDATE signal_price_returns SET dismissed = 1 WHERE signal_id = ?", (signal_id,))
