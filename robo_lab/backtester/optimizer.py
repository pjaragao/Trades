"""
Exaustor de Parâmetros e Filtros + Simulador do Meta-Robô Adaptativo Causal (Zero Look-Ahead).

Executa:
1. Grid Search combinatório variando parâmetros internos de cada robô + banco de filtros universais
   (Tendência, Volume, Volatilidade, Horário/Sessão, Direção).
2. Classificação de campeões por Sentimento de Mercado:
   - Ex-Post (Mês de ALTA, LATERAL, BAIXA)
   - Causal / Point-in-Time (Estado ALTA, LATERAL, BAIXA sem olhar o futuro)
   - Perfil do Dia da Bolsa (Volume Alto/Normal/Baixo, Direcional Alta/Baixa/Oscilante)
   - Timeframes ('5m', '15m', '60m', '1d', '1wk')
3. Simulação do Meta-Seletor Causal:
   - Responde na prática a pergunta: "Em mês de alta qual estratégia funciona, e COMO usar ela sem saber que o mês é de alta?"
"""

import itertools
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from robo_lab.backtester.engine import _compute_slice_metrics, run_bot_backtest
from robo_lab.config import BACKTEST_DEFAULTS
from robo_lab.data_feed import MultiTimeframeDataFeed
from robo_lab.regime.market_sentiment import enrich_indicators_and_regimes, summarize_market_regimes
from robo_lab.strategies.base_bot import FilterConfig
from robo_lab.strategies.bots_norisknogain import NORISKNOGAIN_BOTS, get_bot_by_id


def build_filter_bank(timeframe: str = "1d", thorough: bool = True) -> List[FilterConfig]:
    """
    Gera banco sistemático de combinações de filtros de mercado (tendência, volume, volatilidade, sessão, direção)
    para exaurir hipóteses operacionais sobre cada robô.
    """
    bank = [
        FilterConfig("none", "none", "none", "all_day", "both"),
        FilterConfig("none", "none", "none", "all_day", "long_only"),
        FilterConfig("none", "none", "none", "all_day", "short_only"),
        FilterConfig("ema200_align", "none", "none", "all_day", "both"),
        FilterConfig("ema200_align", "vol_above_avg", "none", "all_day", "both"),
        FilterConfig("ema200_align", "none", "none", "all_day", "long_only"),
        FilterConfig("ema20_50_align", "none", "none", "all_day", "both"),
        FilterConfig("ema20_50_align", "vol_above_avg", "atr_expanding", "all_day", "both"),
        FilterConfig("ema20_50_align", "none", "none", "all_day", "long_only"),
        FilterConfig("adx_trend_gt20", "vol_above_avg", "none", "all_day", "both"),
        FilterConfig("adx_trend_gt20", "vol_spike_1_3x", "atr_expanding", "all_day", "both"),
        FilterConfig("adx_lateral_lt22", "none", "none", "all_day", "both"),
        FilterConfig("adx_lateral_lt22", "vol_calm_lt1_2x", "atr_contracting", "all_day", "both"),
        FilterConfig("er_low_noise", "none", "atr_contracting", "all_day", "both"),
        FilterConfig("er_low_noise", "none", "none", "all_day", "long_only"),
        FilterConfig("er_high_trend", "vol_above_avg", "none", "all_day", "both"),
    ]
    if timeframe in ("1m", "2m", "3m", "5m", "15m", "60m") and thorough:
        bank.extend([
            FilterConfig("none", "vol_above_avg", "none", "golden_hour_morning", "both"),
            FilterConfig("ema20_50_align", "vol_above_avg", "none", "golden_hour_morning", "both"),
            FilterConfig("adx_lateral_lt22", "none", "none", "afternoon_calm", "both"),
            FilterConfig("er_low_noise", "vol_calm_lt1_2x", "none", "afternoon_calm", "both"),
        ])
    return bank


