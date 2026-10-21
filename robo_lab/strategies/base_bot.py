"""
Estrutura Base de Robôs de Trade Paramétricos e Sistema Universal de Filtros.
Permite acoplar qualquer combinação de filtros (Tendência, Volume, Volatilidade, Horário, Direção)
a qualquer robô do catálogo para exaurir o espaço de parâmetros em múltiplos timeframes.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class FilterConfig:
    trend_filter: str = "none"        # none, ema200_align, ema20_50_align, adx_trend_gt20, adx_lateral_lt22, er_low_noise, er_high_trend
    volume_filter: str = "none"       # none, vol_above_avg, vol_spike_1_3x, vol_calm_lt1_2x
    volatility_filter: str = "none"   # none, atr_expanding, atr_contracting
    session_filter: str = "all_day"   # all_day, golden_hour_morning, afternoon_calm
    side_mode: str = "both"           # both, long_only, short_only

    def to_dict(self) -> Dict[str, str]:
        return {
            "trend_filter": self.trend_filter,
            "volume_filter": self.volume_filter,
            "volatility_filter": self.volatility_filter,
            "session_filter": self.session_filter,
            "side_mode": self.side_mode,
        }

    def label(self) -> str:
        parts = []
        if self.trend_filter != "none":
            parts.append(f"trend={self.trend_filter}")
        if self.volume_filter != "none":
            parts.append(f"vol={self.volume_filter}")
        if self.volatility_filter != "none":
            parts.append(f"atr={self.volatility_filter}")
        if self.session_filter != "all_day":
            parts.append(f"sess={self.session_filter}")
        if self.side_mode != "both":
            parts.append(f"side={self.side_mode}")
        return " | ".join(parts) if parts else "sem_filtros_extras"


def apply_universal_filters(
    df: pd.DataFrame,
    raw_entry_side: np.ndarray,
    filters: FilterConfig,
    timeframe: str = "1d",
) -> np.ndarray:
    """
    Recebe o vetor de sinais brutos de entrada (+1 para compra, -1 para venda, 0 neutro)
    e aplica os filtros universais configurados (tendência, volume, volatilidade, sessão e direção).
    """
    sig = raw_entry_side.astype(int).copy()
    n = len(df)
    if n == 0:
        return sig

    c = df["close"].to_numpy()
    ema20 = df["ema20"].to_numpy()
    ema50 = df["ema50"].to_numpy()
    ema200 = df["ema200"].to_numpy()
    adx = df["adx14"].to_numpy()
    er = df["efficiency_ratio"].to_numpy()
    vol_ratio = df["vol_ratio"].to_numpy()
    atr5 = df["atr5"].to_numpy()
    atr20 = df["atr20"].to_numpy()

    # 1. Filtro de Tendência / Regime
    tf = filters.trend_filter
    if tf == "ema200_align":
        sig = np.where((sig == 1) & (c < ema200), 0, sig)
        sig = np.where((sig == -1) & (c > ema200), 0, sig)
    elif tf == "ema20_50_align":
        sig = np.where((sig == 1) & (ema20 < ema50), 0, sig)
        sig = np.where((sig == -1) & (ema20 > ema50), 0, sig)
    elif tf == "adx_trend_gt20":
        sig = np.where(adx < 20.0, 0, sig)
    elif tf == "adx_lateral_lt22":
        sig = np.where(adx > 22.0, 0, sig)
    elif tf == "er_low_noise":
        sig = np.where(er > 0.30, 0, sig)
    elif tf == "er_high_trend":
        sig = np.where(er < 0.26, 0, sig)

    # 2. Filtro de Volume da Bolsa
    vf = filters.volume_filter
    if vf == "vol_above_avg":
        sig = np.where(vol_ratio < 0.95, 0, sig)
    elif vf == "vol_spike_1_3x":
        sig = np.where(vol_ratio < 1.25, 0, sig)
    elif vf == "vol_calm_lt1_2x":
        sig = np.where(vol_ratio > 1.25, 0, sig)

    # 3. Filtro de Volatilidade (ATR Curto vs Longo)
    volat = filters.volatility_filter
    if volat == "atr_expanding":
        sig = np.where(atr5 < atr20 * 0.98, 0, sig)
    elif volat == "atr_contracting":
        sig = np.where(atr5 > atr20 * 1.10, 0, sig)

    # 4. Filtro de Horário/Sessão (apenas para timeframes intraday)
    if timeframe in ("5m", "15m", "60m") and filters.session_filter != "all_day":
        hours = df.index.hour.to_numpy()
        if filters.session_filter == "golden_hour_morning":
            sig = np.where((hours < 10) | (hours >= 13), 0, sig)
        elif filters.session_filter == "afternoon_calm":
            sig = np.where((hours < 12) | (hours >= 16), 0, sig)

    # 5. Modo de Direção (Long+Short, Long Only, Short Only)
    if filters.side_mode == "long_only":
        sig = np.where(sig < 0, 0, sig)
    elif filters.side_mode == "short_only":
        sig = np.where(sig > 0, 0, sig)

    return sig


@dataclass
class BotSpecification:
    bot_id: str
    name: str
    family: str                       # MEAN_REVERSION, TREND_FOLLOWING, BREAKOUT, GRID_SCALP, PULLBACK
    preferred_regimes: List[str]      # ALTA, BAIXA, LATERAL
    channel_name: str
    video_ids: List[str]
    video_titles: List[str]
    thesis: str
    default_params: Dict[str, Any]
    param_grid: Dict[str, List[Any]]
    recommended_filters: List[FilterConfig] = field(default_factory=list)
