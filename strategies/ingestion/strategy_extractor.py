"""
Extrator de Regras e Sintetizador Estruturado a partir de Transcrições de Vídeos.
Analisa o texto de transcrições do YouTube, identifica ativos, indicadores,
parâmetros de entrada e saída, e formata uma especificação de estratégia.
"""

import os
import re
import json
from typing import Dict, Any, List

class StrategyExtractor:
    def __init__(self):
        self.asset_patterns = [
            r"\b(VALE3|VALE|PETR4|PETROBRAS|ITUB4|ITAU|BBAS3|B3SA3|BOVA11|WINFUT|WDOFUT|IBOV|S&P|SP500)\b"
        ]
        self.indicator_patterns = [
            r"\b(ATR|Mdia Mvel|EMA|SMA|RSI|IFR|MACD|Bandas de Bollinger|Delta|Volume)\b",
            r"\b(ATR|Media Movel|EMA|SMA|RSI|IFR|MACD|Bandas de Bollinger|Delta|Volume)\b"
        ]

    def extract_keywords_and_context(self, transcript_text: str) -> Dict[str, Any]:
        """Varre o texto da transcrição e extrai referências operacionais."""
        assets_found = set()
        for p in self.asset_patterns:
            matches = re.findall(p, transcript_text, re.IGNORECASE)
            for m in matches:
                assets_found.add(m.upper())

        indicators_found = set()
        for p in self.indicator_patterns:
            matches = re.findall(p, transcript_text, re.IGNORECASE)
            for m in matches:
                indicators_found.add(m.upper())

        # Procura números associados a delta ou ATR
        atr_matches = re.findall(r"atr\s*(?:de)?\s*(\d+)", transcript_text, re.IGNORECASE)
        delta_matches = re.findall(r"delta\s*(?:de)?\s*(0[,\.]\d+|\d+)", transcript_text, re.IGNORECASE)

        return {
            "assets_referenced": list(assets_found),
            "indicators_referenced": list(indicators_found),
            "atr_periods": list(set(atr_matches)),
            "deltas": list(set(delta_matches))
        }

if __name__ == "__main__":
    extractor = StrategyExtractor()
    with open("strategies/knowledge_base/youtube/jimmy_carvalho/transcript_L48NBs21q6g.txt", "r", encoding="utf-8") as f:
        text = f.read()
    res = extractor.extract_keywords_and_context(text)
    print("Extração de termos do vídeo L48NBs21q6g:")
    print(json.dumps(res, indent=2, ensure_ascii=False))