def expand_param_grid(param_grid: Dict[str, List[Any]], max_combos: int = 12) -> List[Dict[str, Any]]:
    if not param_grid:
        return [{}]
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    combos = [dict(zip(keys, prod)) for prod in itertools.product(*values)]
    if len(combos) > max_combos:
        step = max(1, len(combos) // max_combos)
        combos = combos[::step][:max_combos]
    return combos


def exhaust_bot_parameters_and_filters(
    df: pd.DataFrame,
    bot_id: str,
    timeframe: str = "1d",
    symbol: str = "^BVSP",
    max_param_combos: int = 8,
    thorough_filters: bool = True,
) -> Dict[str, Any]:
    """
    Exaure variações de parâmetros + filtros para um robô específico em um DataFrame enriquecido.
    Retorna:
    - Resultado baseline (sem otimização)
    - Melhor configuração geral (parâmetros + filtros)
    - Melhor configuração específica para ALTA, LATERAL e BAIXA (Ex-Post e Causal)
    - Melhor configuração por Perfil do Dia (Volume Alto/Baixo, Direcional/Lateral)
    """
    bot_spec = get_bot_by_id(bot_id)
    param_combos = expand_param_grid(bot_spec.param_grid, max_combos=max_param_combos)
    filter_bank = build_filter_bank(timeframe=timeframe, thorough=thorough_filters)

    baseline_run = run_bot_backtest(
        df, bot_id, params=bot_spec.default_params, filters=FilterConfig(), timeframe=timeframe, symbol=symbol, include_trades_list=True
    )

    all_runs: List[Dict[str, Any]] = []
    for p_combo in param_combos:
        for f_cfg in filter_bank:
            res = run_bot_backtest(
                df, bot_id, params=p_combo, filters=f_cfg, timeframe=timeframe, symbol=symbol, include_trades_list=False
            )
            if res["summary"]["trades"] >= 3:
                all_runs.append(res)

    if not all_runs:
        all_runs = [baseline_run]

    # Ordena pelo score de robustez global
    all_runs.sort(
        key=lambda r: (r["summary"]["robustness_score"], r["summary"]["total_return_pct"]),
        reverse=True,
    )

    best_cfg = all_runs[0]
    best_full = run_bot_backtest(
        df,
        bot_id,
        params=best_cfg["params"],
        filters=FilterConfig(**best_cfg["filters"]),
        timeframe=timeframe,
        symbol=symbol,
        include_trades_list=True,
    )

    # Descobre qual combinação de parâmetros+filtros deste robô é melhor em cada Sentimento de Mercado
    best_by_expost_regime = {}
    for reg in ("ALTA", "LATERAL", "BAIXA"):
        valid = [r for r in all_runs if r["by_expost_regime"].get(reg, {}).get("trades", 0) >= 2]
        if valid:
            champ = max(
                valid,
                key=lambda r: (
                    r["by_expost_regime"][reg]["robustness_score"],
                    r["by_expost_regime"][reg]["total_return_pct"],
                ),
            )
            best_by_expost_regime[reg] = {
                "params": champ["params"],
                "filters": champ["filters"],
                "filter_label": champ["filter_label"],
                "metrics": champ["by_expost_regime"][reg],
            }
        else:
            best_by_expost_regime[reg] = {
                "params": best_full["params"],
                "filters": best_full["filters"],
                "filter_label": best_full["filter_label"],
                "metrics": best_full["by_expost_regime"].get(reg, {}),
            }

    best_by_causal_regime = {}
    for reg in ("ALTA", "LATERAL", "BAIXA"):
        valid = [r for r in all_runs if r["by_causal_regime"].get(reg, {}).get("trades", 0) >= 2]
        if valid:
            champ = max(
                valid,
                key=lambda r: (
                    r["by_causal_regime"][reg]["robustness_score"],
                    r["by_causal_regime"][reg]["total_return_pct"],
                ),
            )
            best_by_causal_regime[reg] = {
                "params": champ["params"],
                "filters": champ["filters"],
                "filter_label": champ["filter_label"],
                "metrics": champ["by_causal_regime"][reg],
            }
        else:
            best_by_causal_regime[reg] = {
                "params": best_full["params"],
                "filters": best_full["filters"],
                "filter_label": best_full["filter_label"],
                "metrics": best_full["by_causal_regime"].get(reg, {}),
            }

    return {
        "bot_id": bot_id,
        "bot_name": bot_spec.name,
        "family": bot_spec.family,
        "preferred_regimes": bot_spec.preferred_regimes,
        "video_ids": bot_spec.video_ids,
        "video_titles": bot_spec.video_titles,
        "thesis": bot_spec.thesis,
        "timeframe": timeframe,
        "combinations_tested": len(param_combos) * len(filter_bank),
        "baseline": {
            "params": baseline_run["params"],
            "filter_label": baseline_run["filter_label"],
            "summary": baseline_run["summary"],
        },
        "best_overall": best_full,
        "improvement_return_pct": round(
            best_full["summary"]["total_return_pct"] - baseline_run["summary"]["total_return_pct"], 2
        ),
        "best_by_expost_regime": best_by_expost_regime,
        "best_by_causal_regime": best_by_causal_regime,
        "top_5_variations": [
            {
                "rank": idx + 1,
                "params": r["params"],
                "filter_label": r["filter_label"],
                "summary": r["summary"],
            }
            for idx, r in enumerate(all_runs[:5])
        ],
    }


def simulate_causal_adaptive_meta_bot(
    df: pd.DataFrame,
    bot_optimizations: List[Dict[str, Any]],
    timeframe: str = "1d",
    symbol: str = "^BVSP",
    initial_capital: float = BACKTEST_DEFAULTS["initial_capital"],
) -> Dict[str, Any]:
    """
    Responde na prática: "Em mês de alta qual estratégia funciona, e COMO usar ela sem saber que o mês é de alta?"

    Como funciona:
    1. Analisa todos os robôs otimizados e elege o Campeão Especialista para cada estado:
       - Especialista em ALTA
       - Especialista em LATERAL (De Lado)
       - Especialista em BAIXA
    2. Simula duas carteiras adaptativas:
       A) SELETOR CAUSAL (ZERO LOOK-AHEAD — Mundo Real):
          Na barra t, olha APENAS o detector `causal_regime[t]` (calculado estritamente até t-1 sem saber
          como o mês vai terminar!) e aceita apenas sinais do Robô Especialista daquele regime causal!
       B) ORÁCULO EX-POST (Com Look-Ahead — Referência Teórica):
          Escolhe o robô sabendo de antemão se o mês inteiro será de ALTA, LATERAL ou BAIXA.
    3. Compara com o Melhor Robô Fixo (operando sozinho o tempo todo) e com o Buy & Hold do Ibovespa/Ativo.
    """
    # 1. Seleciona o robô especialista para cada regime Causal e Ex-Post
    causal_specialists: Dict[str, Dict[str, Any]] = {}
    expost_specialists: Dict[str, Dict[str, Any]] = {}

    for reg in ("ALTA", "LATERAL", "BAIXA"):
        # Especialista Causal (escolhido pelo desempenho quando o estado causal é `reg`)
        best_c = max(
            bot_optimizations,
            key=lambda b: (
                b["best_by_causal_regime"][reg]["metrics"].get("robustness_score", -999),
                b["best_by_causal_regime"][reg]["metrics"].get("total_return_pct", -999),
            ),
        )
        c_cfg = best_c["best_by_causal_regime"][reg]
        c_run = run_bot_backtest(
            df,
            best_c["bot_id"],
            params=c_cfg["params"],
            filters=FilterConfig(**c_cfg["filters"]),
            timeframe=timeframe,
            symbol=symbol,
            include_trades_list=True,
        )
        causal_specialists[reg] = {
            "regime": reg,
            "bot_id": best_c["bot_id"],
            "bot_name": best_c["bot_name"],
            "family": best_c["family"],
            "params": c_cfg["params"],
            "filters": c_cfg["filters"],
            "filter_label": c_cfg["filter_label"],
            "regime_metrics": c_cfg["metrics"],
            "trades_in_regime": [t for t in c_run["trades"] if t["causal_regime"] == reg],
        }

        # Especialista Ex-Post (quando sabemos que o mês inteiro foi `reg`)
        best_e = max(
            bot_optimizations,
            key=lambda b: (
                b["best_by_expost_regime"][reg]["metrics"].get("robustness_score", -999),
                b["best_by_expost_regime"][reg]["metrics"].get("total_return_pct", -999),
            ),
        )
        e_cfg = best_e["best_by_expost_regime"][reg]
        e_run = run_bot_backtest(
            df,
            best_e["bot_id"],
            params=e_cfg["params"],
            filters=FilterConfig(**e_cfg["filters"]),
            timeframe=timeframe,
            symbol=symbol,
            include_trades_list=True,
        )
        expost_specialists[reg] = {
            "regime": reg,
            "bot_id": best_e["bot_id"],
            "bot_name": best_e["bot_name"],
            "family": best_e["family"],
            "params": e_cfg["params"],
            "filters": e_cfg["filters"],
            "filter_label": e_cfg["filter_label"],
            "regime_metrics": e_cfg["metrics"],
            "trades_in_regime": [t for t in e_run["trades"] if t["expost_regime"] == reg],
        }

    # 2. Reconstrói a sequência cronológica de trades do Seletor Causal (sem sobreposição de posição)
    causal_pool = []
    for reg, spec in causal_specialists.items():
        for t in spec["trades_in_regime"]:
            t_copy = dict(t)
            t_copy["selected_by_regime"] = reg
            t_copy["bot_name"] = spec["bot_name"]
            causal_pool.append(t_copy)
    causal_pool.sort(key=lambda x: x["entry_ts"])

    causal_trades = []
    last_exit_ts = ""
    for t in causal_pool:
        if t["entry_ts"] > last_exit_ts:
            causal_trades.append(t)
            last_exit_ts = t["exit_ts"]

    # 3. Reconstrói a sequência de trades do Oráculo Ex-Post
    oracle_pool = []
    for reg, spec in expost_specialists.items():
        for t in spec["trades_in_regime"]:
            t_copy = dict(t)
            t_copy["selected_by_regime"] = reg
            t_copy["bot_name"] = spec["bot_name"]
            oracle_pool.append(t_copy)
    oracle_pool.sort(key=lambda x: x["entry_ts"])

    oracle_trades = []
    last_exit_oracle = ""
    for t in oracle_pool:
        if t["entry_ts"] > last_exit_oracle:
            oracle_trades.append(t)
            last_exit_oracle = t["exit_ts"]

    causal_metrics = _compute_slice_metrics(causal_trades, initial_capital)
    oracle_metrics = _compute_slice_metrics(oracle_trades, initial_capital)

    best_single = max(bot_optimizations, key=lambda b: b["best_overall"]["summary"]["total_return_pct"])
    single_metrics = best_single["best_overall"]["summary"]

    # Buy & Hold no mesmo período
    if not df.empty:
        bh_ret_pct = ((float(df["close"].iloc[-1]) / float(df["close"].iloc[0])) - 1.0) * 100.0
    else:
        bh_ret_pct = 0.0

    # Curva de capital do Seletor Causal
    causal_curve = [{"ts": str(df.index[0])[:10] if not df.empty else "", "equity": initial_capital}]
    eq = initial_capital
    for t in causal_trades:
        eq += t["net_pnl_brl"]
        causal_curve.append({"ts": t["exit_ts"][:16], "equity": round(eq, 2), "regime": t["selected_by_regime"], "bot_id": t["bot_id"]})

    return {
        "causal_specialists": {
            reg: {k: v for k, v in spec.items() if k != "trades_in_regime"}
            for reg, spec in causal_specialists.items()
        },
        "expost_specialists": {
            reg: {k: v for k, v in spec.items() if k != "trades_in_regime"}
            for reg, spec in expost_specialists.items()
        },
        "comparison": {
            "buy_and_hold_return_pct": round(bh_ret_pct, 2),
            "best_single_bot": {
                "bot_id": best_single["bot_id"],
                "bot_name": best_single["bot_name"],
                "metrics": single_metrics,
            },
            "causal_adaptive_selector": {
                "description": "Troca de robô em tempo real usando APENAS indicadores causais até t-1 (Sem saber o futuro!)",
                "metrics": causal_metrics,
            },
            "expost_oracle_selector": {
                "description": "Referência teórica sabendo de antemão se o mês fechou em Alta, Lateral ou Baixa",
                "metrics": oracle_metrics,
            },
        },
        "causal_equity_curve": causal_curve,
        "recent_causal_trades": causal_trades[-40:],
    }


def run_arena_analysis(
    symbol: str = "^BVSP",
    timeframes: Optional[List[str]] = None,
    start_date: str = "2020-01-01",
    max_param_combos: int = 6,
) -> Dict[str, Any]:
    """
    Executa a bateria completa de backtests, exaustão de filtros e classificação por sentimento de mercado
    para todos os 10 robôs do canal @norisknogainoficial em múltiplos timeframes.
    """
    feed = MultiTimeframeDataFeed()
    symbol = feed.normalize_symbol(symbol)
    tfs = timeframes or ["5m", "15m", "60m", "1d", "1wk"]

    results_by_tf: Dict[str, Any] = {}
    day_profile_matrix: Dict[str, Any] = {}

    for tf in tfs:
        raw_df = feed.get_bars(symbol, timeframe=tf, start_date=start_date if tf in ("1d", "1wk") else None)
        if raw_df.empty:
            continue
        df = enrich_indicators_and_regimes(raw_df, timeframe=tf)
        regime_stats = summarize_market_regimes(df)

        bot_results = []
        for bot in NORISKNOGAIN_BOTS:
            opt = exhaust_bot_parameters_and_filters(
                df,
                bot.bot_id,
                timeframe=tf,
                symbol=symbol,
                max_param_combos=max_param_combos,
                thorough_filters=(tf in ("1m", "2m", "3m", "5m", "15m", "60m", "1d")),
            )
            bot_results.append(opt)

        bot_results.sort(
            key=lambda b: (
                b["best_overall"]["summary"]["robustness_score"],
                b["best_overall"]["summary"]["total_return_pct"],
            ),
            reverse=True,
        )

        meta_selector = simulate_causal_adaptive_meta_bot(df, bot_results, timeframe=tf, symbol=symbol)

        # Campeões por Perfil do Dia (Volume Alto/Baixo e Direção do Pregão)
        vol_champions = {}
        for vp in ("VOLUME_ALTO", "VOLUME_NORMAL", "VOLUME_BAIXO"):
            champ = max(
                bot_results,
                key=lambda b: b["best_overall"]["by_volume_profile"].get(vp, {}).get("robustness_score", -999),
            )
            vol_champions[vp] = {
                "bot_id": champ["bot_id"],
                "bot_name": champ["bot_name"],
                "filter_label": champ["best_overall"]["filter_label"],
                "metrics": champ["best_overall"]["by_volume_profile"].get(vp, {}),
            }

        dir_champions = {}
        for dd in ("DIA_DIRECIONAL_ALTA", "DIA_DIRECIONAL_BAIXA", "DIA_LATERAL_OSCILANTE"):
            champ = max(
                bot_results,
                key=lambda b: b["best_overall"]["by_day_direction"].get(dd, {}).get("robustness_score", -999),
            )
            dir_champions[dd] = {
                "bot_id": champ["bot_id"],
                "bot_name": champ["bot_name"],
                "filter_label": champ["best_overall"]["filter_label"],
                "metrics": champ["best_overall"]["by_day_direction"].get(dd, {}),
            }

        results_by_tf[tf] = {
            "timeframe": tf,
            "bars_count": len(df),
            "period_start": str(df.index[0])[:16],
            "period_end": str(df.index[-1])[:16],
            "regime_summary": regime_stats,
            "bots_ranking": bot_results,
            "meta_causal_selector": meta_selector,
            "champions_by_volume_profile": vol_champions,
            "champions_by_day_direction": dir_champions,
        }

    return {
        "symbol": symbol,
        "channel": "No Risk No Gain - Robôs Para Day Trade (@norisknogainoficial)",
        "timeframes_evaluated": list(results_by_tf.keys()),
        "by_timeframe": results_by_tf,
    }
