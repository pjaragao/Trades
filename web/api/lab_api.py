"""Laboratório: backtest por analista, screeners (estimativas), IA sob demanda e base de conhecimento."""
import json
from pathlib import Path

from flask import Blueprint, jsonify, request

from src.core.config import ROOT
from src.lab import ai, rates, signal_backtest
from src.services import performance, signals

bp = Blueprint("lab_api", __name__, url_prefix="/api/lab")

KB_DIR = ROOT / "strategies" / "knowledge_base"
CATALOG = KB_DIR / "catalog.json"

SCREENERS = [
    {"id": "STRAT-YT-001", "type": "put_selling", "name": "Venda de PUT a −1 ATR", "asset": "Opções (ações B3)",
     "about": "Strike ~1 ATR abaixo do preço; prêmio por Black-Scholes com volatilidade fixa.", "cycle": True},
    {"id": "STRAT-YT-002", "type": "bull_spread", "name": "Trava de alta com CALL", "asset": "Opções (ações B3)",
     "about": "Compra CALL no dinheiro e vende CALL ~1 ATR acima; prêmios estimados."},
    {"id": "STRAT-YT-004", "type": "covered_call", "name": "Venda coberta", "asset": "Opções (blue chips)",
     "about": "Venda de CALL ~3% fora do dinheiro sobre ações em carteira; prêmio estimado."},
    {"id": "STRAT-YT-003", "type": "swing_trade", "name": "Swing trade (MM20/IFR)", "asset": "Ações B3",
     "about": "Tendência pela MM20/MM50 e IFR; stop/alvos percentuais do setup."},
    {"id": "STRAT-TF-001", "type": "futures_levels", "name": "Níveis de pivô em futuros", "asset": "WIN / WDO",
     "about": "Pivô clássico do dia anterior (referência intraday, difícil de operar manualmente)."},
]


def _cdi() -> float:
    return rates.cdi_annual_fraction()


@bp.get("/rates")
def get_rates():
    return jsonify(rates.get_rates(force=request.args.get("force") == "1"))


@bp.post("/backtest")
def backtest():
    d = request.get_json(silent=True) or {}
    res = signal_backtest.run(
        traders=d.get("traders") or None,
        asset_classes=d.get("asset_classes") or None,
        date_from=d.get("date_from") or None,
        date_to=d.get("date_to") or None,
        initial_capital=d.get("initial_capital"),
        value_per_trade=d.get("value_per_trade"),
        slippage_pct=float(d.get("slippage_pct", 1.0)),
        skip_intraday=bool(d.get("skip_intraday", True)),
    )
    return jsonify(res)


@bp.get("/screeners")
def list_screeners():
    return jsonify({"screeners": SCREENERS, "rates": rates.get_rates()})


@bp.get("/screener/<strategy_id>")
def run_screener(strategy_id):
    from strategies.screeners.market_screener import MarketScreenerService

    if strategy_id not in {s["id"] for s in SCREENERS}:
        raise KeyError(strategy_id)
    svc = MarketScreenerService(catalog_path=str(CATALOG), cdi_annual=_cdi())
    data = svc.get_strategy_screener_data(strategy_id, target_cycle=request.args.get("cycle", "current"))
    data["rates"] = rates.get_rates()
    data["is_estimate"] = True
    return jsonify(data)


@bp.post("/allocation")
def allocation():
    from strategies.screeners.portfolio_allocator import PortfolioAllocator

    d = request.get_json(silent=True) or {}
    res = PortfolioAllocator(cdi_annual=_cdi()).calculate_allocation(float(d.get("capital", 100000.0)))
    res["rates"] = rates.get_rates()
    res["is_estimate"] = True
    return jsonify(res)


@bp.post("/option-backtest")
def option_backtest():
    from strategies.backtesting.option_backtester import OptionBacktester

    d = request.get_json(silent=True) or {}
    symbol = str(d.get("symbol") or "VALE3").upper().strip()
    if not symbol.endswith(".SA"):
        symbol += ".SA"
    res = OptionBacktester(cdi_annual_rate=_cdi()).run_backtest(
        symbol=symbol, initial_capital=float(d.get("initial_capital", 100000.0)), start_date=d.get("start_date") or "2018-01-01")
    res["is_estimate"] = True
    return jsonify(res)


