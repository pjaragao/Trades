"""Preferências do usuário e informações do sistema para a tela Configurações."""
from flask import Blueprint, jsonify, request

from src.core import db
from src.core.b3_tickers import ASSET_CLASS_LABELS
from src.core.config import execution_flags, get_prefs, monitor_poll_seconds, tf_settings, update_prefs
from src.services import alerts, performance
from src.services.signal_monitor import get_monitor

bp = Blueprint("settings_api", __name__, url_prefix="/api")


def _system():
    url, key, email, pwd = tf_settings()
    with db.connection() as c:
        traders = [r[0] for r in c.execute("SELECT trader FROM signals GROUP BY trader ORDER BY COUNT(*) DESC")]
    return {
        "tf_configured": bool(url and key and email and pwd),
        "tf_email": email,
        "telegram_configured": alerts.telegram_configured(),
        "poll_seconds": monitor_poll_seconds(),
        "execution": {**{k: v for k, v in execution_flags().items() if k != "mt5_agent_token"},
                      "agent_token_set": bool(execution_flags()["mt5_agent_token"])},
        "db_path": str(db.db_path()),
        "asset_classes": ASSET_CLASS_LABELS,
        "traders": traders,
    }


@bp.get("/settings")
def get_settings():
    return jsonify({"prefs": get_prefs(), "system": _system()})


@bp.put("/settings")
def put_settings():
    data = request.get_json(silent=True) or {}
    ex = data.get("execution") or {}
    if ex.get("mode") == "live" and not execution_flags()["enabled"]:
        raise ValueError("Modo real bloqueado: ligue execution.enabled no settings.yaml ou EXECUTION_ENABLED=true no Docker.")
    prefs = update_prefs(data)
    performance.invalidate_cache()
    get_monitor().trigger()
    return jsonify({"prefs": prefs, "system": _system()})
