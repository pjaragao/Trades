"""Central de alertas (sino da barra superior + notificações do navegador)."""
from flask import Blueprint, jsonify, request

from src.services import alerts

bp = Blueprint("alerts_api", __name__, url_prefix="/api")


@bp.get("/alerts")
def list_alerts():
    after = request.args.get("after_id")
    return jsonify({
        "items": alerts.list_alerts(
            unread_only=request.args.get("unread") == "1",
            after_id=int(after) if after not in (None, "") else None,
            limit=min(int(request.args.get("limit", 50)), 200),
        ),
        "unread": alerts.unread_count(),
        "last_id": alerts.last_id(),
    })


@bp.post("/alerts/read")
def mark_read():
    data = request.get_json(silent=True) or {}
    ids = [int(i) for i in data.get("ids") or []]
    n = alerts.mark_read(ids or None)
    return jsonify({"ok": True, "marked": n, "unread": alerts.unread_count()})


@bp.post("/alerts/test-telegram")
def test_telegram():
    if not alerts.telegram_configured():
        raise ValueError("Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID em config/.env e reinicie o app.")
    ok = alerts.send_telegram("✅ Copiloto de Trades: notificações do Telegram funcionando.")
    if not ok:
        raise ValueError("O Telegram recusou a mensagem. Confira o token e o chat_id.")
    return jsonify({"ok": True})