# ---------------------------------------------------------------- base de conhecimento
def _catalog():
    if not CATALOG.exists():
        return {"strategies": []}
    with open(CATALOG, "r", encoding="utf-8") as f:
        return json.load(f)


@bp.get("/knowledge")
def knowledge():
    cat = _catalog()
    profiles = performance.trader_profiles()
    items = []
    for s in cat.get("strategies", []):
        src = str(s.get("source") or "")
        item = {k: s.get(k) for k in ("id", "name", "source", "asset_class", "symbols", "summary", "status", "screener_type")}
        item["origin"] = "tradingfloors" if src.startswith("TradingFloor") else "youtube"
        item["has_doc"] = bool(s.get("doc_path"))
        if item["origin"] == "tradingfloors":
            trader = src[src.find("(") + 1:src.find(")")] if "(" in src else ""
            mine = [p for p in profiles if p["trader"].lower() == trader.lower()]
            main = max(mine, key=lambda p: (p["open"] or 0) * 1000 + (p["closed"] or 0)) if mine else None
            item["trader"] = trader
            item["live_stats"] = main  # números reais do histórico do TF
        else:
            item["claimed"] = {k: s.get(k) for k in ("win_rate_pct", "payoff_ratio", "profit_factor", "max_drawdown_pct")}
        items.append(item)
    channels = []
    for prof in (KB_DIR / "youtube").glob("*/channel_profile.json"):
        try:
            with open(prof, "r", encoding="utf-8") as f:
                p = json.load(f)
            channels.append({
                "channel_name": p.get("channel_name") or prof.parent.name,
                "channel_url": p.get("channel_url"),
                "videos": p.get("total_videos_analyzed") or p.get("strategy_candidates_count"),
                "strategies": len(p.get("cataloged_strategies") or []),
                "specialties": p.get("specialties") or [],
                "updated_at": p.get("last_updated"),
            })
        except (OSError, ValueError):
            continue
    return jsonify({"strategies": items, "channels": channels, "updated_at": cat.get("updated_at")})


@bp.get("/knowledge/<strategy_id>")
def knowledge_doc(strategy_id):
    for s in _catalog().get("strategies", []):
        if s.get("id") == strategy_id and s.get("doc_path"):
            path = (ROOT / s["doc_path"]).resolve()
            if KB_DIR.resolve() not in path.parents or not path.exists():
                raise KeyError(strategy_id)
            return jsonify({"id": strategy_id, "name": s.get("name"), "markdown": path.read_text(encoding="utf-8")})
    raise KeyError(strategy_id)


@bp.post("/youtube")
def youtube_crawl():
    from strategies.ingestion.youtube_crawler import YouTubeStrategyCrawler

    d = request.get_json(silent=True) or {}
    url = str(d.get("url") or "").strip()
    if "youtube.com" not in url and "youtu.be" not in url:
        raise ValueError("Informe a URL de um vídeo do YouTube.")
    crawler = YouTubeStrategyCrawler(base_output_dir=str(KB_DIR / "youtube"))
    return jsonify(crawler.process_video_and_channel(url, max_channel_videos=int(d.get("limit", 30))))


# ---------------------------------------------------------------- IA (TimesFM)
@bp.get("/ai/status")
def ai_status():
    return jsonify(ai.status())


@bp.post("/ai/load")
def ai_load():
    return jsonify(ai.ensure_loading())


@bp.post("/ai/predict")
def ai_predict():
    d = request.get_json(silent=True) or {}
    sig = signals.get_signal(str(d.get("signal_id") or ""))
    if not sig:
        raise KeyError("signal")
    st = ai.ensure_loading()
    if st["state"] != "ready":
        return jsonify({"pending": True, "status": st}), 202
    res = ai.predict(sig, int(d.get("horizon", 15)))
    if res and res.get("error"):
        raise ValueError(res["error"])
    return jsonify({"prediction": res, "status": ai.status()})
