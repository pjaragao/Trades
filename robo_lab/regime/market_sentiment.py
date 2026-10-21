"""
Classificador de Sentimento de Mercado, Perfil do Dia da Bolsa e Detector Causal (Zero Look-Ahead).

Resolve os dois problemas centrais levantados pelo usuário:
1. Classificação Ex-Post (Diagnóstico Histórico):
   - Classifica cada mês/semana/dia como ALTA, BAIXA ou LATERAL (De Lado), além do perfil do pregão:
     Volume (Explosivo, Acima da Média, Fraco), Direção (Direcional Alta, Direcional Baixa, Lateral/Pavio) e Gap.
   - Permite responder: "Em mês de alta (ou dia de alto volume direcional), qual robô e quais filtros funcionam melhor?"

2. Classificação Causal / Point-in-Time (Operação no Mundo Real SEM saber o futuro):
   - No dia 1 ou dia 10 do mês (ou às 10h30 da manhã no Day Trade), NÃO sabemos como o mês ou o dia vai fechar.
   - O Detector Causal usa EXCLUSIVAMENTE dados até a barra anterior (t-1) e a abertura da barra atual para
     estimar em tempo real o estado do mercado:
       * `CAUSAL_ALTA` (Tendência de Alta confirmada sem look-ahead)
       * `CAUSAL_BAIXA` (Tendência de Baixa / Stress confirmado sem look-ahead)
       * `CAUSAL_LATERAL` (Consolidação / Ruído / Oscilação em faixa)
   - Calcula indicadores causais:
       * Eficiência Direcional de Kaufman (ER_10): razão |Close_{t-1} - Close_{t-11}| / soma(|Delta Close|)
       * ADX(14) causal e DI+ vs DI-
       * Alinhamento de Médias (Close_{t-1} vs EMA20 vs EMA50 vs EMA200) e inclinação (slope)
       * Regime de Volume Relativo (Vol_{t-1} / SMA(Vol, 20))
       * Razão de Volatilidade Curta/Longa (ATR_5 / ATR_20)
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd


def enrich_indicators_and_regimes(df: pd.DataFrame, timeframe: str = "1d") -> pd.DataFrame:
    """
    Calcula todos os indicadores técnicos, classificações Ex-Post (para mapear onde cada robô brilha)
    e classificações Causais estritamente defasadas (t-1, zero look-ahead) para decisão em tempo real.
    """
    if df.empty:
        return df.copy()

    out = df.copy()
    c = out["close"].astype(float)
    o = out["open"].astype(float)
    h = out["high"].astype(float)
    l = out["low"].astype(float)
    v = out["volume"].astype(float).replace(0, np.nan).ffill().fillna(1.0)

    # 1. Médias Móveis e Tendência
    out["sma9"] = c.rolling(9, min_periods=2).mean()
    out["sma20"] = c.rolling(20, min_periods=5).mean()
    out["sma50"] = c.rolling(50, min_periods=10).mean()
    out["ema8"] = c.ewm(span=8, adjust=False).mean()
    out["ema10"] = c.ewm(span=10, adjust=False).mean()
    out["ema20"] = c.ewm(span=20, adjust=False).mean()
    out["ema50"] = c.ewm(span=50, adjust=False).mean()
    out["ema80"] = c.ewm(span=80, adjust=False).mean()
    out["ema200"] = c.ewm(span=200, adjust=False).mean()

    # Canal 2MV Padrão (Média das Máximas e Média das Mínimas)
    out["ema20_high"] = h.ewm(span=20, adjust=False).mean()
    out["ema20_low"] = l.ewm(span=20, adjust=False).mean()

    # 2. Volatilidade (True Range & ATR)
    prev_c = c.shift(1).bfill()
    tr = pd.concat([
        (h - l).abs(),
        (h - prev_c).abs(),
        (l - prev_c).abs(),
    ], axis=1).max(axis=1)
    out["tr"] = tr
    out["atr5"] = tr.rolling(5, min_periods=2).mean()
    out["atr14"] = tr.rolling(14, min_periods=3).mean()
    out["atr20"] = tr.rolling(20, min_periods=5).mean()
    out["atr_pct"] = (out["atr14"] / c).fillna(0.015)

    # Desvio padrão e Bandas de Bollinger / Keltner
    out["std20"] = c.rolling(20, min_periods=5).std().fillna(out["atr14"])
    out["bb_upper"] = out["sma20"] + 2.0 * out["std20"]
    out["bb_lower"] = out["sma20"] - 2.0 * out["std20"]
    out["keltner_upper"] = out["sma20"] + 2.0 * out["atr20"]
    out["keltner_lower"] = out["sma20"] - 2.0 * out["atr20"]

    # VWAP Rolling (Intraday reinicia por dia; no diário usa VWAP móvel de 20 períodos)
    typical_price = (h + l + c) / 3.0
    tp_vol = typical_price * v
    if timeframe in ("5m", "15m", "60m"):
        day_group = out.index.date
        cum_tp_vol = tp_vol.groupby(day_group).cumsum()
        cum_vol = v.groupby(day_group).cumsum()
        out["vwap"] = (cum_tp_vol / cum_vol.replace(0, np.nan)).fillna(c)
    else:
        out["vwap"] = (tp_vol.rolling(20, min_periods=3).sum() / v.rolling(20, min_periods=3).sum()).fillna(out["sma20"])

    # 3. Osciladores: IFR2 (Stormer) e IFR14
    delta = c.diff()
    for period, col_name in [(2, "rsi2"), (14, "rsi14")]:
        gain = delta.clip(lower=0.0).ewm(alpha=1.0 / period, adjust=False).mean()
        loss = (-delta.clip(upper=0.0)).ewm(alpha=1.0 / period, adjust=False).mean()
        rs = gain / loss.replace(0.0, 1e-9)
        out[col_name] = 100.0 - (100.0 / (1.0 + rs))

    # MACD (12, 26, 9)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()

    # HiLo Activator (6 períodos padrão No Risk No Gain)
    hilo_high = h.rolling(6, min_periods=2).mean().shift(1)
    hilo_low = l.rolling(6, min_periods=2).mean().shift(1)
    hilo_dir = np.where(c > hilo_high, 1, np.where(c < hilo_low, -1, 0))
    out["hilo_dir"] = pd.Series(hilo_dir, index=out.index).replace(0, np.nan).ffill().fillna(1)

    # 4. Eficiência Direcional de Kaufman (ER) e ADX(14)
    er_window = 10
    direction_change = (c - c.shift(er_window)).abs()
    volatility_sum = c.diff().abs().rolling(er_window, min_periods=3).sum().replace(0, 1e-9)
    out["efficiency_ratio"] = (direction_change / volatility_sum).clip(0.0, 1.0).fillna(0.25)

    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr14_safe = out["atr14"].replace(0, 1e-9)
    plus_di = 100.0 * pd.Series(plus_dm, index=out.index).ewm(alpha=1 / 14, adjust=False).mean() / atr14_safe
    minus_di = 100.0 * pd.Series(minus_dm, index=out.index).ewm(alpha=1 / 14, adjust=False).mean() / atr14_safe
    dx = (100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)).fillna(15.0)
    out["adx14"] = dx.ewm(alpha=1 / 14, adjust=False).mean().fillna(15.0)
    out["plus_di"] = plus_di
    out["minus_di"] = minus_di

    # 5. Perfil do Pregão / Barra (Volume, Direção, Gap, Corpo)
    vol_sma20 = v.rolling(20, min_periods=3).mean().replace(0, 1.0)
    out["vol_ratio"] = (v / vol_sma20).fillna(1.0)
    out["gap_pct"] = ((o - prev_c) / prev_c).fillna(0.0)
    bar_range = (h - l).replace(0, 1e-9)
    out["body_ratio"] = ((c - o).abs() / bar_range).clip(0.0, 1.0)
    out["bar_return_pct"] = ((c - o) / o).fillna(0.0)

    # Classificação de Perfil da Bolsa na Barra/Dia
    out["volume_profile"] = np.where(
        out["vol_ratio"] >= 1.35, "VOLUME_ALTO",
        np.where(out["vol_ratio"] <= 0.75, "VOLUME_BAIXO", "VOLUME_NORMAL")
    )
    out["day_direction_profile"] = np.where(
        (out["body_ratio"] >= 0.50) & (c > o), "DIA_DIRECIONAL_ALTA",
        np.where(
            (out["body_ratio"] >= 0.50) & (c < o), "DIA_DIRECIONAL_BAIXA",
            "DIA_LATERAL_OSCILANTE"
        )
    )

    # =========================================================================
    # 6. CLASSIFICAÇÃO EX-POST DE SENTIMENTO MENSAL / PERÍODO (Para diagnóstico)
    # =========================================================================
    out["year_month"] = out.index.strftime("%Y-%m")
    monthly_first = c.groupby(out["year_month"]).transform("first")
    monthly_last = c.groupby(out["year_month"]).transform("last")
    out["expost_month_return_pct"] = ((monthly_last / monthly_first) - 1.0) * 100.0

    # Limiares de sentimento mensal da bolsa:
    # > +2.0%: ALTA | < -2.0%: BAIXA | entre -2.0% e +2.0%: LATERAL (DE LADO)
    out["expost_regime"] = np.where(
        out["expost_month_return_pct"] > 2.0, "ALTA",
        np.where(out["expost_month_return_pct"] < -2.0, "BAIXA", "LATERAL")
    )

    # =========================================================================
    # 7. DETECTOR CAUSAL DE SENTIMENTO (ZERO LOOK-AHEAD: usa apenas até t-1!)
    # Como saber qual estratégia usar SEM saber que o mês/semana será de alta!
    # =========================================================================
    c_prev = c.shift(1)
    ema20_prev = out["ema20"].shift(1)
    ema50_prev = out["ema50"].shift(1)
    ema200_prev = out["ema200"].shift(1)
    adx_prev = out["adx14"].shift(1).fillna(15.0)
    er_prev = out["efficiency_ratio"].shift(1).fillna(0.25)
    ret5_prev = c_prev.pct_change(5).fillna(0.0)
    ret15_prev = c_prev.pct_change(15).fillna(0.0)
    ema20_slope = ema20_prev.pct_change(3).fillna(0.0)

    # Score direcional causal [-100, +100] calculado ANTES da abertura/fechamento da barra t:
    trend_score = (
        np.where(c_prev > ema20_prev, 25.0, -25.0)
        + np.where(ema20_prev > ema50_prev, 25.0, -25.0)
        + np.where(c_prev > ema200_prev, 15.0, -15.0)
        + np.where(ema20_slope > 0.001, 15.0, np.where(ema20_slope < -0.001, -15.0, 0.0))
        + np.where(ret5_prev > 0.008, 10.0, np.where(ret5_prev < -0.008, -10.0, 0.0))
        + np.where(ret15_prev > 0.015, 10.0, np.where(ret15_prev < -0.015, -10.0, 0.0))
    )
    out["causal_trend_score"] = pd.Series(trend_score, index=out.index).fillna(0.0)

    # Força de tendência vs lateralidade causal (sem olhar o futuro):
    # Se Efficiency Ratio < 0.22 ou ADX < 18 ou |trend_score| <= 25 -> Mercado está LATERAL (De Lado)!
    is_causal_lateral = (
        ((er_prev < 0.22) & (adx_prev < 22.0))
        | (adx_prev < 16.5)
        | (out["causal_trend_score"].abs() <= 25.0)
    )
    out["causal_regime"] = np.where(
        is_causal_lateral,
        "LATERAL",
        np.where(out["causal_trend_score"] > 25.0, "ALTA", "BAIXA")
    )

    # Confiança causal (0 a 100%)
    out["causal_confidence"] = np.where(
        out["causal_regime"] == "LATERAL",
        np.clip(100.0 - adx_prev * 2.2, 40.0, 95.0),
        np.clip(out["causal_trend_score"].abs() * 0.75 + adx_prev * 0.8, 45.0, 98.0),
    )

    return out


def summarize_market_regimes(df: pd.DataFrame) -> Dict[str, Any]:
    """Gera estatísticas de distribuição de regimes Ex-Post vs Causais e taxa de coincidência."""
    if df.empty or "expost_regime" not in df.columns:
        return {}

    expost_counts = df["expost_regime"].value_counts(normalize=True).to_dict()
    causal_counts = df["causal_regime"].value_counts(normalize=True).to_dict()
    vol_counts = df["volume_profile"].value_counts(normalize=True).to_dict()
    dir_counts = df["day_direction_profile"].value_counts(normalize=True).to_dict()

    # Matriz de transição / acerto direcional do detector causal sem olhar o futuro
    non_opposite = (
        ((df["causal_regime"] == "ALTA") & (df["expost_regime"] != "BAIXA"))
        | ((df["causal_regime"] == "BAIXA") & (df["expost_regime"] != "ALTA"))
        | (df["causal_regime"] == "LATERAL")
    ).mean()

    return {
        "total_bars": len(df),
        "expost_distribution_pct": {k: round(v * 100, 1) for k, v in expost_counts.items()},
        "causal_distribution_pct": {k: round(v * 100, 1) for k, v in causal_counts.items()},
        "volume_profile_pct": {k: round(v * 100, 1) for k, v in vol_counts.items()},
        "day_direction_pct": {k: round(v * 100, 1) for k, v in dir_counts.items()},
        "causal_regime_safety_rate_pct": round(float(non_opposite) * 100.0, 1),
    }
