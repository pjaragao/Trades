"""
Ordens (Fase 6): envio ao MT5 ou à conta simulada, acompanhamento e conversão dos
preenchimentos em execuções do diário.

Regras de segurança:
- modo 'off'  -> nada é enviado;
- modo 'live' -> exige a trava `execution.enabled` (settings.yaml ou EXECUTION_ENABLED=true);
- se o envio falhar sem confirmação do conector, a ordem fica 'unknown' (confira no MT5 antes de reenviar);
- preenchimentos são idempotentes (cada negócio do conector vira uma execução, uma única vez).
"""
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.core import b3_tickers, db
from src.core.config import execution_flags, get_prefs, now_iso, now_utc
from src.execution.brokers import BrokerError, get_broker
from src.execution.risk import check_order
from src.services import alerts, journal

log = logging.getLogger("copiloto.orders")
_lock = threading.RLock()

OPEN_STATUSES = ("sending", "open", "partial")
FINAL_STATUSES = ("filled", "cancelled", "rejected", "expired", "error", "unknown")


# ---------------------------------------------------------------- estado
def execution_state(prefs: Optional[Dict[str, Any]] = None, with_health: bool = False) -> Dict[str, Any]:
    prefs = prefs or get_prefs()
    ex = prefs["execution"]
    flags = execution_flags()
    mode = ex["mode"]
    account = "paper" if mode == "paper" else "real"
    can_send, reason = True, ""
    if mode == "off":
        can_send, reason = False, "Execução desligada (Configurações › Execução)."
    elif mode == "live" and not flags["enabled"]:
        can_send, reason = False, "Modo real bloqueado: ligue execution.enabled no settings.yaml ou EXECUTION_ENABLED=true."
    state = {
        "mode": mode,
        "account": account,
        "order_type": ex["order_type"],
        "gate_enabled": flags["enabled"],
        "broker": "paper" if mode == "paper" else flags["broker"],
        "agent_url": flags["mt5_agent_url"] if flags["broker"] == "mt5_remote" else None,
        "can_send": can_send,
        "reason": reason,
        "auto": ex["auto"],
        "armed": bool(ex["auto"]["armed"]) and can_send,
    }
    if with_health and mode != "off":
        try:
            state["health"] = get_broker(account).health()
        except BrokerError as exc:
            state["health"] = {"ok": False, "connected": False, "message": str(exc), "account": None}
        if not state["health"]["ok"]:
            state["can_send"] = False
            state["reason"] = state["reason"] or state["health"]["message"]
    return state


# ---------------------------------------------------------------- consulta
def get_order(order_id: int, conn=None) -> Optional[Dict[str, Any]]:
    with db.connection(conn) as c:
        row = c.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return _hydrate(dict(row)) if row else None


def _hydrate(o: Dict[str, Any]) -> Dict[str, Any]:
    o["risk"] = json.loads(o.pop("risk_json") or "null")
    o["is_open"] = o["status"] in OPEN_STATUSES
    return o


def list_orders(account: Optional[str] = None, only_open: bool = False, limit: int = 50, conn=None) -> List[Dict[str, Any]]:
    sql, params, where = "SELECT * FROM orders", [], []
    if account:
        where.append("account = ?")
        params.append(account)
    if only_open:
        where.append(f"status IN ({','.join('?' * len(OPEN_STATUSES))})")
        params += list(OPEN_STATUSES)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with db.connection(conn) as c:
        return [_hydrate(dict(r)) for r in c.execute(sql, params)]


def open_orders_index(account: str, conn=None) -> Dict[str, List[Dict[str, Any]]]:
    """{signal_id ou 'cycle:<id>' ou 'ticker:<t>': [ordens abertas]}"""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for o in list_orders(account, only_open=True, limit=200, conn=conn):
        for key in filter(None, [o["signal_id"], o["cycle_id"] and f"cycle:{o['cycle_id']}", f"ticker:{o['ticker']}"]):
            out.setdefault(key, []).append(o)
    return out


