"""
Agente MT5 — roda no Windows, ao lado do terminal MetaTrader 5, e expõe uma API HTTP mínima
para o Copiloto (que pode estar em Docker no homelab).

    set MT5_AGENT_TOKEN=um-token-longo-e-secreto
    python -m src.execution.agent --host 0.0.0.0 --port 8765
    python -m src.execution.agent --readonly      # só cotações: recusa qualquer ordem

Requisitos no Windows: pip install flask MetaTrader5 python-dotenv pyyaml
No terminal MT5: conta logada (e "Algo Trading" ligado, para ordens).
Toda requisição precisa de `Authorization: Bearer <MT5_AGENT_TOKEN>`.
"""
import hmac
import logging
import os
import sys

from flask import Flask, jsonify, request

from src.execution.brokers.base import Broker, BrokerError

log = logging.getLogger("mt5-agent")


MAX_SYMBOLS = 100


def create_agent(broker: Broker, token: str, readonly: bool = False) -> Flask:
    if not token or len(token) < 16:
        raise SystemExit("Defina MT5_AGENT_TOKEN com pelo menos 16 caracteres (o mesmo no Copiloto).")
    app = Flask("mt5_agent")
    readonly_msg = "Agente MT5 em modo somente cotações (MT5_AGENT_READONLY) — ordens desativadas"

    @app.before_request
    def _auth():
        sent = request.headers.get("Authorization", "")
        if not hmac.compare_digest(sent, f"Bearer {token}"):
            return jsonify({"error": "não autorizado"}), 401
        return None

    @app.errorhandler(BrokerError)
    def _broker_error(exc):
        return jsonify({"error": str(exc)}), 502

    @app.errorhandler(Exception)
    def _any_error(exc):  # pragma: no cover - proteção
        log.exception("Erro no agente")
        return jsonify({"error": f"Erro interno do agente: {exc}"}), 500

    @app.get("/health")
    def health():
        h = dict(broker.health())
        h["readonly"] = readonly
        if readonly and h.get("connected"):
            h.update(ok=False, message=readonly_msg)
        return jsonify(h)

    @app.get("/quote/<symbol>")
    def quote(symbol):
        return jsonify({"quote": broker.quote(symbol.upper())})

    @app.get("/quotes")
    def quotes():
        symbols = [s.strip().upper() for s in request.args.get("symbols", "").split(",") if s.strip()]
        return jsonify({"quotes": broker.quotes(list(dict.fromkeys(symbols))[:MAX_SYMBOLS])})

    @app.post("/orders")
    def place():
        if readonly:
            return jsonify({"error": readonly_msg}), 403
        d = request.get_json(silent=True) or {}
        side = str(d.get("side", "")).upper()
        order_type = d.get("order_type", "limit")
        qty = float(d.get("quantity") or 0)
        limit = d.get("limit_price")
        if side not in ("BUY", "SELL") or qty <= 0 or order_type not in ("limit", "market") or (order_type == "limit" and not limit):
            return jsonify({"error": "Ordem inválida"}), 400
        log.info("ORDEM %s %s %s @ %s (%s)", side, qty, d.get("symbol"), limit, order_type)
        res = broker.place_order(str(d.get("symbol", "")).upper(), side, qty, order_type, float(limit) if limit else None, d.get("comment", ""))
        log.info(" -> %s", res)
        return jsonify(res)

    @app.get("/orders/<oid>")
    def status(oid):
        return jsonify(broker.order_status(oid, request.args.get("symbol", "")))

    @app.post("/orders/<oid>/cancel")
    def cancel(oid):
        if readonly:
            return jsonify({"error": readonly_msg}), 403
        d = request.get_json(silent=True) or {}
        return jsonify(broker.cancel_order(oid, d.get("symbol", "")))

    return app


def main() -> None:
    import argparse

    from src.core.config import execution_flags, load_env
    from src.execution.brokers.mt5_local import Mt5LocalBroker

    load_env()
    parser = argparse.ArgumentParser(description="Agente MT5 do Copiloto de Trades")
    parser.add_argument("--host", default=os.getenv("MT5_AGENT_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MT5_AGENT_PORT", 8765)))
    parser.add_argument("--readonly", action="store_true", default=os.getenv("MT5_AGENT_READONLY", "").lower() in ("1", "true", "yes"),
                        help="somente cotações: recusa envio/cancelamento de ordens")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    flags = execution_flags()
    broker = Mt5LocalBroker(flags["mt5_terminal_path"], flags["magic_number"])
    h = broker.health()
    print(f"MT5: {h['message']}" + (f" · conta {h['account']['login']} ({h['account']['company']})" if h.get("account") else ""))
    if sys.platform != "win32":
        print("Aviso: o pacote MetaTrader5 só funciona no Windows.")
    app = create_agent(broker, os.getenv("MT5_AGENT_TOKEN", ""), readonly=args.readonly)
    print(f"Agente MT5 ouvindo em http://{args.host}:{args.port}" + (" — SOMENTE COTAÇÕES" if args.readonly else ""))
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
