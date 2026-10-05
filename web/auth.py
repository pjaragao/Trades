"""
Login simples por senha única (COPILOTO_PASSWORD) — necessário quando o app fica exposto na rede (Docker/homelab).

- Sem COPILOTO_PASSWORD definido, o acesso é livre (uso local em 127.0.0.1).
- Sessão por cookie assinado (SECRET_KEY ou chave gerada e salva no diretório de dados), válida por 30 dias.
- Limite de tentativas por IP para dificultar força bruta.
"""
import hmac
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from src.core.config import DATABASE_DIR

log = logging.getLogger("copiloto.auth")

PUBLIC_PATHS = ("/login", "/logout", "/api/health", "/static/")
MAX_ATTEMPTS = 8
WINDOW_SECONDS = 300
_attempts = defaultdict(deque)


def _secret_key() -> str:
    env = os.getenv("SECRET_KEY", "").strip()
    if env:
        return env
    path = DATABASE_DIR / ".secret_key"
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_hex(32)
        path.write_text(key, encoding="utf-8")
        return key
    except OSError:
        return secrets.token_hex(32)


def _too_many(ip: str) -> bool:
    q = _attempts[ip]
    now = time.time()
    while q and now - q[0] > WINDOW_SECONDS:
        q.popleft()
    return len(q) >= MAX_ATTEMPTS


def init_auth(app: Flask) -> None:
    password = os.getenv("COPILOTO_PASSWORD", "")
    app.secret_key = _secret_key()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        AUTH_ENABLED=bool(password),
    )
    trust = os.getenv("TRUST_PROXY", "").strip().lower()
    hops = int(trust) if trust.isdigit() else (1 if trust in ("true", "yes") else 0)
    if hops:  # nº de proxies na frente (ex.: 2 = nginx -> Traefik do Coolify -> app)
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)
    if not password:
        log.warning("COPILOTO_PASSWORD não definido: acesso sem login (use só em 127.0.0.1).")
        return

    @app.before_request
    def _guard():
        if any(request.path.startswith(p) for p in PUBLIC_PATHS) or session.get("auth"):
            return None
        if request.path.startswith("/api/"):
            return jsonify({"error": "Sessão expirada — faça login novamente.", "login": True}), 401
        return redirect(url_for("login", next=request.path))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            ip = request.remote_addr or "?"
            if _too_many(ip):
                error = "Muitas tentativas. Aguarde alguns minutos."
            elif hmac.compare_digest(request.form.get("password", "").encode(), password.encode()):
                session.clear()
                session["auth"] = True
                session.permanent = True
                _attempts.pop(ip, None)
                nxt = request.args.get("next") or "/"
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")
            else:
                _attempts[ip].append(time.time())
                error = "Senha incorreta."
        return render_template("login.html", error=error), (401 if error else 200)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))
