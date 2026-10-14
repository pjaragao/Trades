"""Sinais dos analistas, boleta pronta, decisões e perfil dos analistas."""
from flask import Blueprint, jsonify, request

from src.core import db
from src.core.config import get_prefs
from src.services import alerts, journal, performance, portfolio, signals
from web.api.core_api import _profiles_index, ticket_for

bp = Blueprint("signals_api", __name__, url_prefix="/api")


def _float_arg(name):
    v = request.args.get(name)
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        raise ValueError(f"Parâmetro inválido: {name}")


@bp.get("/signals")
def list_signals():
    a = request.args
    data = signals.list_signals(
        status=a.get("status", "open"),
        scope=a.get("scope", "followed"),
        trader=a.get("trader") or None,
        asset_class=a.get("asset_class") or None,
        decision=a.get("decision") or None,
        q=a.get("q") or None,
        limit=min(int(a.get("limit", 100)), 500),
        offset=int(a.get("offset", 0)),
    )
    profiles = _profiles_index()
    for s in data["items"]:
        s["profile"] = profiles.get((s["trader"].lower(), s["asset_class"]))
    return jsonify(data)


@bp.get("/signals/<signal_id>")
def get_signal(signal_id):
    sig = signals.get_signal(signal_id)
    if not sig:
        raise KeyError(signal_id)
    prefs = get_prefs()
    with db.connection() as c:
        led = journal.ledger(c)
        exposure = portfolio.exposure(c, led)
        positions = portfolio.positions(c, led)
    sig["ticket"] = ticket_for(sig, prefs, exposure, _profiles_index())
    sig["executions"] = journal.list_executions(signal_id=signal_id)
    sig["position"] = next((p for p in positions if signal_id in p["signal_ids"] or (p.get("signal") or {}).get("id") == signal_id), None)
    from src.services import similar

    sig["similar"] = similar.find(sig, positions) if sig["status"] == "OPEN" else []
    return jsonify(sig)


@bp.post("/signals/<signal_id>/link-position")
def link_position(signal_id):
    """'É este trade': vincula a minha posição (ciclo) ao sinal e marca como executado."""
    from src.services import auto_link

    data = request.get_json(silent=True) or {}
    with db.transaction() as c:
        n = auto_link.link_cycle(c, signal_id, str(data.get("cycle_id") or ""))
    if not n:
        raise ValueError("Nada para vincular: a posição não tem execuções sem sinal no mesmo lado.")
    return jsonify({"linked": n})


@bp.get("/signals/<signal_id>/ticket")
def get_ticket(signal_id):
    sig = signals.get_signal(signal_id)
    if not sig:
        raise KeyError(signal_id)
    prefs = get_prefs()
    exposure = portfolio.exposure()
    return jsonify(ticket_for(sig, prefs, exposure, _profiles_index(), quantity=_float_arg("quantity"), limit_price=_float_arg("limit_price")))


@bp.post("/signals/<signal_id>/decision")
def decide(signal_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status == "clear":
        signals.clear_decision(signal_id)
        return jsonify({"ok": True})
    result = signals.set_decision(signal_id, status, data.get("reason"), data.get("remind_minutes"))
    alerts.mark_signal_alerts_read(signal_id, ["new_signal", "reminder"])
    return jsonify({"ok": True, "decision": result})


@bp.get("/signals/price-returns")
def price_returns_history():
    from src.services import price_returns

    limit = min(int(request.args.get("limit", 50)), 200)
    return jsonify({"items": price_returns.list_price_returns(limit=limit)})


@bp.post("/signals/<signal_id>/dismiss-return")
def dismiss_price_return(signal_id):
    from src.services import price_returns

    price_returns.dismiss_price_return(signal_id)
    alerts.mark_signal_alerts_read(signal_id, ["price_returned"])
    return jsonify({"ok": True})


@bp.get("/traders")
def traders():
    prefs = get_prefs()
    followed = {t.lower() for t in prefs["follow"]["traders"]}
    rows = performance.trader_profiles()
    for r in rows:
        r["followed"] = (not followed or r["trader"].lower() in followed) and (
            not prefs["follow"]["asset_classes"] or r["asset_class"] in prefs["follow"]["asset_classes"])
    return jsonify(rows)

