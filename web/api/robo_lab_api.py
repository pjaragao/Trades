"""
API da Fábrica de Robôs & Regimes de Mercado (`robo_lab`).
Expõe endpoints para:
- Catálogo de vídeos e estratégias mineradas do canal (@norisknogainoficial ou novos canais)
- Relatório pré-computado da Arena Multi-Timeframe (5m, 15m, 60m, 1d, 1wk) e Matriz de Sentimento
- Execução sob demanda de otimização exaustiva de filtros/parâmetros para qualquer ativo B3 e timeframe
- Exportação de código MQL5 (.mq5) com Detector Causal de Regime embutido
"""

import json
from flask import Blueprint, jsonify, request

from robo_lab.backtester.optimizer import exhaust_bot_parameters_and_filters, run_arena_analysis
from robo_lab.config import DEFAULT_SYMBOLS_B3, REPORTS_DIR, SUPPORTED_TIMEFRAMES, SYMBOL_LABELS
from robo_lab.data_feed import MultiTimeframeDataFeed
from robo_lab.ingestion.youtube_channel_miner import build_channel_strategy_catalog
from robo_lab.regime.market_sentiment import enrich_indicators_and_regimes, summarize_market_regimes
from robo_lab.strategies.bots_norisknogain import NORISKNOGAIN_BOTS
from robo_lab.strategies.mt5_exporter import generate_mql5_ea_code

bp = Blueprint("robo_lab_api", __name__, url_prefix="/api/robos")


@bp.get("/overview")
def overview():
    arena_file = REPORTS_DIR / "norisknogain_full_arena.json"
    if arena_file.exists():
        data = json.loads(arena_file.read_text(encoding="utf-8"))
    else:
        data = {"channel_catalog": build_channel_strategy_catalog("norisknogainoficial"), "arena_by_symbol": {}}

    return jsonify({
        "symbols": [{"symbol": s, "label": SYMBOL_LABELS.get(s, s)} for s in DEFAULT_SYMBOLS_B3],
        "timeframes": SUPPORTED_TIMEFRAMES,
        "bots": [
            {
                "bot_id": b.bot_id,
                "name": b.name,
                "family": b.family,
                "preferred_regimes": b.preferred_regimes,
                "video_ids": b.video_ids,
                "video_titles": b.video_titles,
                "thesis": b.thesis,
                "default_params": b.default_params,
                "param_grid": b.param_grid,
            }
            for b in NORISKNOGAIN_BOTS
        ],
        "channel_catalog": data.get("channel_catalog"),
        "arena_by_symbol": data.get("arena_by_symbol", {}),
        "generated_at": data.get("generated_at"),
    })


@bp.post("/arena")
def run_custom_arena():
    d = request.get_json(silent=True) or {}
    symbol = str(d.get("symbol") or "^BVSP").strip()
    timeframe = str(d.get("timeframe") or "1d").strip()
    start_date = str(d.get("start_date") or "2020-01-01").strip()
    max_combos = int(d.get("max_combos") or 6)

    res = run_arena_analysis(symbol=symbol, timeframes=[timeframe], start_date=start_date, max_combos=max_combos) if False else run_arena_analysis(
        symbol=symbol, timeframes=[timeframe], start_date=start_date, max_param_combos=max_combos
    )
    return jsonify(res)


@bp.post("/optimize-bot")
def optimize_single_bot():
    d = request.get_json(silent=True) or {}
    bot_id = str(d.get("bot_id") or "NRNG-001").strip()
    symbol = str(d.get("symbol") or "^BVSP").strip()
    timeframe = str(d.get("timeframe") or "1d").strip()
    start_date = str(d.get("start_date") or "2020-01-01").strip()

    feed = MultiTimeframeDataFeed()
    raw_df = feed.get_bars(symbol, timeframe=timeframe, start_date=start_date if timeframe in ("1d", "1wk") else None)
    if raw_df.empty:
        raise ValueError(f"Sem dados históricos para {symbol} no timeframe {timeframe}")
    df = enrich_indicators_and_regimes(raw_df, timeframe=timeframe)
    opt = exhaust_bot_parameters_and_filters(df, bot_id=bot_id, timeframe=timeframe, max_param_combos=12, thorough_filters=True)
    opt["regime_summary"] = summarize_market_regimes(df)
    return jsonify(opt)


@bp.get("/export-mql5/<bot_id>")
def export_mql5(bot_id: str):
    symbol = request.args.get("symbol", "WIN$N")
    tf = request.args.get("timeframe", "15m")
    code = generate_mql5_ea_code(bot_id, symbol=symbol, timeframe=tf)
    return jsonify({"bot_id": bot_id, "symbol": symbol, "timeframe": tf, "mql5_code": code})
