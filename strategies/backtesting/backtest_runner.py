"""
Runner Central de Backtests para a Base de Conhecimento.
Permite executar simulações históricas parametrizadas tanto via CLI quanto via Web API.
"""

import os
import sys
import json
import argparse
from typing import Dict, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from strategies.backtesting.option_backtester import OptionBacktester

class BacktestRunner:
    def __init__(self):
        self.option_backtester = OptionBacktester()

    def run(self, strategy_id: str = "STRAT-YT-001", symbol: str = "VALE3.SA", start_date: str = "2016-01-01", initial_capital: float = 100000.0) -> Dict[str, Any]:
        if strategy_id == "STRAT-YT-001":
            return self.option_backtester.run_backtest(
                symbol=symbol,
                initial_capital=initial_capital,
                start_date=start_date
            )
        else:
            return {"error": f"Estratégia {strategy_id} ainda não possui motor de backtest dedicado"}

if __name__ == "__main__":
    runner = BacktestRunner()
    res = runner.run("STRAT-YT-001", "PETR4.SA", start_date="2018-01-01")
    print(f"Backtest PETR4: Multiple={res.get('strategy_multiple')}x vs CDI={res.get('cdi_multiple')}x")
