"""
Sincronizador e Minerador Automatizado de Trades do TradingFloor.
Pode ser acionado periodicamente ou via botão na interface web para recalcular
as métricas de consistência dos traders e detectar novos padrões.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from strategies.methodology.pattern_detector import TradePatternDetector

class TradingFloorExtractor:
    def __init__(self, db_path: str = "database/backtest_cache.db"):
        self.detector = TradePatternDetector(db_path=db_path)

    def refresh_patterns(self):
        print("Recalculando padrões quantitativos do TradingFloor...")
        traders, assets = self.detector.run_and_save()
        return {
            "success": True,
            "traders_analyzed": len(traders),
            "asset_classes_analyzed": len(assets)
        }

if __name__ == "__main__":
    extractor = TradingFloorExtractor()
    print(extractor.refresh_patterns())
