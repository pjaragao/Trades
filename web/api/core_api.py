"""Status geral, tela Hoje e sincronização manual."""
from flask import Blueprint, jsonify, request

from src import __version__
from src.core import db
from src.core.config import execution_flags, get_prefs
from src.core.market_hours import market_status, now_brt, to_brt
from src.services import alerts, journal, performance, portfolio, signals
from src.services.signal_monitor import get_monitor
from src.services.sizing import build_ticket, exit_ticket

bp = Blueprint("core_api", __name__, url_prefix="/api")


@bp.get("/status")
def status():
    return jsonify({
        "version": __version__,
        "monitor": get_monitor().status(),
        "market": market_status(),
        "portfolio": portfolio.summary(),
        "alerts": {"unread": alerts.unread_count(), "last_id": alerts.last_id()},
        "execution": execution_flags(),
        "now": now_brt().isoformat(timespec="seconds"),
    })


@bp.post("/sync")
def sync_now():
    result = get_monitor().run_cycle()
    return jsonify({"ok": bool(result) or get_monitor().status()["state"] == "live", "monitor": get_monitor().status()})


@bp.post("/sync/history")
def sync_history():
    db.kv_set("history_synced_at", None)
    result = get_monitor().run_cycle()
    return jsonify({"ok": "history" in result, "result": result.get("history"), "monitor": get_monitor().status()})


def _profiles_index():
    return {(p["trader"].lower(), p["asset_class"]): p for p in performance.trader_profiles()}


def ticket_for(sig, prefs, exposure, profiles, **overrides):
    profile = profiles.get((sig["trader"].lower(), sig["asset_class"]))
    sig["profile"] = profile
    return build_ticket(sig, prefs, exposure=exposure, trader_profile=profile, **overrides)


@bp.get("/today")
def today():
    prefs = get_prefs()
    now = now_brt()
    with db.connection() as c:
        led = journal.ledger(c)
        positions = portfolio.positions(c, led)
        exposure = portfolio.exposure(c, led)
        open_sigs = signals.open_followed(c)
    profiles = _profiles_index()
    fresh_hours = prefs["follow"]["fresh_hours"]
    held_tickers = {p["ticker"] for p in positions}

    new_signals, reminders, inbox = [], [], 0
    for s in open_sigs:
        d = s.get("decision")
        if s["ticker"] in held_tickers and not d:
            continue
        if d is None:
            if s["age_hours"] is not None and s["age_hours"] <= fresh_hours:
                s["ticket"] = ticket_for(s, prefs, exposure, profiles)
                new_signals.append(s)
            else:
                inbox += 1
        elif d["status"] == "snoozed":
            remind = to_brt(d.get("remind_at"))
            if remind and remind <= now:
                s["ticket"] = ticket_for(s, prefs, exposure, profiles)
                reminders.append(s)

    exits = []
    for p in positions:
        if p["exit_pending"]:
            exits.append({**p, "exit_ticket": exit_ticket(p, p.get("signal"), prefs)})

    return jsonify({
        "new_signals": new_signals,
        "reminders": reminders,
        "exits_pending": exits,
        "positions": positions,
        "summary": portfolio.summary(),
        "inbox_count": inbox,
        "recent_alerts": alerts.list_alerts(limit=8),
        "market": market_status(),
        "fresh_hours": fresh_hours,
    })
