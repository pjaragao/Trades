"""
Aplicação web do Copiloto de Trades (Flask).

    python web_app.py            -> http://127.0.0.1:5000
"""
import logging
import os
from pathlib import Path

from flask import Flask, jsonify, render_template

from src import __version__
from src.core import db

WEB_DIR = Path(__file__).resolve().parent


def create_app(start_monitor: bool = True, db_path=None) -> Flask:
    app = Flask(__name__, template_folder=str(WEB_DIR / "templates"), static_folder=str(WEB_DIR / "static"))
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # sempre revalida JS/CSS (módulos ES sem build)
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    if db_path:
        db.configure(db_path)
    else:
        db.init_db()

    from web.api.alerts_api import bp as alerts_bp
    from web.api.core_api import bp as core_bp
    from web.api.lab_api import bp as lab_bp
    from web.api.portfolio_api import bp as portfolio_bp
    from web.api.results_api import bp as results_bp
    from web.api.settings_api import bp as settings_bp
    from web.api.signals_api import bp as signals_bp

    for bp in (core_bp, signals_bp, portfolio_bp, alerts_bp, settings_bp, results_bp, lab_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ValueError)
    def _bad_request(exc):
        return jsonify({"error": str(exc)}), 400

    @app.errorhandler(KeyError)
    def _not_found(exc):
        return jsonify({"error": "Registro não encontrado"}), 404

    @app.route("/")
    def index():
        return render_template("app.html", version=__version__)

    if start_monitor:
        from src.services.signal_monitor import get_monitor

        get_monitor().start()

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Copiloto de Trades (servidor web local)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 5000)))
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"), help="0.0.0.0 para acessar pelo celular na rede local")
    parser.add_argument("--db", default=os.getenv("COPILOTO_DB"), help="arquivo do banco (padrão: database/app.db)")
    parser.add_argument("--no-monitor", action="store_true", help="não inicia o monitor de sinais")
    args = parser.parse_args()

    os.chdir(WEB_DIR.parent)  # módulos do laboratório usam caminhos relativos à raiz do projeto
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    port, host = args.port, args.host
    app = create_app(start_monitor=not args.no_monitor, db_path=args.db)
    print("\n" + "=" * 60)
    print("  COPILOTO DE TRADES")
    print(f"  Acesse no navegador: http://127.0.0.1:{port}")
    if host not in ("127.0.0.1", "localhost"):
        print(f"  Na rede local (celular): http://<ip-deste-pc>:{port}")
    print("=" * 60 + "\n")
    app.run(host=host, port=port, debug=False, threaded=True)
