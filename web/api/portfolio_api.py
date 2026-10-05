"""Carteira (posições), execuções registradas e cotações manuais."""
from flask import Blueprint, jsonify, request

from src.core import db
from src.core.config import get_prefs
from src.core.market_hours import now_brt
from src.services import journal, portfolio
from src.services.sizing import exit_ticket

bp = Blueprint("portfolio_api", __name__, url_prefix="/api")


def _account():
    a = request.args.get("account") or "real"
    return a if a in ("real", "paper") else "real"


@bp.get("/portfolio")
def get_portfolio():
    from src.execution.orders import open_orders_index

    prefs = get_prefs()
    account = _account()
    positions = portfolio.positions(account=account)
    idx = open_orders_index(account)
    for p in positions:
        p["exit_ticket"] = exit_ticket(p, p.get("signal"), prefs)
        p["open_orders"] = idx.get(f"cycle:{p['cycle_id']}", []) or idx.get(f"ticker:{p['ticker']}", [])
    with db.connection() as c:
        has_paper = c.execute("SELECT 1 FROM executions WHERE account = 'paper' LIMIT 1").fetchone() is not None
    return jsonify({"positions": positions, "summary": portfolio.summary(account=account), "account": account, "has_paper": has_paper})


@bp.get("/executions")
def list_executions():
    return jsonify(journal.list_executions(ticker=request.args.get("ticker"), signal_id=request.args.get("signal_id"), account=_account()))


@bp.post("/executions")
def add_execution():
    data = request.get_json(silent=True) or {}
    if not data.get("executed_at"):
        data["executed_at"] = now_brt().isoformat(timespec="seconds")
    row = journal.add_execution(data, allow_short=bool(data.get("allow_short")))
    return jsonify(row), 201


@bp.put("/executions/<int:exec_id>")
def update_execution(exec_id):
    data = request.get_json(silent=True) or {}
    return jsonify(journal.update_execution(exec_id, data, allow_short=bool(data.get("allow_short"))))


@bp.delete("/executions/<int:exec_id>")
def delete_execution(exec_id):
    journal.delete_execution(exec_id)
    return jsonify({"ok": True})


@bp.get("/fees/estimate")
def fees_estimate():
    asset = request.args.get("asset_class", "OPCAO")
    gross = float(request.args.get("gross", 0) or 0)
    return jsonify({"fees": journal.estimate_fees(asset, gross)})


@bp.post("/positions/<path:cycle_id>/keep")
def keep_position(cycle_id):
    portfolio.keep_position(cycle_id)
    return jsonify({"ok": True})


@bp.put("/quotes/<ticker>")
def set_quote(ticker):
    data = request.get_json(silent=True) or {}
    portfolio.set_manual_quote(ticker, data.get("price"))
    return jsonify({"ok": True})
