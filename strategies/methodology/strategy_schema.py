"""
Modelos de Dados Padronizados para o Módulo de Estratégias.
Garante que todas as estratégias registradas possuam regras, parâmetros,
métricas estatísticas e diretrizes de risco uniformes.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class StrategyMetrics(BaseModel):
    win_rate_pct: float = Field(0.0, description="Taxa de acerto em porcentagem (0 a 100)")
    payoff_ratio: float = Field(0.0, description="Razão Média de Ganho / Média de Perda")
    profit_factor: float = Field(0.0, description="Lucro Bruto / Prejuízo Bruto")
    expectancy_per_trade: float = Field(0.0, description="Esperança matemática monetária ou percentual por trade")
    max_drawdown_pct: float = Field(0.0, description="Drawdown máximo histórico percentual")
    total_trades_tested: int = Field(0, description="Número de operações avaliadas no histórico")
    sharpe_ratio: Optional[float] = Field(None, description="Índice Sharpe anualizado")
    historical_period: str = Field("N/A", description="Período do backtest/avaliação (ex: 2009-2026)")

class EntryRule(BaseModel):
    indicator: str
    condition: str
    target_value: str
    timeframe: str = "Daily"

class ExitRule(BaseModel):
    type: str  # TakeProfit, StopLoss, Expiration, TrailingStop
    rule: str
    value: Optional[str] = None

class RiskParameters(BaseModel):
    max_capital_allocation_pct: float = Field(10.0, description="Alocação máxima do patrimônio nesta estratégia")
    risk_reward_minimum: float = Field(1.5, description="Relação mínima risco/retorno esperada")
    collateral_type: str = Field("CDI_100", description="Tipo de garantia: CDI, Caixa, Ações")
    stop_loss_policy: str = Field("None", description="Política de stop: Fixo, Trailing, Vencimento")

class StrategySpecification(BaseModel):
    id: str = Field(..., description="Identificador único (ex: STRAT-YT-001, STRAT-TF-001)")
    name: str = Field(..., description="Nome descritivo da estratégia")
    source_type: str = Field(..., description="Tipo de fonte: YouTube, TradingFloor, Academic, Proprietary")
    author_or_channel: str = Field(..., description="Autor, canal ou trader responsável")
    source_url: Optional[str] = Field(None, description="URL original do vídeo ou fonte")
    asset_class: str = Field(..., description="Opções, Ações, Futuros B3, Cripto, Forex")
    underlying_symbols: List[str] = Field(default_factory=list, description="Ativos operados (ex: VALE3, PETR4, WINFUT)")
    summary: str = Field(..., description="Resumo executivo da tese e vantagem estatística (edge)")
    market_regime_favorable: List[str] = Field(default_factory=list, description="Regimes favoráveis: Lateral, Alta Moderada, Alta Volatilidade")
    market_regime_unfavorable: List[str] = Field(default_factory=list, description="Regimes desfavoráveis: Crash severo, Tendência forte de baixa")
    
    entry_rules: List[EntryRule] = Field(default_factory=list)
    exit_rules: List[ExitRule] = Field(default_factory=list)
    risk_parameters: RiskParameters = Field(default_factory=RiskParameters)
    metrics: StrategyMetrics = Field(default_factory=StrategyMetrics)
    
    status: str = Field("ACTIVE", description="ACTIVE, IN_EVALUATION, ARCHIVED")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
