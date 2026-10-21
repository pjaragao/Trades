"""
Configurações centrais do módulo Robo Lab (Fábrica de Robôs, Backtest Paramétrico e Sentimento de Mercado).
"""

from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
ROBO_LAB_DIR = Path(__file__).resolve().parent
DATA_DIR = ROBO_LAB_DIR / "data"
CHANNELS_DIR = DATA_DIR / "channels"
REPORTS_DIR = DATA_DIR / "reports"
MARKET_CACHE_DB = DATA_DIR / "market_cache.db"
LEGACY_MARKET_DB = ROOT_DIR / "strategies" / "data_cache" / "market_prices.db"

DEFAULT_SYMBOLS_B3 = [
    "WIN$N",       # Mini Índice Futuro B3
    "WDO$N",       # Mini Dólar Futuro B3
    "^BVSP",       # Índice Ibovespa à Vista
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
    "WIN$N": "Mini Índice Futuro (WIN$N - B3/MT5)",
    "WDO$N": "Mini Dólar Futuro (WDO$N - B3/MT5)",
    "^BVSP": "Ibovespa (Índice à Vista)",
    "BRL=X": "Dólar Comercial (USD/BRL Spot)",
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
}

SUPPORTED_TIMEFRAMES = [
    {"code": "1m", "label": "1 Minuto (Ultra Scalp WIN/WDO)", "category": "DAY_TRADE_SCALP", "bars_per_day": 420},
    {"code": "2m", "label": "2 Minutos (Scalp Clássico WIN/WDO)", "category": "DAY_TRADE_SCALP", "bars_per_day": 210},
    {"code": "3m", "label": "3 Minutos (Day Trade Rápido WIN/WDO)", "category": "DAY_TRADE_SCALP", "bars_per_day": 140},
    {"code": "5m", "label": "5 Minutos (Day Trade Clássico)", "category": "DAY_TRADE", "bars_per_day": 84},
    {"code": "15m", "label": "15 Minutos (Day Trade Intraday)", "category": "DAY_TRADE", "bars_per_day": 28},
    {"code": "60m", "label": "60 Minutos (Day Trade / Intra-Swing)", "category": "HYBRID", "bars_per_day": 7},
    {"code": "1d", "label": "Diário (Swing Trade)", "category": "SWING_TRADE", "bars_per_day": 1},
    {"code": "1wk", "label": "Semanal (Position / Macro Swing)", "category": "SWING_TRADE", "bars_per_day": 0.2},
]

# Especificações reais dos Contratos Futuros da B3 (Mini-Índice e Mini-Dólar)
FUTURES_SPECS: Dict[str, Dict[str, Any]] = {
    "WIN$N": {
        "name": "Mini Índice Ibovespa Futuro",
        "tick_size": 5.0,             # 5 pontos por tick
        "point_value_brl": 0.20,      # R$ 0,20 por ponto (1 tick = R$ 1,00)
        "fee_pct_per_side": 0.00002,  # ~R$ 0,50 por contrato num nocional de ~R$ 26.000
        "slippage_pct_per_side": 0.00004, # ~5 pontos (1 tick) de slippage médio
        "margin_per_contract_brl": 2500.0, # Margem/alocação recomendada por mini-contrato
    },
    "WDO$N": {
        "name": "Mini Dólar Comercial Futuro",
        "tick_size": 0.5,             # 0,5 ponto por tick
        "point_value_brl": 10.0,      # R$ 10,00 por ponto (1 tick = R$ 5,00)
        "fee_pct_per_side": 0.000025, # ~R$ 1,20 por contrato num nocional de ~R$ 55.000
        "slippage_pct_per_side": 0.00009, # ~0,5 ponto (1 tick) de slippage médio
        "margin_per_contract_brl": 3000.0, # Margem/alocação recomendada por mini-contrato
    },
}

BACKTEST_DEFAULTS = {
    "initial_capital": 100000.0,
    "position_size_pct": 0.25,     # 25% do capital por operação
    "b3_fee_pct_per_side": 0.0003, # 0.03% emolumentos B3 por ponta (ações à vista)
    "slippage_pct_per_side": 0.0005, # 0.05% slippage médio por ponta (ações à vista)
    "risk_free_annual": 0.1075,    # Selic/CDI referência
}
