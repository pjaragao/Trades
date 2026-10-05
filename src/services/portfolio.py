"""
Carteira: minhas posições abertas (derivadas das execuções), marcadas a mercado e comparadas ao sinal.
"""
from typing import Any, Dict, List, Optional

from src.core import db
from src.core.config import get_prefs
from src.core.market_hours import now_brt, to_brt
from src.services import journal
from src.services.signals import hydrate, signal_return_pct

SIGNAL_LINK_WINDOW_DAYS = 5
KEEP_PREFIX = "exit_kept:"


def _quotes(conn) -> Dict[str, Dict[str, Any]]:
    return {r["ticker"]: dict(r) for r in conn.execute("SELECT * FROM quotes")}


def _signals_by_ids(conn, ids: List[str], prefs) -> Dict[str, Dict[str, Any]]:
    if not ids:
        return {}
    rows = conn.execute(f"SELECT * FROM signals WHERE id IN ({','.join('?' * len(ids))})", ids)
    return {r["id"]: hydrate(dict(r), prefs) for r in rows}


def _guess_signal(conn, ticker: str, opened_at: Optional[str], prefs) -> Optional[Dict[str, Any]]:
    """Posição sem vínculo explícito: usa o sinal mais recente do mesmo ativo aberto até alguns dias antes da minha entrada."""
    opened = to_brt(opened_at)
    best = None
    for r in conn.execute("SELECT * FROM signals WHERE ticker = ? ORDER BY timestamp_entrada DESC", (ticker,)):
        entry = to_brt(r["timestamp_entrada"])
        if opened and entry and (entry - opened).days > 1:
            continue
        if opened and entry and (opened - entry).days > SIGNAL_LINK_WINDOW_DAYS + 30:
            break
        best = hydrate(dict(r), prefs)
        break
    return best


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or not b:
        return None
    return round((a / b - 1) * 100, 2)


def positions(conn=None, led: Optional[Dict[str, Any]] = None, account: str = "real") -> List[Dict[str, Any]]:
    prefs = get_prefs(conn)
    with db.connection(conn) as c:
        led = led or journal.ledger(c, account)
        quotes = _quotes(c)
        cycles = {cy["id"]: cy for cy in led["cycles"]}
        all_ids = sorted({sid for p in led["positions"] for sid in p["signal_ids"]})
        sigs = _signals_by_ids(c, all_ids, prefs)
        kept = {r["key"][len(KEEP_PREFIX):] for r in c.execute("SELECT key FROM kv WHERE key LIKE ?", (KEEP_PREFIX + "%",))}

        out = []
        for p in led["positions"]:
            linked = [sigs[s] for s in p["signal_ids"] if s in sigs]
            guessed = False
            if not linked:
                g = _guess_signal(c, p["ticker"], p["opened_at"], prefs)
                if g:
                    linked, guessed = [g], True
            primary = linked[0] if linked else None

            q = quotes.get(p["ticker"])
            last = q["price"] if q else (primary.get("preco_atual") if primary else None)
            qty = abs(p["qty"])
            if last is not None:
                unreal = (last - p["avg_price"]) * qty if p["side"] == "LONG" else (p["avg_price"] - last) * qty
                unreal = round(unreal, 2)
                market_value = round(last * qty, 2)
            else:
                unreal, market_value = None, None

            cy = cycles.get(p["cycle_id"]) or {}
            my_entry = cy.get("avg_buy") if p["side"] == "LONG" else cy.get("avg_sell")
            sig_entry = primary.get("preco_entrada") if primary else None
            entry_slip = _pct(my_entry, sig_entry)
            if entry_slip is not None and p["side"] == "SHORT":
                entry_slip = -entry_slip

            exit_kept = bool(primary and primary["status"] == "CLOSED" and p["cycle_id"] in kept)
            exit_pending = bool(primary and primary["status"] == "CLOSED") and not exit_kept
            alerts = []
            if primary and last is not None:
                stop, target = primary.get("stop_loss"), primary.get("take_profit")
                if stop and ((p["side"] == "LONG" and last <= stop) or (p["side"] == "SHORT" and last >= stop)):
                    alerts.append({"kind": "stop", "level": "danger", "text": f"Preço atingiu o stop do analista ({stop})"})
                if target and ((p["side"] == "LONG" and last >= target) or (p["side"] == "SHORT" and last <= target)):
                    alerts.append({"kind": "target", "level": "success", "text": f"Preço atingiu o alvo do analista ({target})"})
            if primary and primary.get("days_to_expiration") is not None and primary["days_to_expiration"] <= 5 and not exit_pending:
                alerts.append({"kind": "expiry", "level": "warning", "text": f"Opção vence em {primary['days_to_expiration']} dia(s)"})

            out.append({
                **p,
                "quantity": qty,
                "last_price": last,
                "last_price_source": q["source"] if q else ("tradingfloors" if last is not None else None),
                "last_price_at": q["updated_at"] if q else None,
                "market_value": market_value,
                "unrealized_pnl": unreal,
                "unrealized_pct": round(unreal / p["invested"] * 100, 2) if unreal is not None and p["invested"] else None,
                "my_entry": my_entry,
                "fees_paid": cy.get("fees"),
                "signal": primary,
                "signal_guessed": guessed,
                "signal_entry": sig_entry,
                "entry_slippage_pct": entry_slip,
                "signal_return_pct": (primary.get("return_final_pct") if exit_pending else primary.get("return_now_pct")) if primary else None,
                "exit_pending": exit_pending,
                "exit_kept": exit_kept,
                "account": account,
                "alerts": alerts,
            })
    out.sort(key=lambda x: (not x["exit_pending"], x["opened_at"] or ""))
    return out


