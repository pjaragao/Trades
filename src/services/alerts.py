"""
Alertas (novo sinal, saída pendente, stop/alvo, sistema) e envio de notificações.

O navegador busca alertas novos por id (/api/alerts?after_id=) e dispara Notification API + som.
O Telegram (opcional) é enviado aqui mesmo, em segundo plano, quando habilitado.
"""
import threading
from typing import Any, Dict, List, Optional

import requests

from src.core import db
from src.core.config import get_prefs, now_iso, telegram_credentials

NOTIFY_KINDS = {"new_signal", "exit_pending", "stop_hit", "target_hit", "reminder"}


def create_alert(
    conn,
    kind: str,
    title: str,
    body: str = "",
    signal_id: Optional[str] = None,
    ticker: Optional[str] = None,
    severity: str = "info",
    dedup_key: Optional[str] = None,
) -> Optional[int]:
    cur = conn.execute(
        "INSERT OR IGNORE INTO alerts(kind, signal_id, ticker, title, body, severity, created_at, dedup_key) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (kind, signal_id, ticker, title, body, severity, now_iso(), dedup_key),
    )
    return cur.lastrowid if cur.rowcount else None


def list_alerts(unread_only: bool = False, after_id: Optional[int] = None, limit: int = 50, conn=None) -> List[Dict[str, Any]]:
    sql, params, where = "SELECT * FROM alerts", [], []
    if unread_only:
        where.append("read_at IS NULL")
    if after_id is not None:
        where.append("id > ?")
        params.append(int(after_id))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with db.connection(conn) as c:
        return [dict(r) for r in c.execute(sql, params)]


def unread_count(conn=None) -> int:
    with db.connection(conn) as c:
        return c.execute("SELECT COUNT(*) FROM alerts WHERE read_at IS NULL").fetchone()[0]


def last_id(conn=None) -> int:
    with db.connection(conn) as c:
        return c.execute("SELECT COALESCE(MAX(id), 0) FROM alerts").fetchone()[0]


def mark_read(ids: Optional[List[int]] = None, conn=None) -> int:
    with db.transaction(conn) as c:
        if ids:
            marks = ",".join("?" * len(ids))
            cur = c.execute(f"UPDATE alerts SET read_at = ? WHERE read_at IS NULL AND id IN ({marks})", [now_iso(), *ids])
        else:
            cur = c.execute("UPDATE alerts SET read_at = ? WHERE read_at IS NULL", (now_iso(),))
        return cur.rowcount


def mark_signal_alerts_read(signal_id: str, kinds: Optional[List[str]] = None, conn=None) -> None:
    with db.transaction(conn) as c:
        sql = "UPDATE alerts SET read_at = ? WHERE read_at IS NULL AND signal_id = ?"
        params: List[Any] = [now_iso(), signal_id]
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            params += kinds
        c.execute(sql, params)


# ---------------------------------------------------------------------------
# Telegram (opcional)
# ---------------------------------------------------------------------------

def telegram_configured() -> bool:
    token, chat = telegram_credentials()
    return bool(token and chat)


def send_telegram(text: str) -> bool:
    token, chat = telegram_credentials()
    if not (token and chat):
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


def dispatch_pending(conn=None) -> int:
    """Envia ao Telegram os alertas notificáveis ainda não enviados (marca notified_at em todos)."""
    prefs = get_prefs(conn)
    with db.transaction(conn) as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM alerts WHERE notified_at IS NULL ORDER BY id")]
        if not rows:
            return 0
        c.execute(
            f"UPDATE alerts SET notified_at = ? WHERE id IN ({','.join('?' * len(rows))})",
            [now_iso(), *[r["id"] for r in rows]],
        )
    to_send = [r for r in rows if r["kind"] in NOTIFY_KINDS]
    if prefs["alerts"].get("telegram") and telegram_configured() and to_send:
        def _send():
            for r in to_send:
                send_telegram(f"{r['title']}\n{r['body'] or ''}".strip())
        threading.Thread(target=_send, daemon=True).start()
    return len(to_send)
