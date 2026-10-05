"""
Scanner Central Multi-Estratégia.
Unifica a execução de screeners para todas as estratégias ativas da Base de Conhecimento,
retornando oportunidades em tempo real para busca e execução de novos trades.
"""

import os
import sys
import json
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from strategies.screeners.put_selling_screener import PutSellingScreener
from strategies.screeners.bull_spread_screener import BullSpreadScreener
from strategies.screeners.swing_trade_screener import SwingTradeScreener
from strategies.screeners.covered_call_screener import CoveredCallScreener
from strategies.screeners.futures_levels_engine import FuturesLevelsEngine
from strategies.screeners.portfolio_allocator import PortfolioAllocator

class MarketScreenerService:
    def __init__(self, catalog_path: str = "strategies/knowledge_base/catalog.json", cdi_annual: Optional[float] = None):
        # CDI atual (BCB) quando informado; os módulos mantêm 11,75% só como padrão de linha de comando
        cdi = cdi_annual if cdi_annual is not None else 0.1175
        self.catalog_path = catalog_path
        self.put_screener = PutSellingScreener(cdi_annual=cdi)
        self.bull_screener = BullSpreadScreener(cdi_annual=cdi)
        self.swing_screener = SwingTradeScreener()
        self.covered_screener = CoveredCallScreener(cdi_annual=cdi)
        self.futures_engine = FuturesLevelsEngine()
        self.allocator = PortfolioAllocator(cdi_annual=cdi)

    def get_catalog(self) -> Dict[str, Any]:
        if os.path.exists(self.catalog_path):
            with open(self.catalog_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"strategies": []}

    def get_strategy_screener_data(self, strategy_id: str, target_cycle: str = "current") -> Dict[str, Any]:
        """Retorna oportunidades e parâmetros calculados para uma estratégia específica."""
        strat_id = strategy_id.upper().strip()

        if strat_id == "STRAT-YT-001":
            opps = self.put_screener.scan_all(target_cycle=target_cycle)
            exp_date = self.put_screener.get_next_expiration_date(target_cycle=target_cycle)
            return {
                "strategy_id": "STRAT-YT-001",
                "strategy_name": "Venda de Put OTM no Nível -1 ATR (Renda 300% CDI)",
                "type": "put_selling",
                "expiration_date": exp_date.strftime("%d/%m/%Y"),
                "target_cycle": target_cycle,
                "total_opportunities": len(opps),
                "items": opps
            }


        elif strat_id == "STRAT-YT-002":
            opps = self.bull_screener.scan_all()
            exp_info = self.bull_screener.get_expiration_info()
            return {
                "strategy_id": "STRAT-YT-002",
                "strategy_name": "Trava de Alta com Call (Bull Call Spread)",
                "type": "bull_spread",
                "expiration_date": exp_info["date"],
                "total_opportunities": len(opps),
                "items": opps
            }

        elif strat_id in ["STRAT-YT-003", "STRAT-TF-003"]:
            opps = self.swing_screener.scan_all()
            actionable = [o for o in opps if o["is_actionable"]]
            return {
                "strategy_id": strat_id,
                "strategy_name": "Swing Trade de Alta Consistência (72% Win Rate)",
                "type": "swing_trade",
                "total_opportunities": len(opps),
                "actionable_count": len(actionable),
                "items": opps
            }

        elif strat_id == "STRAT-YT-004":
            opps = self.covered_screener.scan_all()
            exp_info = self.covered_screener.get_expiration_info()
            return {
                "strategy_id": "STRAT-YT-004",
                "strategy_name": "Renda Mensal com Venda Coberta & Cash-Secured Put",
                "type": "covered_call",
                "expiration_date": exp_info["date"],
                "total_opportunities": len(opps),
                "items": opps
            }

        elif strat_id in ["STRAT-TF-001", "STRAT-TF-002", "STRAT-TF-006"]:
            levels = self.futures_engine.scan_all()
            return {
                "strategy_id": strat_id,
                "strategy_name": "Níveis de Day Trade & Scalp em Futuros B3",
                "type": "futures_levels",
                "total_opportunities": len(levels),
                "items": levels
            }

        elif strat_id == "STRAT-YT-007":
            alloc = self.allocator.calculate_allocation(100000.0)
            return {
                "strategy_id": "STRAT-YT-007",
                "strategy_name": "Alocação Híbrida de R$ 100k com Dividendos Sintéticos",
                "type": "portfolio_allocation",
                "total_opportunities": 1,
                "items": [alloc]
            }

        # Fallback genérico para outras estratégias
        return {
            "strategy_id": strat_id,
            "strategy_name": "Estratégia da Base de Conhecimento",
            "type": "generic",
            "total_opportunities": 0,
            "items": []
        }

    def run_all_screeners(self, target_cycle: str = "current") -> Dict[str, Any]:
        catalog = self.get_catalog()
        active_strats = catalog.get("strategies", [])

        # Executa os principais screeners
        put_opps = self.put_screener.scan_all(target_cycle=target_cycle)
        bull_opps = self.bull_screener.scan_all()
        swing_opps = self.swing_screener.scan_all()
        covered_opps = self.covered_screener.scan_all()
        futures_levels = self.futures_engine.scan_all()
        alloc = self.allocator.calculate_allocation(100000.0)

        total_opps = len(put_opps) + len(bull_opps) + len(swing_opps) + len(covered_opps)
        exp_date_put = self.put_screener.get_next_expiration_date(target_cycle=target_cycle)

        return {
            "total_strategies_monitored": len(active_strats),
            "opportunities_count": total_opps,
            "strategies_summary": active_strats,
            "target_cycle": target_cycle,
            "opportunities": {
                "STRAT-YT-001": {
                    "strategy_name": "Venda de Put OTM no Nível -1 ATR (Renda 300% CDI)",
                    "asset_class": "Opções B3",
                    "expiration_date": exp_date_put.strftime("%d/%m/%Y"),
                    "target_cycle": target_cycle,
                    "candidates": put_opps
                },

                "STRAT-YT-002": {
                    "strategy_name": "Trava de Alta com Call (Bull Call Spread)",
                    "asset_class": "Opções B3",
                    "candidates": bull_opps
                },
                "STRAT-YT-003": {
                    "strategy_name": "Swing Trade de Alta Consistência (72% Acerto)",
                    "asset_class": "Ações B3",
                    "candidates": swing_opps
                },
                "STRAT-YT-004": {
                    "strategy_name": "Venda Coberta & Dividendos Sintéticos",
                    "asset_class": "Opções Blue Chips",
                    "candidates": covered_opps
                },
                "STRAT-TF-001": {
                    "strategy_name": "Níveis de Day Trade & Scalp em Futuros B3",
                    "asset_class": "Futuros B3",
                    "candidates": futures_levels
                },
                "STRAT-YT-007": {
                    "strategy_name": "Alocação Híbrida de R$ 100k com Dividendos Sintéticos",
                    "asset_class": "Multi-Ativos",
                    "candidates": [alloc]
                }
            }
        }

if __name__ == "__main__":
    service = MarketScreenerService()
    report = service.run_all_screeners()
    print("Screener centralizado multi-estratégia executado!")
    print(f"Total de oportunidades: {report['opportunities_count']}")
