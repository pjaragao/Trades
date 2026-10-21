"""
Implementação dos 10 Robôs de Trade extraídos do canal 'No Risk No Gain - Robôs Para Day Trade' (@norisknogainoficial).
Cada robô gera sinais vetorizados de entrada (+1 compra, -1 venda) e define regras paramétricas de:
- Alvo (Take Profit em ATR, banda oposta, média ou projeção de Fibonacci)
- Stop Loss (em ATR, mínima/máxima de N candles ou saída dinâmica)
- Tempo máximo de permanência na operação (Max Hold Bars)
"""

from typing import Any, Callable, Dict, List, Tuple

import numpy as np
import pandas as pd

from robo_lab.strategies.base_bot import BotSpecification, FilterConfig


# =============================================================================
# 1. NRNG-001: Robô Cash Bands (Bandas de Volatilidade True Range + Tendência)
# Vídeo: WOmf-78GWS4 ("Robô Cash Bands - A Estratégia que virou a minha CHAVE no Day Trade")
# =============================================================================
def signals_cash_bands(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Opera oscilação natural do preço nas Bandas de True Range (ATR) filtradas por Média Curta vs Longa.
    Alvo curto/médio (banda oposta ou múltiplo de ATR) e Stop longo de segurança (2.5x a 3.5x ATR).
    """
    c = df["close"].to_numpy()
    l = df["low"].to_numpy()
    h = df["high"].to_numpy()
    atr = df["atr14"].to_numpy()

    fast_p = int(params.get("fast_ma", 9))
    slow_p = int(params.get("slow_ma", 21))
    band_mult = float(params.get("band_atr_mult", 0.85))
    target_atr = float(params.get("target_atr_mult", 1.1))
    stop_atr = float(params.get("stop_atr_mult", 2.8))
    max_hold = int(params.get("max_hold_bars", 8))

    ma_fast = pd.Series(c).ewm(span=fast_p, adjust=False).mean().to_numpy()
    ma_slow = pd.Series(c).ewm(span=slow_p, adjust=False).mean().to_numpy()

    lower_band = ma_fast - band_mult * atr
    upper_band = ma_fast + band_mult * atr

    buy_cond = (ma_fast >= ma_slow) & (l <= lower_band)
    sell_cond = (ma_fast < ma_slow) & (h >= upper_band)

    entry = np.where(buy_cond, 1, np.where(sell_cond, -1, 0))
    tp_dist = target_atr * atr
    sl_dist = stop_atr * atr
    return entry, tp_dist, sl_dist, max_hold


# =============================================================================
# 2. NRNG-002: Robô Keltner com Reversão à Média / Preço Médio (Round 6)
# Vídeo: xXolrydmNis ("O Único ROBÔ de Keltner com Preço Médio para Day Trade")
# =============================================================================
def signals_keltner_reversion(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Compra quando fecha vela negativa abaixo da Banda Inferior de Keltner;
    Vende quando fecha vela positiva acima da Banda Superior de Keltner.
    Alvo no retorno à Média Móvel (SMA 9 ou 20).
    """
    c = df["close"].to_numpy()
    o = df["open"].to_numpy()
    atr = df["atr20"].to_numpy()

    k_period = int(params.get("keltner_period", 20))
    k_dev = float(params.get("keltner_dev", 1.6))
    stop_atr = float(params.get("stop_atr_mult", 2.6))
    max_hold = int(params.get("max_hold_bars", 10))

    sma_k = pd.Series(c).rolling(k_period, min_periods=5).mean().to_numpy()
    k_upper = sma_k + k_dev * atr
    k_lower = sma_k - k_dev * atr

    buy_cond = (c < k_lower) & (c < o)
    sell_cond = (c > k_upper) & (c > o)

    entry = np.where(buy_cond, 1, np.where(sell_cond, -1, 0))
    # Distância do fechamento até a média central como alvo dinâmico
    tp_dist = np.maximum(np.abs(sma_k - c), 0.75 * atr)
    sl_dist = stop_atr * atr
    return entry, tp_dist, sl_dist, max_hold


# =============================================================================
# 3. NRNG-003: Robô Setup IFR2 (Stormer Adaptado com Média de Filtro)
# Vídeo: bhMJbMrhifI ("Como Criar um ROBÔ do Setup IFR2 do Stormer no Profit")
# =============================================================================
def signals_ifr2_stormer(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Compra quando Close > SMA(ma_period) e IFR(2) < buy_level (ex: 15 ou 25),
    saindo na máxima dos últimos 2 candles.
    Venda quando Close < SMA(ma_period) e IFR(2) > sell_level (ex: 85 ou 75),
    saindo na mínima dos últimos 2 candles.
    """
    c = df["close"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    rsi2 = df["rsi2"].to_numpy()
    atr = df["atr14"].to_numpy()

    ma_period = int(params.get("ma_period", 20))
    buy_lvl = float(params.get("rsi_buy_level", 20.0))
    sell_lvl = float(params.get("rsi_sell_level", 80.0))
    stop_atr = float(params.get("stop_atr_mult", 2.2))
    max_hold = int(params.get("max_hold_bars", 5))

    ma_filter = pd.Series(c).rolling(ma_period, min_periods=5).mean().to_numpy()
    high_2 = pd.Series(h).rolling(2, min_periods=1).max().to_numpy()
    low_2 = pd.Series(l).rolling(2, min_periods=1).min().to_numpy()

    buy_cond = (c > ma_filter) & (rsi2 <= buy_lvl)
    sell_cond = (c < ma_filter) & (rsi2 >= sell_lvl)

    entry = np.where(buy_cond, 1, np.where(sell_cond, -1, 0))
    tp_buy = np.maximum(high_2 - c, 0.7 * atr)
    tp_sell = np.maximum(c - low_2, 0.7 * atr)
    tp_dist = np.where(entry == 1, tp_buy, tp_sell)
    sl_dist = stop_atr * atr
    return entry, tp_dist, sl_dist, max_hold


# =============================================================================
# 4. NRNG-004: Robô Scalper de VWAP Bands / Gradiente Linear
# Vídeos: QTIVjQ-2mko ("Robô Scalper de VWAP BANDS"), fGTLG0aUHB0, Fv8DwS5phOM
# =============================================================================
def signals_vwap_gradient_bands(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Opera os níveis de desvio da VWAP (Bandas -1, -2, -3 e +1, +2, +3),
    comprando nos desvios negativos e realizando no nível imediatamente superior (lógica Gradiente Linear).
    """
    c = df["close"].to_numpy()
    l = df["low"].to_numpy()
    h = df["high"].to_numpy()
    vwap = df["vwap"].to_numpy()
    atr = df["atr14"].to_numpy()

    band_atr_step = float(params.get("band_atr_step", 0.9))
    stop_atr = float(params.get("stop_atr_mult", 2.4))
    max_hold = int(params.get("max_hold_bars", 6))

    b_up1 = vwap + band_atr_step * atr
    b_dn1 = vwap - band_atr_step * atr

    # Compra quando testa a banda inferior da VWAP e fecha mostrando defesa
    buy_cond = (l <= b_dn1) & (c >= b_dn1 * 0.998)
    sell_cond = (h >= b_up1) & (c <= b_up1 * 1.002)

    entry = np.where(buy_cond, 1, np.where(sell_cond, -1, 0))
    tp_dist = band_atr_step * atr
    sl_dist = stop_atr * atr
    return entry, tp_dist, sl_dist, max_hold


# =============================================================================
# 5. NRNG-005: Robô Alinhamento de 3 Médias + Filtro de Afastamento
# Vídeo: GoUPpPav_DU ("Como Programar um Robô de Alinhamento de Medias")
# =============================================================================
def signals_triple_ma_alignment(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Seguidor de tendência puro: M1 > M2 > M3 e Close > M1,
    com filtro de afastamento |M2 - M3| >= min_spread_atr * ATR para evitar consolidação!
    """
    c = df["close"].to_numpy()
    atr = df["atr14"].to_numpy()

    p1 = int(params.get("m1_period", 10))
    p2 = int(params.get("m2_period", 20))
    p3 = int(params.get("m3_period", 50))
    min_spread_atr = float(params.get("min_spread_atr", 0.35))
    target_atr = float(params.get("target_atr_mult", 2.4))
    stop_atr = float(params.get("stop_atr_mult", 1.3))
    max_hold = int(params.get("max_hold_bars", 14))

    m1 = pd.Series(c).ewm(span=p1, adjust=False).mean().to_numpy()
    m2 = pd.Series(c).ewm(span=p2, adjust=False).mean().to_numpy()
    m3 = pd.Series(c).ewm(span=p3, adjust=False).mean().to_numpy()

    spread_ok = np.abs(m2 - m3) >= (min_spread_atr * atr)
    # Gatilho de início/retomada de alinhamento para não recomprar topo exausto
    prev_c = np.roll(c, 1)
    prev_m1 = np.roll(m1, 1)
    prev_c[0] = c[0]
    prev_m1[0] = m1[0]

    buy_cond = (m1 > m2) & (m2 > m3) & (c > m1) & spread_ok & ((prev_c <= prev_m1 * 1.005) | (df["rsi14"].to_numpy() < 68))
    sell_cond = (m1 < m2) & (m2 < m3) & (c < m1) & spread_ok & ((prev_c >= prev_m1 * 0.995) | (df["rsi14"].to_numpy() > 32))

    entry = np.where(buy_cond, 1, np.where(sell_cond, -1, 0))
    tp_dist = target_atr * atr
    sl_dist = stop_atr * atr
    return entry, tp_dist, sl_dist, max_hold


# =============================================================================
# 6. NRNG-006: Robô 2MV Padrão (Canal de Médias de Máximas e Mínimas)
# Vídeo: YI28qY-9HYE ("Robô 2MV Padrão - Como criar um robô [PASSO A PASSO]")
# =============================================================================
def signals_2mv_padrao(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Canal formado pela EMA(period, High) e EMA(period, Low).
    Compra no primeiro candle positivo que fecha acima da EMA das Máximas (saindo do box branco/neutro).
    Venda no primeiro candle negativo que fecha abaixo da EMA das Mínimas.
    """
    c = df["close"].to_numpy()
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    atr = df["atr14"].to_numpy()

    period = int(params.get("channel_period", 20))
    payoff_mult = float(params.get("payoff_mult", 2.0))
    stop_atr = float(params.get("stop_atr_mult", 1.2))
    max_hold = int(params.get("max_hold_bars", 12))

    ema_high = pd.Series(h).ewm(span=period, adjust=False).mean().to_numpy()
    ema_low = pd.Series(l).ewm(span=period, adjust=False).mean().to_numpy()

    prev_c = np.roll(c, 1)
    prev_eh = np.roll(ema_high, 1)
    prev_el = np.roll(ema_low, 1)
    prev_c[0] = c[0]

    buy_cond = (c > ema_high) & (c > o) & (prev_c <= prev_eh)
    sell_cond = (c < ema_low) & (c < o) & (prev_c >= prev_el)

    entry = np.where(buy_cond, 1, np.where(sell_cond, -1, 0))
    sl_dist = stop_atr * atr
    tp_dist = payoff_mult * sl_dist
    return entry, tp_dist, sl_dist, max_hold


# =============================================================================
# 7. NRNG-007: Robô Setup 123 (Stormer / Mark Crisp com Alvo Fibonacci 161.8%)
# Vídeo: KqK0OQovqz8 ("Como Criar um ROBÔ Setup 123 de Compra e Venda do Stormer")
# =============================================================================
def signals_setup_123_fibo(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Identifica formação de Fundo 1-2-3 (Low[1] < Low[2] e Low[0] > Low[1]) ou Topo 1-2-3
    (High[1] > High[2] e High[0] < High[1]) a favor das médias (EMA8 vs EMA80),
    com alvo projetado em 161.8% (ou fibo_mult) da amplitude do padrão.
    """
    c = df["close"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    atr = df["atr14"].to_numpy()
    ema8 = df["ema8"].to_numpy()
    ema80 = df["ema80"].to_numpy()

    fibo_mult = float(params.get("fibo_target_mult", 1.618))
    use_ma_filter = bool(params.get("use_ma_8_80", True))
    max_hold = int(params.get("max_hold_bars", 10))

    l1 = np.roll(l, 1)
    l2 = np.roll(l, 2)
    h1 = np.roll(h, 1)
    h2 = np.roll(h, 2)
    c1 = np.roll(c, 1)
    l1[:2] = l[:2]
    l2[:2] = l[:2]
    h1[:2] = h[:2]
    h2[:2] = h[:2]
    c1[:2] = c[:2]

    # Fundo 123: mínima 1 menor que mínima 2, mínima 0 maior que mínima 1, fechamento maior que anterior e não esticado
    buy_123 = (l > l1) & (l1 < l2) & (c > c1) & (c <= h2 * 1.005)
    sell_123 = (h < h1) & (h1 > h2) & (c < c1) & (c >= l2 * 0.995)

    if use_ma_filter:
        buy_123 = buy_123 & (c > ema8) & (ema8 > ema80)
        sell_123 = sell_123 & (c < ema8) & (ema8 < ema80)

    entry = np.where(buy_123, 1, np.where(sell_123, -1, 0))
    risk_buy = np.clip(c - l1, 0.5 * atr, 2.5 * atr)
    risk_sell = np.clip(h1 - c, 0.5 * atr, 2.5 * atr)
    sl_dist = np.where(entry == 1, risk_buy, risk_sell)
    tp_dist = fibo_mult * sl_dist
    return entry, tp_dist, sl_dist, max_hold


# =============================================================================
# 8. NRNG-008: Robô HiLo Activator + MACD com Stop nas 5 Mínimas/Máximas
# Vídeos: blngdl8VYwg ("Robô Renko com HILO") + g4iJPgDA8ww ("Robô MACD no ProfitChart")
# =============================================================================
def signals_hilo_macd(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Combina a virada/tendência do HiLo Activator com cruzamento/alinhamento do MACD,
    posicionando o stop na menor mínima dos últimos N períodos (Lowest Low / Highest High).
    """
    c = df["close"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    atr = df["atr14"].to_numpy()
    macd = df["macd"].to_numpy()
    macd_sig = df["macd_signal"].to_numpy()

    hilo_p = int(params.get("hilo_period", 6))
    stop_lb = int(params.get("stop_lookback", 5))
    payoff_mult = float(params.get("payoff_mult", 1.8))
    max_hold = int(params.get("max_hold_bars", 12))

    hilo_h = pd.Series(h).rolling(hilo_p, min_periods=2).mean().shift(1).bfill().to_numpy()
    hilo_l = pd.Series(l).rolling(hilo_p, min_periods=2).mean().shift(1).bfill().to_numpy()

    prev_macd = np.roll(macd, 1)
    prev_sig = np.roll(macd_sig, 1)
    prev_c = np.roll(c, 1)
    prev_hh = np.roll(hilo_h, 1)
    prev_hl = np.roll(hilo_l, 1)

    # Virada do HiLo ou cruzamento do MACD confirmado pelo HiLo
    buy_cond = (c > hilo_h) & (macd > macd_sig) & ((prev_c <= prev_hh) | (prev_macd <= prev_sig))
    sell_cond = (c < hilo_l) & (macd < macd_sig) & ((prev_c >= prev_hl) | (prev_macd >= prev_sig))

    entry = np.where(buy_cond, 1, np.where(sell_cond, -1, 0))
    lowest_n = pd.Series(l).rolling(stop_lb, min_periods=2).min().to_numpy()
    highest_n = pd.Series(h).rolling(stop_lb, min_periods=2).max().to_numpy()

    sl_buy = np.clip(c - lowest_n, 0.6 * atr, 2.5 * atr)
    sl_sell = np.clip(highest_n - c, 0.6 * atr, 2.5 * atr)
    sl_dist = np.where(entry == 1, sl_buy, sl_sell)
    tp_dist = payoff_mult * sl_dist
    return entry, tp_dist, sl_dist, max_hold


# =============================================================================
# 9. NRNG-009: Robô Bandas de Bollinger (Fechou Fora, Fechou Dentro)
# Vídeo: saziFu7u_mA ("Como Programar um Robô BANDAS DE BOLLINGER no ProfitChart")
# =============================================================================
def signals_bollinger_reentry(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Clássico 'Fechou Fora, Fechou Dentro' nas Bandas de Bollinger:
    Barra anterior fechou fora da banda (exaustão) e barra atual fecha reentrando na banda a favor da reversão.
    """
    c = df["close"].to_numpy()
    o = df["open"].to_numpy()
    atr = df["atr14"].to_numpy()

    bb_period = int(params.get("bb_period", 20))
    bb_std = float(params.get("bb_std", 2.0))
    stop_atr = float(params.get("stop_atr_mult", 1.8))
    max_hold = int(params.get("max_hold_bars", 8))

    s_c = pd.Series(c)
    sma = s_c.rolling(bb_period, min_periods=5).mean().to_numpy()
    std = s_c.rolling(bb_period, min_periods=5).std().fillna(pd.Series(atr)).to_numpy()
    upper = sma + bb_std * std
    lower = sma - bb_std * std

    prev_c = np.roll(c, 1)
    prev_lo = np.roll(lower, 1)
    prev_up = np.roll(upper, 1)
    prev_c[0] = c[0]

    buy_cond = (prev_c < prev_lo) & (c > lower) & (c > o)
    sell_cond = (prev_c > prev_up) & (c < upper) & (c < o)

    entry = np.where(buy_cond, 1, np.where(sell_cond, -1, 0))
    tp_dist = np.maximum(np.abs(sma - c), 0.9 * atr)
    sl_dist = stop_atr * atr
    return entry, tp_dist, sl_dist, max_hold


# =============================================================================
# 10. NRNG-010: Robô Golden Hour / Range Breaker + Fair Value Gap (FVG)
# Vídeos: I0IVhZ2MVBg ("74% WIN RATE TRADING ONLY THE FIRST CANDLE"), d0hPQ2FUwuY, 3-dknLPG0wQ
# =============================================================================
def signals_range_fvg_breaker(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """
    Detecta ignição institucional por rompimento de range curto / 1º Candle ou formação de Fair Value Gap (FVG),
    buscando alvos rápidos de alta assertividade (74%+ win rate como demonstrado no vídeo).
    """
    c = df["close"].to_numpy()
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    atr = df["atr14"].to_numpy()

    box_bars = int(params.get("box_bars", 4))
    target_atr = float(params.get("target_atr_mult", 1.0))
    stop_atr = float(params.get("stop_atr_mult", 1.6))
    max_hold = int(params.get("max_hold_bars", 6))

    box_high = pd.Series(h).rolling(box_bars, min_periods=2).max().shift(1).bfill().to_numpy()
    box_low = pd.Series(l).rolling(box_bars, min_periods=2).min().shift(1).bfill().to_numpy()

    h_lag2 = np.roll(h, 2)
    l_lag2 = np.roll(l, 2)
    h_lag2[:2] = h[:2]
    l_lag2[:2] = l[:2]

    # FVG Bullish (Low[0] > High[2]) ou Rompimento de Range com corpo expressivo
    fvg_bull = (l > h_lag2) & (c > o)
    fvg_bear = (h < l_lag2) & (c < o)

    range_break_bull = (c > box_high) & ((c - o) > 0.45 * atr)
    range_break_bear = (c < box_low) & ((o - c) > 0.45 * atr)

    buy_cond = fvg_bull | range_break_bull
    sell_cond = fvg_bear | range_break_bear

    entry = np.where(buy_cond, 1, np.where(sell_cond, -1, 0))
    tp_dist = target_atr * atr
    sl_dist = stop_atr * atr
    return entry, tp_dist, sl_dist, max_hold


# =============================================================================
# CATÁLOGO DOS 10 ROBÔS DO CANAL @norisknogainoficial
# =============================================================================
BOT_SIGNAL_FUNCTIONS: Dict[str, Callable] = {
    "NRNG-001": signals_cash_bands,
    "NRNG-002": signals_keltner_reversion,
    "NRNG-003": signals_ifr2_stormer,
    "NRNG-004": signals_vwap_gradient_bands,
    "NRNG-005": signals_triple_ma_alignment,
    "NRNG-006": signals_2mv_padrao,
    "NRNG-007": signals_setup_123_fibo,
    "NRNG-008": signals_hilo_macd,
    "NRNG-009": signals_bollinger_reentry,
    "NRNG-010": signals_range_fvg_breaker,
}

NORISKNOGAIN_BOTS: List[BotSpecification] = [
    BotSpecification(
        bot_id="NRNG-001",
        name="Robô Cash Bands (Oscilação True Range)",
        family="MEAN_REVERSION",
        preferred_regimes=["LATERAL", "ALTA"],
        channel_name="No Risk No Gain - Robôs Para Day Trade",
        video_ids=["WOmf-78GWS4", "XGdBjQqn_qk"],
        video_titles=[
            "Robô Cash Bands - A Estratégia que virou a minha CHAVE no Day Trade",
            "The DAY TRADING Robot that operates on the NATURAL PRICE FLUCTUATIONS",
        ],
        thesis=(
            "Estratégia principal de uso diário do autor Gean Gorla. Constrói bandas de volatilidade baseadas "
            "no True Range (ATR) e entra a favor da tendência macro no toque da banda de recuo, buscando "
            "alvos curtos de alta probabilidade (70% a 85% de acerto) com stop de segurança longo."
        ),
        default_params={"fast_ma": 9, "slow_ma": 21, "band_atr_mult": 0.85, "target_atr_mult": 1.1, "stop_atr_mult": 2.8, "max_hold_bars": 8},
        param_grid={
            "band_atr_mult": [0.65, 0.85, 1.10],
            "target_atr_mult": [0.85, 1.15, 1.50],
            "stop_atr_mult": [2.2, 2.8],
        },
    ),
    BotSpecification(
        bot_id="NRNG-002",
        name="Robô Keltner Reversão à Média (Round 6 / Keltner Médio)",
        family="MEAN_REVERSION",
        preferred_regimes=["LATERAL"],
        channel_name="No Risk No Gain - Robôs Para Day Trade",
        video_ids=["xXolrydmNis"],
        video_titles=["O Único ROBÔ de Keltner com Preço Médio para Day Trade no Profit que você irá precisar!"],
        thesis=(
            "Opera o fechamento de velas de exaustão fora dos Canais de Keltner (desvio 1.5 a 2.0) com alvo "
            "de zeragem no retorno à Média Móvel central (9 ou 20 períodos). Muito forte em mercados de lado e tardes calmas."
        ),
        default_params={"keltner_period": 20, "keltner_dev": 1.6, "stop_atr_mult": 2.6, "max_hold_bars": 10},
        param_grid={
            "keltner_period": [14, 20],
            "keltner_dev": [1.4, 1.7, 2.0],
            "stop_atr_mult": [2.0, 2.8],
        },
    ),
    BotSpecification(
        bot_id="NRNG-003",
        name="Robô Setup IFR2 Stormer com Filtro de Média 20",
        family="PULLBACK",
        preferred_regimes=["ALTA", "LATERAL"],
        channel_name="No Risk No Gain - Robôs Para Day Trade",
        video_ids=["bhMJbMrhifI", "vzgRhKBMSyE"],
        video_titles=[
            "Como Criar um ROBÔ do Setup IFR2 do Stormer no Profit",
            "The Swing Trading strategy with a 96% success rate since 1998!!",
        ],
        thesis=(
            "Adaptação automatizada do clássico IFR(2) do Stormer: exige preço acima da Média de 20 períodos "
            "para comprar quando o IFR(2) mergulha em sobrevenda (<15 a <25), saindo na máxima das 2 últimas barras."
        ),
        default_params={"ma_period": 20, "rsi_buy_level": 20.0, "rsi_sell_level": 80.0, "stop_atr_mult": 2.2, "max_hold_bars": 5},
        param_grid={
            "ma_period": [14, 20],
            "rsi_buy_level": [15.0, 22.0, 28.0],
            "stop_atr_mult": [1.8, 2.5],
        },
    ),
    BotSpecification(
        bot_id="NRNG-004",
        name="Robô Scalper VWAP Bands & Gradiente Linear",
        family="GRID_SCALP",
        preferred_regimes=["LATERAL"],
        channel_name="No Risk No Gain - Robôs Para Day Trade",
        video_ids=["QTIVjQ-2mko", "fGTLG0aUHB0", "OV0tz6dif_w", "Fv8DwS5phOM", "roUb-meZZjI"],
        video_titles=[
            "Como Criar um Robô Scalper de VWAP BANDS no Profit",
            "Como Criar um ROBÔ Trader de PREÇO MÉDIO tipo Gradiente Linear",
            "Robô Gradiente linear o MELHOR do Mercado de Day Trade",
        ],
        thesis=(
            "Projeta faixas simétricas em torno da VWAP e opera a malha de oscilação (Gradiente Linear), "
            "comprando nos desvios negativos e realizando na banda imediatamente superior sem depender de direção."
        ),
        default_params={"band_atr_step": 0.9, "stop_atr_mult": 2.4, "max_hold_bars": 6},
        param_grid={
            "band_atr_step": [0.65, 0.90, 1.20],
            "stop_atr_mult": [1.8, 2.5],
            "max_hold_bars": [5, 8],
        },
    ),
    BotSpecification(
        bot_id="NRNG-005",
        name="Robô Alinhamento de 3 Médias + Filtro Anti-Consolidação",
        family="TREND_FOLLOWING",
        preferred_regimes=["ALTA", "BAIXA"],
        channel_name="No Risk No Gain - Robôs Para Day Trade",
        video_ids=["GoUPpPav_DU", "3wPsVN8Jlw8", "61yMh22RMP4"],
        video_titles=[
            "Como Programar um Robô de Alinhamento de Medias para o ProfitChart",
            "Como Criar um Robô Cruzamento de médias (VÁRIOS TIPOS)",
            "THE PERFECT ENTRY POINT - MULTI-TIMEFRAME TRIPLE SCREEN BOT",
        ],
        thesis=(
            "Seguidor de tendência que exige alinhamento simultâneo de 3 médias (curta > média > longa) "
            "mais o filtro de afastamento mínimo |M2 - M3| criado no vídeo para bloquear entradas quando as médias embolam."
        ),
        default_params={"m1_period": 10, "m2_period": 20, "m3_period": 50, "min_spread_atr": 0.35, "target_atr_mult": 2.4, "stop_atr_mult": 1.3, "max_hold_bars": 14},
        param_grid={
            "min_spread_atr": [0.20, 0.40, 0.65],
            "target_atr_mult": [1.8, 2.5, 3.2],
            "stop_atr_mult": [1.1, 1.5],
        },
    ),
    BotSpecification(
        bot_id="NRNG-006",
        name="Robô 2MV Padrão (Rompimento do Canal de Máximas/Mínimas)",
        family="BREAKOUT",
        preferred_regimes=["ALTA", "BAIXA"],
        channel_name="No Risk No Gain - Robôs Para Day Trade",
        video_ids=["YI28qY-9HYE"],
        video_titles=["Robô 2MV Padrão - Como criar um robô [PASSO A PASSO]"],
        thesis=(
            "Replica a regra de coloração institucional 2MV Padrão usando EMA(20, High) e EMA(20, Low). "
            "Ignora o 'box branco' (consolidação entre as médias) e dispara quando fecha vela de força rompendo o canal."
        ),
        default_params={"channel_period": 20, "payoff_mult": 2.0, "stop_atr_mult": 1.2, "max_hold_bars": 12},
        param_grid={
            "channel_period": [12, 20],
            "payoff_mult": [1.5, 2.0, 2.6],
            "stop_atr_mult": [1.0, 1.4],
        },
    ),
    BotSpecification(
        bot_id="NRNG-007",
        name="Robô Setup 123 Stormer com Alvo Fibonacci 161.8%",
        family="PULLBACK",
        preferred_regimes=["ALTA", "BAIXA"],
        channel_name="No Risk No Gain - Robôs Para Day Trade",
        video_ids=["KqK0OQovqz8"],
        video_titles=["Como Criar um ROBÔ Setup 123 de Compra e Venda do Stormer no ProfitChart"],
        thesis=(
            "Detecta pivôs de fundo/topo de 3 barras (Setup 123 de Mark Crisp / Stormer) alinhados às médias 8 e 80, "
            "filtrando barras gigantes e projetando o alvo exatamente em 161.8% de Fibonacci do risco."
        ),
        default_params={"fibo_target_mult": 1.618, "use_ma_8_80": True, "max_hold_bars": 10},
        param_grid={
            "fibo_target_mult": [1.272, 1.618, 2.0],
            "use_ma_8_80": [True, False],
            "max_hold_bars": [8, 14],
        },
    ),
    BotSpecification(
        bot_id="NRNG-008",
        name="Robô HiLo Activator + MACD (Stop nas 5 Mínimas/Máximas)",
        family="TREND_FOLLOWING",
        preferred_regimes=["ALTA", "BAIXA"],
        channel_name="No Risk No Gain - Robôs Para Day Trade",
        video_ids=["blngdl8VYwg", "g4iJPgDA8ww"],
        video_titles=[
            "Robô Renko com HILO - Setup de virada do Box no Profit",
            "Como programar um robô MACD no ProfitChart - Automação de Estratégias",
        ],
        thesis=(
            "Une a virada de tendência do HiLo Activator (6 períodos) com o cruzamento do MACD(12,26,9) "
            "e ancora o stop técnico na menor mínima (ou maior máxima) dos últimos 5 candles."
        ),
        default_params={"hilo_period": 6, "stop_lookback": 5, "payoff_mult": 1.8, "max_hold_bars": 12},
        param_grid={
            "hilo_period": [5, 8],
            "stop_lookback": [3, 5, 8],
            "payoff_mult": [1.5, 2.0, 2.5],
        },
    ),
    BotSpecification(
        bot_id="NRNG-009",
        name="Robô Bandas de Bollinger (Fechou Fora, Fechou Dentro)",
        family="MEAN_REVERSION",
        preferred_regimes=["LATERAL", "ALTA"],
        channel_name="No Risk No Gain - Robôs Para Day Trade",
        video_ids=["saziFu7u_mA", "NJF-d3pilRI"],
        video_titles=[
            "Como Programar um Robô BANDAS DE BOLLINGER no ProfitChart [PASSO A PASSO]",
            "Como Criar um ROBÔ Scalper de SALDO DE AGRESSÃO no Profit",
        ],
        thesis=(
            "Captura o retorno elástico à média quando um candle fecha fora da Banda de Bollinger (2 desvios) "
            "e o candle seguinte fecha dentro da banda confirmando exaustão vendedora ou compradora."
        ),
        default_params={"bb_period": 20, "bb_std": 2.0, "stop_atr_mult": 1.8, "max_hold_bars": 8},
        param_grid={
            "bb_period": [14, 20],
            "bb_std": [1.7, 2.0, 2.3],
            "stop_atr_mult": [1.5, 2.2],
        },
    ),
    BotSpecification(
        bot_id="NRNG-010",
        name="Robô Golden Hour / 1º Candle Range Breaker + FVG",
        family="BREAKOUT",
        preferred_regimes=["ALTA", "BAIXA"],
        channel_name="No Risk No Gain - Robôs Para Day Trade",
        video_ids=["I0IVhZ2MVBg", "d0hPQ2FUwuY", "3-dknLPG0wQ"],
        video_titles=[
            "74% WIN RATE TRADING ONLY THE FIRST CANDLE OF THE DAY!",
            "1H POR DIA: O ROBÔ QUE DOBROU O CAPITAL EM 1 ANO? | ROBÔ GOLDEN HOUR",
            "This 5m SETUP works every day! I turned it into a Day Trade ROBOT!",
        ],
        thesis=(
            "Opera o rompimento da faixa inicial / consolidação curta combinado com Fair Value Gap (FVG - "
            "desequilíbrio de 3 barras) com alvo curto/médio de alta taxa de acerto."
        ),
        default_params={"box_bars": 4, "target_atr_mult": 1.0, "stop_atr_mult": 1.6, "max_hold_bars": 6},
        param_grid={
            "box_bars": [3, 5, 8],
            "target_atr_mult": [0.8, 1.1, 1.5],
            "stop_atr_mult": [1.3, 1.8],
        },
    ),
]


def get_bot_by_id(bot_id: str) -> BotSpecification:
    for b in NORISKNOGAIN_BOTS:
        if b.bot_id == bot_id:
            return b
    raise KeyError(f"Robô não encontrado: {bot_id}")
