import os
import sys
import json
import yaml
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.bot_service import BotService
from src.backtest_engine import BacktestEngine
from src.client_tf import TradingFloorsClient
from src.order_tracker import OrderTracker
from src.risk_manager import RiskManager
from src.mt5_bridge import MT5Bridge
from src.timesfm_predictor import TimesFMPredictor
from strategies.screeners.market_screener import MarketScreenerService
from strategies.ingestion.youtube_crawler import YouTubeStrategyCrawler
from strategies.backtesting.backtest_runner import BacktestRunner
from strategies.ingestion.tf_extractor import TradingFloorExtractor
from strategies.methodology.strategy_trades import StrategyTradeMatcher

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "web", "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "web", "static")
)

# Inicializa serviços
bot_service = BotService.get_instance()

def get_tf_client():
    load_dotenv("config/.env")
    with open("config/settings.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    url = config["trading_floors"]["supabase_url"]
    key = config["trading_floors"]["supabase_anon_key"]
    email = os.getenv("TF_EMAIL", "").strip()
    pwd = os.getenv("TF_PASSWORD", "").strip()

    client = TradingFloorsClient(url, key, email, pwd)
    client.login()
    return client, config

# ==========================================
# ROTAS FRONTEND
# ==========================================

@app.route("/")
def index():
    return render_template("index.html")

# ==========================================
# APIS DO ROBÔ E MONITORAMENTO
# ==========================================

@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify(bot_service.get_status())

@app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    data = request.get_json() or {}
    dry_run = data.get("dry_run")
    result = bot_service.start_bot(dry_run=dry_run)
    return jsonify(result)

@app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    result = bot_service.stop_bot()
    return jsonify(result)

@app.route("/api/bot/set-mode", methods=["POST"])
def api_bot_set_mode():
    data = request.get_json() or {}
    dry_run = bool(data.get("dry_run", True))
    config = bot_service.load_config()
    config["execution"]["dry_run"] = dry_run
    bot_service.save_config(config)

    # Se estiver rodando, precisa reiniciar para aplicar
    if bot_service.is_running:
        bot_service.stop_bot()
        bot_service.start_bot(dry_run=dry_run)

    return jsonify({"success": True, "dry_run": dry_run})

@app.route("/api/trades/open", methods=["GET"])
def api_trades_open():
    try:
        prod_filter = request.args.get("product")
        asset_filter = request.args.get("asset_type")

        # 1. Tenta buscar da API ao vivo do TradingFloors
        open_trades = []
        try:
            client, config = get_tf_client()
            allowed = config["trading_floors"].get("allowed_products")
            open_trades = client.fetch_open_trades(allowed)
        except Exception:
            pass

        # 2. Se a API retornar vazio ou falhar, busca as posições OPEN do cache local SQLite
        if not open_trades:
            cache_path = "database/backtest_cache.db"
            if os.path.exists(cache_path):
                import sqlite3
                with sqlite3.connect(cache_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    rows = cursor.execute("SELECT * FROM historical_trades WHERE status = 'OPEN' ORDER BY timestamp_entrada DESC").fetchall()
                    open_trades = [dict(r) for r in rows]

        # 3. Aplica filtros opcionais
        if prod_filter and prod_filter != "all":
            open_trades = [
                t for t in open_trades 
                if prod_filter.lower() in str(t.get("produto", "")).lower() or 
                prod_filter.lower() in str(t.get("produto_display", "")).lower() or
                any(prod_filter.lower() in str(p).lower() for p in t.get("produtos_all", []))
            ]
        if asset_filter and asset_filter != "all":
            open_trades = [t for t in open_trades if str(t.get("tipo_ativo")).lower() == asset_filter.lower()]

        # Deduplica qualquer registro repetido pelo mesmo ticker, trader e lado no mesmo dia
        dedup_map = {}
        for t in open_trades:
            t_ticker = str(t.get("ticker", "")).strip().upper()
            t_trader = str(t.get("trader_nome", "")).strip().lower()
            t_lado = str(t.get("lado", "BUY")).strip().upper()
            t_date = str(t.get("timestamp_entrada", ""))[:10]
            dkey = (t_ticker, t_trader, t_lado, t_date)
            if dkey not in dedup_map:
                dedup_map[dkey] = t
            else:
                existing = dedup_map[dkey]
                t_ts = str(t.get("timestamp_entrada", ""))
                exist_ts = str(existing.get("timestamp_entrada", ""))
                if t.get("preco_atual") is not None:
                    if existing.get("preco_atual") is None or t_ts > exist_ts:
                        existing["preco_atual"] = t.get("preco_atual")
                if t_ts > exist_ts:
                    existing["timestamp_entrada"] = t.get("timestamp_entrada")
                for p in t.get("produtos_all", [t.get("produto")]):
                    if p and p not in existing.get("produtos_all", []):
                        existing.setdefault("produtos_all", []).append(p)
                if "Desafio Eleições" in existing.get("produtos_all", []) and "Opções" in existing.get("produtos_all", []):
                    existing["produto_display"] = "Desafio Eleições / Opções"
        open_trades = list(dedup_map.values())

        # Enriquece os trades com o papel principal (ativo subjacente)
        try:
            predictor = TimesFMPredictor.get_instance()
            for t in open_trades:
                ticker = t.get("ticker", "")
                und_sym, opt_t, est_strike = predictor.map_option_to_underlying(ticker)
                und_ticker = und_sym.replace(".SA", "").replace("^", "").replace("=X", "USD/BRL")
                t["underlying_symbol"] = und_sym
                t["underlying_ticker"] = und_ticker
                t["papel_principal"] = und_ticker
                if not t.get("opcao_tipo") and opt_t in ["CALL", "PUT"]:
                    t["opcao_tipo"] = opt_t
                if not t.get("strike") and est_strike:
                    t["strike"] = est_strike
        except Exception as map_err:
            print(f"Aviso ao enriquecer papel principal: {map_err}")

        return jsonify(open_trades)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/trades/database", methods=["GET"])
def api_trades_database():
    """Consulta paginada e filtrável de todos os trades do banco de dados local."""
    try:
        import sqlite3
        cache_path = "database/backtest_cache.db"
        if not os.path.exists(cache_path):
            return jsonify({"total_count": 0, "trades": [], "filter_options": {}})

        status = request.args.get("status", "all")
        product = request.args.get("product", "all")
        tipo_ativo = request.args.get("tipo_ativo", "all")
        trader = request.args.get("trader", "all")
        ticker = request.args.get("ticker", "").strip().upper()
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = int(request.args.get("offset", 0))

        conditions = []
        params = []

        if status != "all":
            conditions.append("status = ?")
            params.append(status)
        if product != "all":
            conditions.append("produto LIKE ?")
            params.append(f"%{product}%")
        if tipo_ativo != "all":
            conditions.append("tipo_ativo = ?")
            params.append(tipo_ativo)
        if trader != "all":
            conditions.append("trader_nome = ?")
            params.append(trader)
        if ticker:
            conditions.append("ticker LIKE ?")
            params.append(f"%{ticker}%")

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        with sqlite3.connect(cache_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Total de registros com o filtro
            count_query = f"SELECT COUNT(*) FROM historical_trades{where_clause}"
            total_count = cursor.execute(count_query, params).fetchone()[0]

            # Registros paginados
            select_query = f"SELECT * FROM historical_trades{where_clause} ORDER BY timestamp_entrada DESC LIMIT ? OFFSET ?"
            rows = cursor.execute(select_query, params + [limit, offset]).fetchall()
            trades = [dict(r) for r in rows]

            # Opções únicas para filtros
            distinct_products = [r[0] for r in cursor.execute("SELECT DISTINCT produto FROM historical_trades WHERE produto IS NOT NULL").fetchall()]
            distinct_assets = [r[0] for r in cursor.execute("SELECT DISTINCT tipo_ativo FROM historical_trades WHERE tipo_ativo IS NOT NULL").fetchall()]
            distinct_traders = [r[0] for r in cursor.execute("SELECT DISTINCT trader_nome FROM historical_trades WHERE trader_nome IS NOT NULL ORDER BY trader_nome ASC").fetchall()]

        return jsonify({
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "trades": trades,
            "filter_options": {
                "products": distinct_products,
                "asset_types": distinct_assets,
                "traders": distinct_traders
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/trades/tracked", methods=["GET"])
def api_trades_tracked():
    try:
        tracker = OrderTracker()
        tracked = tracker.get_all_tracked(limit=50)
        return jsonify(tracked)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/trades/execute-manual", methods=["POST"])
def api_trades_execute_manual():
    try:
        data = request.get_json() or {}
        trade_id = data.get("trade_id")
        if not trade_id:
            return jsonify({"success": False, "error": "trade_id é obrigatório"}), 400

        client, config = get_tf_client()
        trade = client.fetch_trade_by_id(trade_id)
        if not trade:
            return jsonify({"success": False, "error": "Trade não encontrado na plataforma."}), 404

        dry_run = config.get("execution", {}).get("dry_run", True)
        risk_manager = RiskManager(config)
        tracker = OrderTracker()
        mt5_bridge = MT5Bridge(config, dry_run=dry_run)
        mt5_bridge.connect()

        qty = risk_manager.calculate_quantity(trade)
        res = mt5_bridge.execute_entry(
            symbol=trade["ticker"],
            lado=trade.get("lado", "BUY"),
            quantidade=qty,
            preco_sugerido=float(trade.get("preco_entrada") or 0),
            comment="Manual TF Entry"
        )

        if res.get("success"):
            ticket = res.get("ticket", 0)
            tracker.record_entry(
                trade_id=trade_id,
                source_table=trade.get("_source_table", "trades"),
                produto=trade.get("produto", "N/A"),
                ticker=trade["ticker"],
                trader_nome=trade.get("trader_nome", "N/A"),
                lado=trade.get("lado", "BUY"),
                preco_entrada_sugerido=float(trade.get("preco_entrada") or 0),
                preco_entrada_executado=res.get("price", float(trade.get("preco_entrada") or 0)),
                quantidade_sugerida=float(trade.get("quantidade") or 100),
                quantidade_executada=qty,
                mt5_ticket=ticket,
                timestamp_entrada=trade.get("timestamp_entrada", ""),
                status="OPEN"
            )
            bot_service.log(f"Ordem manual executada: {trade['ticker']} ({qty} un)")
            return jsonify({"success": True, "result": res})
        else:
            return jsonify({"success": False, "error": res.get("error")})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/trades/close-manual", methods=["POST"])
def api_trades_close_manual():
    try:
        data = request.get_json() or {}
        trade_id = data.get("trade_id")
        if not trade_id:
            return jsonify({"success": False, "error": "trade_id é obrigatório"}), 400

        tracker = OrderTracker()
        tracked = tracker.get_trade_by_id(trade_id)
        if not tracked:
            return jsonify({"success": False, "error": "Posição não encontrada no banco local."}), 404

        with open("config/settings.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        dry_run = config.get("execution", {}).get("dry_run", True)
        mt5_bridge = MT5Bridge(config, dry_run=dry_run)
        mt5_bridge.connect()

        res = mt5_bridge.execute_exit(
            symbol=tracked["ticker"],
            lado_original=tracked.get("lado", "BUY"),
            quantidade=float(tracked.get("quantidade_executada") or 100),
            ticket=tracked.get("mt5_ticket")
        )

        if res.get("success"):
            tracker.record_exit(trade_id=trade_id, preco_saida=res.get("price", 0.0))
            bot_service.log(f"Posição manual encerrada: {tracked['ticker']}")
            return jsonify({"success": True, "result": res})
        else:
            return jsonify({"success": False, "error": res.get("error")})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ==========================================
# APIS DE BACKTEST HISTÓRICO
# ==========================================

@app.route("/api/backtest/filters", methods=["GET"])
def api_backtest_filters():
    try:
        config = bot_service.load_config()
        url = config["trading_floors"]["supabase_url"]
        key = config["trading_floors"]["supabase_anon_key"]
        engine = BacktestEngine(url, key)
        return jsonify(engine.get_filter_options())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/backtest/run", methods=["POST"])
def api_backtest_run():
    try:
        data = request.get_json() or {}
        config = bot_service.load_config()
        url = config["trading_floors"]["supabase_url"]
        key = config["trading_floors"]["supabase_anon_key"]
        engine = BacktestEngine(url, key)

        # Se o cache estiver vazio, sincroniza primeiro
        if engine.get_cached_count() == 0:
            client, _ = get_tf_client()
            engine.sync_historical_data(client.access_token)

        results = engine.run_backtest(
            initial_equity=float(data.get("initial_equity", 10000.0)),
            sizing_mode=str(data.get("sizing_mode", "fixed_capital")),
            fixed_capital=float(data.get("fixed_capital", 1000.0)),
            fixed_quantity=int(data.get("fixed_quantity", 100)),
            product=str(data.get("product", "all")),
            trader=str(data.get("trader", "all")),
            date_from=data.get("date_from"),
            date_to=data.get("date_to")
        )
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/backtest/sync-cache", methods=["POST"])
def api_backtest_sync_cache():
    try:
        client, config = get_tf_client()
        url = config["trading_floors"]["supabase_url"]
        key = config["trading_floors"]["supabase_anon_key"]
        engine = BacktestEngine(url, key, token=client.access_token)
        count = engine.sync_historical_data()
        return jsonify({"success": True, "synced_count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ==========================================
# APIS DE PREVISÃO IA (GOOGLE TIMESFM)
# ==========================================

@app.route("/api/ai/predict", methods=["POST"])
def api_ai_predict():
    try:
        data = request.get_json() or {}
        predictor = TimesFMPredictor.get_instance()
        horizon = int(data.get("horizon", 15))
        result = predictor.predict_trade_success(data, horizon_days=horizon)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ai/active-forecasts", methods=["GET"])
def api_ai_active_forecasts():
    try:
        client, config = get_tf_client()
        allowed = config["trading_floors"].get("allowed_products")
        open_trades = client.fetch_open_trades(allowed)
        predictor = TimesFMPredictor.get_instance()

        forecasts = []
        for t in open_trades[:12]: # Processa os primeiros 12 sinais
            pred = predictor.predict_trade_success(t)
            forecasts.append({
                "trade_id": t.get("id"),
                "ticker": t.get("ticker"),
                "produto": t.get("produto"),
                "trader_nome": t.get("trader_nome"),
                "lado": t.get("lado"),
                "preco_entrada": t.get("preco_entrada"),
                "prediction": pred
            })

        return jsonify(forecasts)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==========================================
# APIS DE ESTRATÉGIAS & BASE DE CONHECIMENTO
# ==========================================

@app.route("/api/strategies/catalog", methods=["GET"])
def api_strategies_catalog():
    try:
        service = MarketScreenerService()
        catalog = service.get_catalog()
        
        # Carrega também perfil de traders do TF se existir
        tf_profile_path = "strategies/knowledge_base/trading_floor/tf_traders_profile.json"
        tf_profile = {}
        if os.path.exists(tf_profile_path):
            with open(tf_profile_path, "r", encoding="utf-8") as f:
                tf_profile = json.load(f)
                
        # Carrega perfil do Jimmy Carvalho
        yt_profile_path = "strategies/knowledge_base/youtube/jimmy_carvalho/channel_profile.json"
        yt_profile = {}
        if os.path.exists(yt_profile_path):
            with open(yt_profile_path, "r", encoding="utf-8") as f:
                yt_profile = json.load(f)

        return jsonify({
            "catalog": catalog,
            "tf_profile": tf_profile,
            "youtube_channels": [yt_profile] if yt_profile else []
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/strategies/trades", methods=["GET"])
def api_strategies_trades():
    """Retorna operações ativas e sinais de screener mapeados diretamente para cada estratégia."""
    try:
        # 1. Busca trades abertos da API do TF
        open_trades = []
        try:
            client, config = get_tf_client()
            allowed = config["trading_floors"].get("allowed_products")
            open_trades = client.fetch_open_trades(allowed)
        except Exception:
            pass

        # 2. Se falhar ou estiver vazio, busca do cache local SQLite
        if not open_trades:
            cache_path = "database/backtest_cache.db"
            if os.path.exists(cache_path):
                import sqlite3
                with sqlite3.connect(cache_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    rows = cursor.execute("SELECT * FROM historical_trades WHERE status = 'OPEN' ORDER BY timestamp_entrada DESC").fetchall()
                    open_trades = [dict(r) for r in rows]

        matcher = StrategyTradeMatcher()
        result = matcher.map_trades_to_strategies(open_trades)

        # Filtro opcional por strategy_id
        strat_filter = request.args.get("strategy_id")
        if strat_filter and strat_filter != "all":
            result["trades"] = [t for t in result["trades"] if t["strategy_id"] == strat_filter]
            result["total_trades"] = len(result["trades"])

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/strategies/screener", methods=["GET"])
def api_strategies_screener():
    try:
        cycle = request.args.get("cycle", "current")
        service = MarketScreenerService()
        results = service.run_all_screeners(target_cycle=cycle)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/strategies/screener/<strategy_id>", methods=["GET"])
def api_strategies_screener_detail(strategy_id):
    try:
        cycle = request.args.get("cycle", "current")
        service = MarketScreenerService()
        result = service.get_strategy_screener_data(strategy_id, target_cycle=cycle)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/strategies/simulate-allocation", methods=["POST"])
def api_strategies_simulate_allocation():
    try:
        data = request.get_json() or {}
        capital = float(data.get("capital", 100000.0))
        from strategies.screeners.portfolio_allocator import PortfolioAllocator
        allocator = PortfolioAllocator()
        result = allocator.calculate_allocation(capital)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/strategies/execute", methods=["POST"])
def api_strategies_execute():
    try:
        data = request.get_json() or {}
        ticker = data.get("ticker", "").strip().upper()
        if not ticker:
            return jsonify({"success": False, "error": "Ticker é obrigatório"}), 400

        trade_id = str(uuid.uuid4())
        strat_id = data.get("strategy_id", "STRAT-MANUAL")
        strat_name = data.get("strategy_name", "Estratégia Quantitativa")
        lado = (data.get("lado") or "BUY").upper()
        preco = float(data.get("preco_entrada") or data.get("current_spot") or 1.0)
        qtd = float(data.get("quantidade") or 100.0)
        obs = data.get("observacoes") or f"Setup originado da estratégia {strat_id} ({strat_name})"

        tracker = OrderTracker()
        tracker.record_entry(
            trade_id=trade_id,
            source_table="strategies_hub",
            produto=f"Estratégia {strat_id}",
            ticker=ticker,
            trader_nome=strat_name[:30],
            lado=lado,
            preco_entrada_sugerido=preco,
            preco_entrada_executado=preco,
            quantidade_sugerida=qtd,
            quantidade_executada=qtd,
            mt5_ticket=None,
            timestamp_entrada=datetime.now().isoformat(),
            status="OPEN",
            observacoes=obs
        )

        bot_service.log(f"[ESTRATÉGIAS] Operação registrada para acompanhamento: {ticker} ({lado}) - {strat_id}")

        return jsonify({
            "success": True,
            "message": f"Operação {ticker} ({lado}) vinculada à estratégia {strat_id} registrada com sucesso!",
            "trade_id": trade_id
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/strategies/youtube/crawl", methods=["POST"])
def api_strategies_youtube_crawl():
    try:
        data = request.get_json() or {}
        video_url = data.get("url")
        if not video_url:
            return jsonify({"success": False, "error": "URL do vídeo é obrigatória"}), 400

        limit = int(data.get("limit", 30))
        crawler = YouTubeStrategyCrawler()
        res = crawler.process_video_and_channel(video_url, max_channel_videos=limit)
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/strategies/backtest", methods=["POST"])
def api_strategies_backtest():
    try:
        data = request.get_json() or {}
        strategy_id = data.get("strategy_id", "STRAT-YT-001")
        symbol = data.get("symbol", "VALE3.SA")
        start_date = data.get("start_date", "2016-01-01")
        initial_capital = float(data.get("initial_capital", 100000.0))

        runner = BacktestRunner()
        res = runner.run(strategy_id=strategy_id, symbol=symbol, start_date=start_date, initial_capital=initial_capital)
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/strategies/tf/refresh", methods=["POST"])
def api_strategies_tf_refresh():
    try:
        extractor = TradingFloorExtractor()
        res = extractor.refresh_patterns()
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==========================================
# APIS DE CONFIGURAÇÃO E LOGS
# ==========================================

@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(bot_service.load_config())

@app.route("/api/config", methods=["POST"])
def api_save_config():
    try:
        new_data = request.get_json() or {}
        current_cfg = bot_service.load_config()

        # Atualiza apenas seções enviadas
        if "risk" in new_data:
            current_cfg.setdefault("risk", {}).update(new_data["risk"])
        if "mt5" in new_data:
            current_cfg.setdefault("mt5", {}).update(new_data["mt5"])
        if "execution" in new_data:
            current_cfg.setdefault("execution", {}).update(new_data["execution"])

        success = bot_service.save_config(current_cfg)
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/logs", methods=["GET"])
def api_logs():
    limit = int(request.args.get("limit", 100))
    return jsonify(bot_service.get_logs(limit=limit))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"\n" + "="*60)
    print(f"  TRADINGFLOORS -> METATRADER 5 WEB SUITE")
    print(f"  Acesse no navegador: http://127.0.0.1:{port}")
    print(f"="*60 + "\n")
    app.run(host="127.0.0.1", port=port, debug=False)
