"""Fase 6: ordens (MT5 / simulação), estado da execução, automação e botão de pânico."""
from flask import Blueprint, jsonify, request

from src.core.config import get_prefs
from src.execution import automation, orders
from src.execution.risk import check_order
from src.core import b3_tickers

bp = Blueprint("execution_api", __name__, url_prefix="/api")


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        raise ValueError("Número inválido")


@bp.get("/execution")
def get_execution():
    state = orders.execution_state(with_health=request.args.get("health") != "0")
    return jsonify({
        "state": state,
        "orders": orders.list_orders(limit=int(request.args.get("limit", 30))),
        "automation_log": automation.recent_log(30),
    })


def _payload():
    d = request.get_json(silent=True) or {}
    return {
        "ticker": b3_tickers.clean_ticker(d.get("ticker")),
        "side": str(d.get("side") or "").upper(),
        "quantity": _num(d.get("quantity")) or 0.0,
        "order_type": d.get("order_type") or None,
        "limit_price": _num(d.get("limit_price")),
        "purpose": d.get("purpose") if d.get("purpose") in ("entry", "exit") else "entry",
        "signal_id": d.get("signal_id") or None,
        "cycle_id": d.get("cycle_id") or None,
    }


@bp.post("/orders/check")
def check():
    """Pré-visualização para o modal de confirmação: estado + checagens de risco, sem enviar nada."""
    p = _payload()
    prefs = get_prefs()
    state = orders.execution_state(prefs, with_health=True)
    asset = b3_tickers.asset_class(None, p["ticker"])
    lot = 1 if asset in ("FUTURO", "FOREX", "INDICE", "COMMODITY", "CRIPTO") else int(prefs["sizing"]["lot_step"] or 100)
    risk = check_order(ticker=p["ticker"], side=p["side"], quantity=p["quantity"], price=p["limit_price"], purpose=p["purpose"],
                       origin="manual", account=state["account"], lot=lot, prefs=prefs)
    return jsonify({"state": state, "risk": risk})


@bp.post("/orders")
def place():
    p = _payload()
    order = orders.submit(**p, origin="manual")
    return jsonify(order), 201


@bp.get("/orders")
def list_orders():
    return jsonify(orders.list_orders(account=request.args.get("account") or None,
                                      only_open=request.args.get("open") == "1",
                                      limit=min(int(request.args.get("limit", 50)), 200)))


@bp.post("/orders/<int:order_id>/cancel")
def cancel(order_id):
    return jsonify(orders.cancel(order_id))


@bp.post("/orders/sync")
def sync():
    return jsonify(orders.sync_open_orders())


@bp.post("/execution/panic")
def panic():
    return jsonify(automation.panic())
