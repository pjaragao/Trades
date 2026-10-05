"""
Screener e Construtor de Travas de Alta com Call (Bull Call Spread - STRAT-YT-002).
Varre ativos líquidos da B3 (PETR4, VALE3, BBAS3, BOVA11, ITUB4),
identifica Call Comprada ATM e Call Vendida OTM na resistência,
calculando custo líquido, lucro máximo (alvo 2x a 3x), breakeven e ROI projetado.
"""

import os
import sys
import math
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from strategies.backtesting.price_data_feed import PriceDataFeed

CALL_MONTH_LETTERS = "ABCDEFGHIJKL"

DEFAULT_SPREAD_WATCHLIST = [
    {"symbol": "PETR4.SA", "name": "Petrobras PN", "clean_ticker": "PETR4", "iv": 0.32},
    {"symbol": "VALE3.SA", "name": "Vale S.A.", "clean_ticker": "VALE3", "iv": 0.30},
    {"symbol": "BBAS3.SA", "name": "Banco do Brasil ON", "clean_ticker": "BBAS3", "iv": 0.25},
    {"symbol": "BOVA11.SA", "name": "ETF Ibovespa", "clean_ticker": "BOVA11", "iv": 0.20},
    {"symbol": "ITUB4.SA", "name": "Itaú Unibanco PN", "clean_ticker": "ITUB4", "iv": 0.22}
]

class BullSpreadScreener:
    def __init__(self):
        self.feed = PriceDataFeed()

    def get_expiration_info(self) -> Dict[str, Any]:
        """Calcula a 3ª sexta-feira do mês de vencimento mais próximo."""
        today = datetime.now()
        year = today.year
        month = today.month

        def third_friday(y, m):
            d1 = datetime(y, m, 1)
            days_to_friday = (4 - d1.weekday()) % 7
            first_friday = d1 + timedelta(days=days_to_friday)
            return first_friday + timedelta(weeks=2)

        exp = third_friday(year, month)
        if today >= exp - timedelta(days=2):
            if month == 12:
                exp = third_friday(year + 1, 1)
                exp_month = 1
            else:
                exp = third_friday(year, month + 1)
                exp_month = month + 1
        else:
            exp_month = month

        month_char = CALL_MONTH_LETTERS[exp_month - 1]
        days_to_exp = max((exp - today).days, 1)
        return {
            "date": exp.strftime("%d/%m/%Y"),
            "month_char": month_char,
            "days_to_exp": days_to_exp
        }

    def _approx_call_price(self, spot: float, strike: float, days: int, iv: float) -> float:
        """Aproximação Black-Scholes simplificada para prêmio de Call."""
        t = max(days, 1) / 365.0
        r = 0.1175 # taxa livre de risco SELIC/CDI
        vol = max(iv, 0.15)
        
        d1 = (math.log(spot / strike) + (r + 0.5 * vol**2) * t) / (vol * math.sqrt(t))
        d2 = d1 - vol * math.sqrt(t)

        def norm_cdf(x):
            return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

        call_val = spot * norm_cdf(d1) - strike * math.exp(-r * t) * norm_cdf(d2)
        return max(round(call_val, 2), 0.05)

    def scan_symbol(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sym = item["symbol"]
        clean = item["clean_ticker"]
        df = self.feed.get_daily_prices(sym, start_date=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"), force_refresh=False)
        if df.empty or len(df) < 15:
            return None

        current_spot = float(df["close"].iloc[-1])
        # ATR-14
        df["tr"] = df[["high", "close"]].max(axis=1) - df[["low", "close"]].min(axis=1)
        atr14 = float(df["tr"].rolling(14).mean().iloc[-1])
        exp_info = self.get_expiration_info()

        # Call Longa (ATM)
        strike_long = round(current_spot, 1)
        # Call Curta (OTM no alvo de resistência: ~1 ATR acima ou 5%)
        spread_dist = max(round(atr14 * 1.1, 1), round(current_spot * 0.05, 1))
        strike_short = round(strike_long + spread_dist, 1)

        prem_long = self._approx_call_price(current_spot, strike_long, exp_info["days_to_exp"], item["iv"])
        prem_short = self._approx_call_price(current_spot, strike_short, exp_info["days_to_exp"], item["iv"])

        cost_net = max(round(prem_long - prem_short, 2), 0.10)
        spread_width = round(strike_short - strike_long, 2)
        max_profit = max(round(spread_width - cost_net, 2), 0.10)
        breakeven = round(strike_long + cost_net, 2)
        roi_pct = round((max_profit / cost_net) * 100.0, 1)
        payoff_ratio = round(max_profit / cost_net, 2)

        # Tickers sugeridos B3
        strike_int_long = int(strike_long * 10)
        strike_int_short = int(strike_short * 10)
        ticker_long = f"{clean[:4]}{exp_info['month_char']}{strike_int_long}"
        ticker_short = f"{clean[:4]}{exp_info['month_char']}{strike_int_short}"

        return {
            "symbol": sym,
            "ticker": clean,
            "name": item["name"],
            "current_spot": round(current_spot, 2),
            "atr14": round(atr14, 2),
            "expiration_date": exp_info["date"],
            "days_to_exp": exp_info["days_to_exp"],
            "strike_long": strike_long,
            "strike_short": strike_short,
            "ticker_long": ticker_long,
            "ticker_short": ticker_short,
            "prem_long": prem_long,
            "prem_short": prem_short,
            "cost_net": cost_net,
            "max_profit": max_profit,
            "breakeven": breakeven,
            "roi_pct": roi_pct,
            "payoff_ratio": payoff_ratio,
            "alvo_pct": round(((strike_short - current_spot) / current_spot) * 100, 1),
            "strategy_id": "STRAT-YT-002",
            "strategy_name": "Trava de Alta com Call (Bull Spread)"
        }

    def scan_all(self) -> List[Dict[str, Any]]:
        results = []
        for item in DEFAULT_SPREAD_WATCHLIST:
            try:
                res = self.scan_symbol(item)
                if res:
                    results.append(res)
            except Exception as e:
                print(f"Erro ao escanear {item['symbol']}: {e}")
        return results

if __name__ == "__main__":
    screener = BullSpreadScreener()
    opps = screener.scan_all()
    print(f"Bull Spread Screener: {len(opps)} oportunidades encontradas")
    for o in opps:
        print(f"{o['ticker']} -> Long {o['ticker_long']} (R${o['strike_long']}) / Short {o['ticker_short']} (R${o['strike_short']}) | Custo: R${o['cost_net']} | Lucro Max: R${o['max_profit']} (ROI: {o['roi_pct']}%)")
