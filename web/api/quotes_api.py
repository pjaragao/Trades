"""
Cotações ao vivo para a interface.

- GET  /api/quotes          : estado do feed + cotações conhecidas (fallback do navegador sem SSE)
- POST /api/quotes/watch    : acompanha ativos abertos na tela (boleta) e devolve a cotação na hora
- GET  /api/stream          : Server-Sent Events — `quotes` a cada mudança, `ping` a cada 15 s

O stream fecha sozinho depois de alguns minutos (o navegador reconecta) para não prender threads do
gunicorn; `X-Accel-Buffering: no` desliga o buffer do nginx.
"""
import json
import time

from flask import Blueprint, Response, jsonify, request

from src.core.config import now_iso
from src.services.quotes import get_feed

bp = Blueprint("quotes_api", __name__, url_prefix="/api")

PING_SECONDS = 15
STREAM_MAX_SECONDS = 300
RETRY_MS = 3000


def _payload(quotes, full: bool):
    return {"full": full, "quotes": quotes, "feed": get_feed().status(), "now": now_iso()}


@bp.get("/quotes")
def list_quotes():
    _, snap = get_feed().snapshot()
    return jsonify(_payload(snap, True))


@bp.post("/quotes/watch")
def watch():
    data = request.get_json(silent=True) or {}
    tickers = [str(t) for t in (data.get("tickers") or [])][:20]
    return jsonify(_payload(get_feed().ensure(tickers), False))


def _event(name: str, data) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _key(q):
    return (q.get("price"), q.get("bid"), q.get("ask"), q.get("last"), q.get("live"), q.get("change_pct"))


@bp.get("/stream")
def stream():
    feed = get_feed()

    def gen():
        version, snap = feed.snapshot()
        sent = {t: _key(q) for t, q in snap.items()}
        yield f"retry: {RETRY_MS}\n\n"
        yield _event("quotes", _payload(snap, True))
        deadline = time.monotonic() + STREAM_MAX_SECONDS
        while time.monotonic() < deadline:
            new_version = feed.wait(version, PING_SECONDS)
            if new_version == version:
                yield _event("ping", {"feed": feed.status(), "now": now_iso()})
                continue
            version, snap = feed.snapshot()
            diff = {t: q for t, q in snap.items() if sent.get(t) != _key(q)}
            sent.update({t: _key(q) for t, q in diff.items()})
            yield _event("quotes", _payload(diff, False))

    headers = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
    return Response(gen(), mimetype="text/event-stream", headers=headers)