# ---------------------------------------------------------------- envio
def submit(*, ticker: str, side: str, quantity: float, order_type: Optional[str] = None, limit_price: Optional[float] = None,
           purpose: str = "entry", origin: str = "manual", signal_id: Optional[str] = None, cycle_id: Optional[str] = None,
           prefs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Envia uma ordem. Levanta ValueError se bloqueada (para ordens manuais)."""
    prefs = prefs or get_prefs()
    state = execution_state(prefs)
    if not state["can_send"]:
        raise ValueError(state["reason"])
    account = state["account"]
    ticker = b3_tickers.clean_ticker(ticker)
    side = str(side).upper()
    order_type = order_type or prefs["execution"]["order_type"]
    if side not in ("BUY", "SELL"):
        raise ValueError("Lado inválido.")
    if order_type == "limit" and (limit_price is None or float(limit_price) <= 0):
        raise ValueError("Informe o preço limite.")
    quantity = float(quantity or 0)
    asset = b3_tickers.asset_class(None, ticker)
    lot = 1 if asset in ("FUTURO", "FOREX", "INDICE", "COMMODITY", "CRIPTO") else int(prefs["sizing"]["lot_step"] or 100)

    with _lock:
        risk = check_order(ticker=ticker, side=side, quantity=quantity, price=float(limit_price) if limit_price else None,
                           purpose=purpose, origin=origin, account=account, lot=lot, prefs=prefs)
        if not risk["ok"]:
            raise ValueError(" ".join(risk["blocks"]))

        with db.transaction() as c:
            cur = c.execute(
                "INSERT INTO orders(account, broker, origin, purpose, signal_id, cycle_id, ticker, asset_class, side, quantity, "
                "order_type, limit_price, status, risk_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (account, state["broker"], origin, purpose, signal_id, cycle_id, ticker, asset, side, quantity, order_type,
                 float(limit_price) if limit_price else None, "sending", json.dumps(risk, ensure_ascii=False), now_iso(), now_iso()),
            )
            order_id = cur.lastrowid

        try:
            broker = get_broker(account)
            res = broker.place_order(ticker, side, quantity, order_type, float(limit_price) if limit_price else None,
                                     comment=f"Copiloto #{order_id}")
        except BrokerError as exc:
            _update(order_id, status="unknown", message=f"Sem confirmação do conector: {exc}. Confira no MT5 antes de reenviar.")
            _order_alert(order_id, "order_problem", "danger")
            raise ValueError(f"Não foi possível confirmar o envio: {exc}. Confira no MT5 antes de reenviar.")

        status = res["status"] if res.get("accepted") else "rejected"
        _update(order_id, status=status, broker_order_id=res.get("broker_order_id"), message=res.get("message"), sent_at=now_iso(),
                closed_at=now_iso() if status in FINAL_STATUSES else None)
        if res.get("fills"):
            _apply_fills(order_id, res["fills"])
        order = get_order(order_id)
        if status == "rejected":
            _order_alert(order_id, "order_rejected", "danger")
        log.info("Ordem #%s %s %s %s @ %s -> %s", order_id, side, quantity, ticker, limit_price, order["status"])
        return order


def _update(order_id: int, conn=None, **fields) -> None:
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    with db.transaction(conn) as c:
        c.execute(f"UPDATE orders SET {sets} WHERE id = ?", [*fields.values(), order_id])


def _apply_fills(order_id: int, fills: List[Dict[str, Any]]) -> int:
    """Grava preenchimentos novos e cria as execuções correspondentes. Retorna quantos eram novos."""
    prefs = get_prefs()
    new = 0
    with db.transaction() as c:
        o = dict(c.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone())
        for f in fills:
            fid = str(f["id"])
            if c.execute("SELECT 1 FROM order_fills WHERE order_id = ? AND broker_fill_id = ?", (order_id, fid)).fetchone():
                continue
            qty, price = float(f["quantity"]), float(f["price"])
            broker_fees = float(f.get("fees") or 0)
            fees = broker_fees if broker_fees > 0 else journal.estimate_fees(o["asset_class"], qty * price, prefs)
            ex = journal.add_execution(
                {"signal_id": o["signal_id"], "ticker": o["ticker"], "side": o["side"], "quantity": qty, "price": price,
                 "fees": fees, "executed_at": f.get("time") or now_iso(), "asset_class": o["asset_class"],
                 "note": f"Ordem #{order_id} ({'simulação' if o['account'] == 'paper' else 'MT5'})"},
                allow_short=True, account=o["account"], source="broker", order_id=order_id,
                fees_source="broker" if broker_fees > 0 else "estimate", conn=c,
            )
            c.execute("INSERT INTO order_fills(order_id, broker_fill_id, quantity, price, fees, filled_at, execution_id) VALUES(?,?,?,?,?,?,?)",
                      (order_id, fid, qty, price, fees, f.get("time") or now_iso(), ex["id"]))
            new += 1
        tot = c.execute("SELECT COALESCE(SUM(quantity),0) q, COALESCE(SUM(quantity*price),0) v FROM order_fills WHERE order_id = ?", (order_id,)).fetchone()
        c.execute("UPDATE orders SET filled_qty = ?, avg_fill_price = ?, updated_at = ? WHERE id = ?",
                  (tot["q"], round(tot["v"] / tot["q"], 6) if tot["q"] else None, now_iso(), order_id))
    if new:
        _order_alert(order_id, "order_filled", "action")
    return new


def _order_alert(order_id: int, kind: str, severity: str) -> None:
    o = get_order(order_id)
    if not o:
        return
    side = "COMPRA" if o["side"] == "BUY" else "VENDA"
    acct = " (simulação)" if o["account"] == "paper" else ""
    titles = {
        "order_filled": f"Ordem executada{acct}: {side} {o['ticker']}",
        "order_rejected": f"Ordem recusada{acct}: {side} {o['ticker']}",
        "order_problem": f"Ordem sem confirmação{acct}: {side} {o['ticker']}",
    }
    body = (f"{o['filled_qty']:,.0f}/{o['quantity']:,.0f} a R$ {o['avg_fill_price']:,.2f}" if o["filled_qty"] and o["avg_fill_price"]
            else (o["message"] or "")).replace(",", "X").replace(".", ",").replace("X", ".")
    with db.transaction() as c:
        alerts.create_alert(c, kind, titles[kind], body, signal_id=o["signal_id"], ticker=o["ticker"], severity=severity,
                            dedup_key=f"{kind}:{order_id}:{o['filled_qty']}")


# ---------------------------------------------------------------- acompanhamento
def sync_open_orders() -> Dict[str, int]:
    """Consulta o conector para cada ordem aberta; registra preenchimentos e cancela ordens automáticas vencidas."""
    stats = {"checked": 0, "fills": 0, "closed": 0, "errors": 0}
    prefs = get_prefs()
    cancel_after = prefs["execution"]["auto"]["cancel_after_minutes"]
    with _lock:
        for o in list_orders(only_open=True, limit=200):
            if not o["broker_order_id"]:
                continue
            stats["checked"] += 1
            try:
                broker = get_broker(o["account"])
                st = broker.order_status(o["broker_order_id"], o["ticker"])
            except BrokerError as exc:
                stats["errors"] += 1
                _update(o["id"], message=f"Sem resposta do conector: {exc}")
                continue
            if st.get("fills"):
                stats["fills"] += _apply_fills(o["id"], st["fills"])
            status = st["status"]
            if status in ("open", "partial") and o["origin"] == "auto":
                created = datetime.fromisoformat(o["created_at"])
                if now_utc() - created > timedelta(minutes=cancel_after):
                    try:
                        broker.cancel_order(o["broker_order_id"], o["ticker"])
                        status = "cancelled"
                        st["message"] = f"Cancelada pela automação após {cancel_after} min sem execução"
                    except BrokerError:
                        pass
            if status != o["status"] or st.get("message"):
                final = status in FINAL_STATUSES
                _update(o["id"], status=status, message=st.get("message") or o["message"], closed_at=now_iso() if final else None)
                stats["closed"] += 1 if final else 0
    return stats


def cancel(order_id: int) -> Dict[str, Any]:
    with _lock:
        o = get_order(order_id)
        if not o:
            raise KeyError(order_id)
        if not o["is_open"]:
            raise ValueError("A ordem não está aberta.")
        if o["broker_order_id"]:
            try:
                res = get_broker(o["account"]).cancel_order(o["broker_order_id"], o["ticker"])
            except BrokerError as exc:
                raise ValueError(f"Não foi possível cancelar: {exc}")
            if not res.get("ok"):
                raise ValueError(res.get("message") or "O conector não confirmou o cancelamento.")
        _update(order_id, status="cancelled", message="Cancelada por você", closed_at=now_iso())
    sync_open_orders()
    return get_order(order_id)


def cancel_all(account: Optional[str] = None) -> int:
    n = 0
    for o in list_orders(account, only_open=True, limit=200):
        try:
            cancel(o["id"])
            n += 1
        except ValueError as exc:
            log.warning("Falha ao cancelar ordem #%s: %s", o["id"], exc)
    return n


def refresh_quotes_from_broker(max_tickers: int = 15) -> int:
    """No modo real, atualiza a cotação das posições abertas pelo MT5 (mais atual que o TradingFloors)."""
    state = execution_state()
    if state["mode"] != "live" or not state["can_send"]:
        return 0
    try:
        broker = get_broker("real")
    except BrokerError:
        return 0
    tickers = [p["ticker"] for p in journal.ledger(None, "real")["positions"]][:max_tickers]
    n = 0
    for t in tickers:
        try:
            q = broker.quote(t)
        except BrokerError:
            return n
        if not q:
            continue
        price = q.get("last") or (((q.get("bid") or 0) + (q.get("ask") or 0)) / 2 if q.get("bid") and q.get("ask") else None)
        if not price:
            continue
        with db.transaction() as c:
            c.execute("INSERT INTO quotes(ticker, price, source, updated_at) VALUES(?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET "
                      "price = excluded.price, source = excluded.source, updated_at = excluded.updated_at", (t, float(price), "mt5", now_iso()))
        n += 1
    return n


__all__ = ["execution_state", "submit", "sync_open_orders", "cancel", "cancel_all", "list_orders", "get_order",
           "open_orders_index", "refresh_quotes_from_broker"]
