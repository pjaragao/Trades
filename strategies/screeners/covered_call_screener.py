"""
Calculadora e Screener de Venda Coberta & Dividendos Sintéticos (STRAT-YT-004).
Estratégia para rentabilizar custódia de Blue Chips pagadoras de dividendos na B3.
Calcula a Call OTM ideal para venda, o dividendo sintético mensal gerado,
a taxa de proteção contra quedas e o retorno total caso a ação seja exercida no strike.
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

COVERED_CALL_WATCHLIST = [
    {"symbol": "PETR4.SA", "clean": "PETR4", "name": "Petrobras PN", "div_yield": 0.14, "iv": 0.32},
    {"symbol": "VALE3.SA", "clean": "VALE3", "name": "Vale S.A.", "div_yield": 0.08, "iv": 0.30},
    {"symbol": "BBAS3.SA", "clean": "BBAS3", "name": "Banco do Brasil ON", "div_yield": 0.09, "iv": 0.25},
    {"symbol": "ITUB4.SA", "clean": "ITUB4", "name": "Itaú Unibanco PN", "div_yield": 0.07, "iv": 0.22},
    {"symbol": "B3SA3.SA", "clean": "B3SA3", "name": "B3 S.A.", "div_yield": 0.06, "iv": 0.26}
]

class CoveredCallScreener:
    def __init__(self, cdi_annual: float = 0.1175):
        self.feed = PriceDataFeed()
        self.cdi_annual = cdi_annual

    def get_expiration_info(self, target_cycle: str = "auto") -> Dict[str, Any]:
        today = datetime.now()
        year = today.year
        month = today.month

        def third_friday(y, m):
            d1 = datetime(y, m, 1)
            days = (4 - d1.weekday()) % 7
            return d1 + timedelta(days=days, weeks=2)

        exp = third_friday(year, month)
        # Se faltam 5 dias ou menos para o vencimento atual (semana de vencimento), ou se target_cycle=='next', mira no ciclo mensal seguinte
        if target_cycle == "next" or (target_cycle == "auto" and (exp - today).days <= 5) or today >= exp - timedelta(days=2):
            exp_month = 1 if month == 12 else month + 1
            exp_year = year + 1 if month == 12 else year
            exp = third_friday(exp_year, exp_month)
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
        t = max(days, 1) / 365.0
        r = self.cdi_annual
        vol = max(iv, 0.15)
        d1 = (math.log(spot / strike) + (r + 0.5 * vol**2) * t) / (vol * math.sqrt(t))
        d2 = d1 - vol * math.sqrt(t)

        def norm_cdf(x):
            return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

        call_val = spot * norm_cdf(d1) - strike * math.exp(-r * t) * norm_cdf(d2)
        return max(round(call_val, 2), 0.15)

    def scan_symbol(self, item: Dict[str, Any], target_cycle: str = "auto") -> Optional[Dict[str, Any]]:
        sym = item["symbol"]
        clean = item["clean"]
        df = self.feed.get_daily_prices(sym, start_date=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"), force_refresh=False)
        if df.empty or len(df) < 15:
            return None

        spot = float(df["close"].iloc[-1])
        exp = self.get_expiration_info(target_cycle=target_cycle)

        # Strike OTM moderado: ~2.5% a 4.0% acima do preço atual para permitir valorização
        strike = round(spot * 1.03, 1)
        premium = self._approx_call_price(spot, strike, exp["days_to_exp"], item["iv"])

        # Rendimento da opção (período e mensal normalizado para 30 dias)
        period_return_pct = round((premium / spot) * 100.0, 2)
        factor_monthly = (30.0 / exp["days_to_exp"]) if exp["days_to_exp"] > 0 else 1.0
        monthly_return_pct = round(period_return_pct * factor_monthly, 2) if exp["days_to_exp"] < 20 else period_return_pct
        annualized_return_pct = round(monthly_return_pct * 12.0, 2)

        # CDI Base: 11,75% a.a. -> CDI Mensal: 0,93% a.m.
        cdi_base_annual_pct = round(self.cdi_annual * 100.0, 2) # 11.75%
        cdi_monthly_pct = round(((1.0 + self.cdi_annual) ** (1.0 / 12.0) - 1.0) * 100.0, 2) # 0.93%
        cdi_ratio_pct = round((monthly_return_pct / cdi_monthly_pct) * 100.0, 0)

        # Taxa de Proteção contra Queda
        downside_protection_pct = monthly_return_pct

        # Retorno Máximo se Exercido (Ganho de capital + Prêmio)
        capital_gain_pct = ((strike - spot) / spot) * 100.0
        total_if_exercised_pct = round(capital_gain_pct + monthly_return_pct, 2)

        strike_int = int(strike * 10)
        option_ticker = f"{clean[:4]}{exp['month_char']}{strike_int}"

        return {
            "symbol": sym,
            "ticker": clean,
            "name": item["name"],
            "current_spot": round(spot, 2),
            "strike": strike,
            "option_ticker": option_ticker,
            "premium": premium,
            "expiration_date": exp["date"],
            "days_to_exp": exp["days_to_exp"],
            "monthly_yield_pct": monthly_return_pct,
            "annualized_yield_pct": annualized_return_pct,
            "cdi_annual_pct": cdi_base_annual_pct,
            "cdi_monthly_pct": cdi_monthly_pct,
            "cdi_ratio_pct": cdi_ratio_pct,
            "downside_protection_pct": downside_protection_pct,
            "total_if_exercised_pct": total_if_exercised_pct,
            "income_per_1000_shares": round(premium * 1000, 2),
            "strategy_id": "STRAT-YT-004",
            "strategy_name": "Renda Mensal com Venda Coberta (Dividendos Sintéticos)"
        }

    def scan_all(self, target_cycle: str = "auto") -> List[Dict[str, Any]]:
        results = []
        for item in COVERED_CALL_WATCHLIST:
            try:
                res = self.scan_symbol(item, target_cycle=target_cycle)
                if res:
                    results.append(res)
            except Exception as e:
                print(f"Erro ao escanear {item['symbol']}: {e}")
        return results

if __name__ == "__main__":
    screener = CoveredCallScreener()
    opps = screener.scan_all()
    print(f"Covered Call Screener: {len(opps)} oportunidades encontradas")
    for o in opps:
        print(f"{o['ticker']} (R${o['current_spot']}) -> Vender {o['option_ticker']} (Strike R${o['strike']}) | Prêmio: R${o['premium']} ({o['monthly_yield_pct']}%/mês = {o['cdi_ratio_pct']}% do CDI) | Renda p/ 1.000 ações: R${o['income_per_1000_shares']}")