def exposure(conn=None, led: Optional[Dict[str, Any]] = None, account: str = "real") -> float:
    led = led or journal.ledger(conn, account)
    return round(sum(p["invested"] for p in led["positions"]), 2)


def summary(conn=None, account: str = "real") -> Dict[str, Any]:
    prefs = get_prefs(conn)
    with db.connection(conn) as c:
        led = journal.ledger(c, account)
        pos = positions(c, led, account)
    today = now_brt().date().isoformat()
    month = today[:7]
    invested = round(sum(p["invested"] for p in led["positions"]), 2)
    unreal = [p["unrealized_pnl"] for p in pos if p["unrealized_pnl"] is not None]
    capital = float(prefs["capital"]["total"])
    realized_total = round(sum(e["pnl"] for e in led["events"]), 2)
    return {
        "capital": capital,
        "invested": invested,
        "free": round(capital - invested, 2),
        "open_positions": len(pos),
        "exit_pending": sum(1 for p in pos if p["exit_pending"]),
        "unrealized_pnl": round(sum(unreal), 2) if unreal else 0.0,
        "unpriced_positions": sum(1 for p in pos if p["unrealized_pnl"] is None),
        "realized_today": round(sum(e["pnl"] for e in led["events"] if e["date"] == today), 2),
        "realized_month": round(sum(e["pnl"] for e in led["events"] if e["date"].startswith(month)), 2),
        "realized_total": realized_total,
        "equity": round(capital + realized_total, 2),
        "account": account,
    }


def set_manual_quote(ticker: str, price: float, conn=None) -> None:
    from src.core.config import now_iso
    from src.core.b3_tickers import clean_ticker

    if price is None or float(price) < 0:
        raise ValueError("Preço inválido")
    with db.transaction(conn) as c:
        c.execute(
            "INSERT INTO quotes(ticker, price, source, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(ticker) DO UPDATE SET price = excluded.price, source = excluded.source, updated_at = excluded.updated_at",
            (clean_ticker(ticker), float(price), "manual", now_iso()),
        )


def keep_position(cycle_id: str, conn=None) -> None:
    """Usuário decidiu não seguir a saída do analista: some de "Saída pendente", continua na Carteira."""
    db.kv_set(KEEP_PREFIX + cycle_id, "1", conn=conn)


def signal_exposure_for(signal_id: str, conn=None) -> Optional[Dict[str, Any]]:
    """Minha posição atual vinculada a um sinal (ou no mesmo ativo)."""
    for p in positions(conn):
        if signal_id in p["signal_ids"] or (p.get("signal") and p["signal"]["id"] == signal_id):
            return p
    return None


__all__ = ["positions", "exposure", "summary", "set_manual_quote", "signal_exposure_for", "signal_return_pct"]
