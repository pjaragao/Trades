"""
Configurações centrais do módulo Robo Lab (Fábrica de Robôs, Backtest Paramétrico e Sentimento de Mercado).
"""

from pathlib import Path
from typing import Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
ROBO_LAB_DIR = Path(__file__).resolve().parent
DATA_DIR = ROBO_LAB_DIR / "data"
CHANNELS_DIR = DATA_DIR / "channels"
REPORTS_DIR = DATA_DIR / "reports"
MARKET_CACHE_DB = DATA_DIR / "market_cache.db"
LEGACY_MARKET_DB = ROOT_DIR / "strategies" / "data_cache" / "market_prices.db"

DEFAULT_SYMBOLS_B3 = [
    "^BVSP",       # Índice Ibovespa
    "BOVA11.SA",   # ETF Ibovespa
    "VALE3.SA",    # Vale
    "PETR4.SA",    # Petrobras
    "ITUB4.SA",    # Itaú Unibanco
    "BBAS3.SA",    # Banco do Brasil
    "BBDC4.SA",    # Bradesco
    "WEGE3.SA",    # WEG
    "PRIO3.SA",    # Prio
    "GGBR4.SA",    # Gerdau
    "B3SA3.SA",    # B3
    "SUZB3.SA",    # Suzano
    "RENT3.SA",    # Localiza
]

SYMBOL_LABELS: Dict[str, str] = {
    "^BVSP": "Ibovespa (Índice / Proxy WIN)",
    "BOVA11.SA": "BOVA11 (ETF Ibovespa)",
    "VALE3.SA": "VALE3 (Vale ON)",
    "PETR4.SA": "PETR4 (Petrobras PN)",
    "ITUB4.SA": "ITUB4 (Itaú PN)",
    "BBAS3.SA": "BBAS3 (Banco do Brasil ON)",
    "BBDC4.SA": "BBDC4 (Bradesco PN)",
    "WEGE3.SA": "WEGE3 (WEG ON)",
    "PRIO3.SA": "PRIO3 (PRIO ON)",
    "GGBR4.SA": "GGBR4 (Gerdau PN)",
    "B3SA3.SA": "B3SA3 (B3 ON)",
    "SUZB3.SA": "SUZB3 (Suzano ON)",
    "RENT3.SA": "RENT3 (Localiza ON)",
    "WIN$N": "Mini Índice Futuro (MT5)",
    "WDO$N": "Mini Dólar Futuro (MT5)",
}

SUPPORTED_TIMEFRAMES = [
    {"code": "5m", "label": "5 Minutos (Day Trade Scalp/Curto)", "category": "DAY_TRADE", "bars_per_day": 84},
    {"code": "15m", "label": "15 Minutos (Day Trade Intraday)", "category": "DAY_TRADE", "bars_per_day": 28},
    {"code": "60m", "label": "60 Minutos (Day Trade / Intra-Swing)", "category": "HYBRID", "bars_per_day": 7},
    {"code": "1d", "label": "Diário (Swing Trade)", "category": "SWING_TRADE", "bars_per_day": 1},
    {"code": "1wk", "label": "Semanal (Position / Macro Swing)", "category": "SWING_TRADE", "bars_per_day": 0.2},
]

BACKTEST_DEFAULTS = {
    "initial_capital": 100000.0,
    "position_size_pct": 0.25,     # 25% do capital por operação
    "b3_fee_pct_per_side": 0.0003, # 0.03% emolumentos B3 por ponta
    "slippage_pct_per_side": 0.0005, # 0.05% slippage médio por ponta
    "risk_free_annual": 0.1075,    # Selic/CDI referência
}
