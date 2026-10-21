"""
Testes automatizados para o módulo independente `robo_lab` (Mineração de Estratégias do YouTube,
Classificação Causal de Sentimento de Mercado sem Look-Ahead e Arena Exaustiva de Robôs B3).
"""
import numpy as np
import pandas as pd

from robo_lab.backtester.engine import run_bot_backtest
from robo_lab.backtester.optimizer import exhaust_bot_parameters_and_filters
from robo_lab.ingestion.youtube_channel_miner import build_channel_strategy_catalog
from robo_lab.regime.market_sentiment import enrich_indicators_and_regimes
from robo_lab.strategies.base_bot import FilterConfig
from robo_lab.strategies.bots_norisknogain import BOT_SIGNAL_FUNCTIONS, NORISKNOGAIN_BOTS
from robo_lab.strategies.mt5_exporter import generate_mql5_ea_code


def _make_sample_ohlcv(n: int = 350, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-02 10:00:00", periods=n, freq="15min")
    trend = np.concatenate([
        np.linspace(0, 12, n // 3),
        np.sin(np.linspace(0, 8 * np.pi, n // 3)) * 0.8 + 12,
        np.linspace(12, 2, n - 2 * (n // 3)),
    ])
    noise = rng.normal(0, 0.35, size=n)
    close = 100.0 + trend + noise
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    spread = np.abs(rng.normal(0.45, 0.15, size=n))
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.integers(1000, 10000, size=n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def test_causal_regime_has_zero_lookahead():
    """Garante que o detector causal (`causal_regime`) no instante t não muda se alterarmos barras futuras (> t)."""
    df_full = _make_sample_ohlcv(300)
    ann_full = enrich_indicators_and_regimes(df_full, timeframe="15m")

    # Altera drasticamente o futuro após a barra 220
    df_modified_future = df_full.copy()
    df_modified_future.iloc[221:, df_modified_future.columns.get_loc("close")] *= 3.0
    df_modified_future.iloc[221:, df_modified_future.columns.get_loc("high")] *= 3.0
    ann_mod = enrich_indicators_and_regimes(df_modified_future, timeframe="15m")

    # Até a barra 220, o causal_regime deve ser idêntico (zero look-ahead)
    pd.testing.assert_series_equal(
        ann_full["causal_regime"].iloc[:221],
        ann_mod["causal_regime"].iloc[:221],
    )


def test_all_10_norisknogain_bots_generate_signals_and_backtest():
    """Verifica que todos os 10 robôs do canal No Risk No Gain geram sinais válidos e rodam no motor."""
    df = enrich_indicators_and_regimes(_make_sample_ohlcv(320), timeframe="15m")
    assert len(NORISKNOGAIN_BOTS) == 10

    for bot in NORISKNOGAIN_BOTS:
        sig_fn = BOT_SIGNAL_FUNCTIONS[bot.bot_id]
        sig_tuple = sig_fn(df, bot.default_params)
        assert isinstance(sig_tuple, tuple) and len(sig_tuple) == 4
        assert len(sig_tuple[0]) == len(df)

        res = run_bot_backtest(
            df,
            bot_id=bot.bot_id,
            filters=FilterConfig(trend_filter="ema20_50_align"),
            timeframe="15m",
            include_trades_list=False,
        )
        assert res["bot_id"] == bot.bot_id
        assert isinstance(res["summary"]["total_return_pct"], float)
        assert isinstance(res["by_causal_regime"], dict)


def test_exhaustive_filter_and_parameter_optimization():
    """Executa a exaustão de filtros e parâmetros de um robô e verifica o ganho de robustez."""
    df = enrich_indicators_and_regimes(_make_sample_ohlcv(260), timeframe="15m")
    opt = exhaust_bot_parameters_and_filters(
        df,
        bot_id="NRNG-001",
        timeframe="15m",
        max_param_combos=2,
        thorough_filters=False,
    )
    assert opt["bot_id"] == "NRNG-001"
    assert opt["combinations_tested"] > 5
    assert "best_overall" in opt
    assert "best_by_causal_regime" in opt
    assert "top_5_variations" in opt


def test_youtube_channel_manifest_and_mt5_export():
    """Verifica que o manifesto do canal @norisknogainoficial está carregado e que o exportador MQL5 funciona."""
    summary = build_channel_strategy_catalog("norisknogainoficial")
    assert summary["total_videos_scanned"] >= 200
    assert summary["strategy_videos_identified"] >= 150

    code = generate_mql5_ea_code("NRNG-009", symbol="WIN$N", timeframe="15m")
    assert "DetectCausalMarketRegime" in code
    assert "NRNG-009" in code


def test_web_robo_lab_api_endpoints():
    """Testa as rotas Flask `/api/robos/*` integradas ao painel web."""
    from web.app import create_app

    app = create_app(start_monitor=False)
    client = app.test_client()

    r_ov = client.get("/api/robos/overview")
    assert r_ov.status_code == 200
    data = r_ov.get_json()
    assert len(data["bots"]) == 10
    assert data["channel_catalog"]["strategy_videos_identified"] >= 150
    assert "^BVSP" in data["arena_by_symbol"]

    r_mq5 = client.get("/api/robos/export-mql5/NRNG-009?symbol=WIN$N&timeframe=15m")
    assert r_mq5.status_code == 200
    assert "DetectCausalMarketRegime" in r_mq5.get_json()["mql5_code"]
    assert "WIN$N" in data["arena_by_symbol"]
    assert "WDO$N" in data["arena_by_symbol"]
    assert set(data["arena_by_symbol"]["WIN$N"]["by_timeframe"].keys()) >= {"1m", "2m", "3m", "5m", "15m"}
    assert set(data["arena_by_symbol"]["WDO$N"]["by_timeframe"].keys()) >= {"1m", "2m", "3m", "5m", "15m"}
