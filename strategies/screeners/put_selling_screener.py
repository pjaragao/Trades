"""
Screener de Mercado em Tempo Real para Estratégia de Opções:
Venda de Put OTM no Nível -1 ATR (STRAT-YT-001).
Varre as principais ações da B3 com mercado líquido de opções (VALE3, PETR4, ITUB4, BBAS3, B3SA3, BOVA11),
calcula o ATR-14 atual, determina os strikes recomendados (-1 ATR e -1.5 ATR)
e projeta o prêmio mensal e a taxa anualizada comparada ao CDI.
"""

import os
import sys
import math
import argparse
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from strategies.backtesting.price_data_feed import PriceDataFeed

DEFAULT_WATCHLIST = [
    {"symbol": "VALE3.SA", "name": "Vale S.A.", "type": "Mineração", "iv_approx": 0.30},
    {"symbol": "PETR4.SA", "name": "Petrobras PN", "type": "Óleo e Gás", "iv_approx": 0.33},
    {"symbol": "ITUB4.SA", "name": "Itaú Unibanco PN", "type": "Bancário", "iv_approx": 0.22},
    {"symbol": "BBAS3.SA", "name": "Banco do Brasil ON", "type": "Bancário", "iv_approx": 0.25},
    {"symbol": "B3SA3.SA", "name": "B3 S.A.", "type": "Financeiro", "iv_approx": 0.26},
    {"symbol": "BOVA11.SA", "name": "ETF Ibovespa", "type": "Índice", "iv_approx": 0.19}
]

class PutSellingScreener:
    def __init__(self, cdi_annual: float = 0.1175):
        self.feed = PriceDataFeed()
        self.cdi_annual = cdi_annual

    def get_next_expiration_date(self, target_cycle: str = "current") -> datetime:
        """
        Determina a terceira sexta-feira do mês de vencimento.
        Se target_cycle == 'next', busca o vencimento do mês seguinte (ciclo mensal completo).
        """
        today = datetime.now()
        year = today.year
        month = today.month

        def third_friday(y, m):
            d1 = datetime(y, m, 1)
            days_to_friday = (4 - d1.weekday()) % 7
            first_friday = d1 + timedelta(days=days_to_friday)
            return first_friday + timedelta(weeks=2)

        exp = third_friday(year, month)
        
        # Se já passou ou se faltam menos de 2 dias ou se foi pedido o próximo ciclo:
        if target_cycle == "next" or today >= exp or (exp - today).days <= 1:
            if month == 12:
                exp = third_friday(year + 1, 1)
            else:
                exp = third_friday(year, month + 1)
        return exp

    def scan_symbol(self, item: Dict[str, Any], target_cycle: str = "current") -> Optional[Dict[str, Any]]:
        sym = item["symbol"]
        df = self.feed.get_daily_prices(sym, start_date=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"), force_refresh=False)
        if df.empty or len(df) < 15:
            return None

        df.dropna(subset=["close", "high", "low"], inplace=True)
        if len(df) < 15:
            return None

        # Calcula ATR(14)
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)
        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        atr_series = tr.rolling(14).mean().dropna()
        if atr_series.empty:
            return None
        atr_14 = float(atr_series.iloc[-1])
        current_spot = float(close.iloc[-1])

        if math.isnan(current_spot) or math.isnan(atr_14) or current_spot <= 0 or atr_14 <= 0:
            return None

        # Strikes recomendados
        strike_std = round(current_spot - (1.0 * atr_14), 2)
        strike_cons = round(current_spot - (1.5 * atr_14), 2)

        exp_date = self.get_next_expiration_date(target_cycle=target_cycle)
        days_to_exp = max(1, (exp_date - datetime.now()).days)

        # Estimativa de prêmio (aproximação Black-Scholes para OTM)
        iv = item.get("iv_approx", 0.28)
        t = days_to_exp / 252.0
        r = self.cdi_annual

        def calc_put_premium(s, k, days_t):
            t_sub = days_t / 252.0
            if t_sub <= 0 or s <= 0 or k <= 0:
                return 0.0
            d1 = (math.log(s / k) + (r + 0.5 * iv ** 2) * t_sub) / (iv * math.sqrt(t_sub))
            d2 = d1 - iv * math.sqrt(t_sub)
            def norm_cdf(x):
                return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
            p = k * math.exp(-r * t_sub) * norm_cdf(-d2) - s * norm_cdf(-d1)
            return max(p, s * 0.007)

        premium_std = calc_put_premium(current_spot, strike_std, days_to_exp)
        premium_cons = calc_put_premium(current_spot, strike_cons, days_to_exp)

        # Rendimento estimado percentual da opção sobre o strike (capital garantidor)
        period_yield_std_pct = round((premium_std / strike_std) * 100.0, 2) if strike_std > 0 else 0.0
        period_yield_cons_pct = round((premium_cons / strike_cons) * 100.0, 2) if strike_cons > 0 else 0.0

        # Normaliza para base mensal padrão (~30d) se dias forem curtos, garantindo uniformidade com Venda Coberta
        factor_monthly = (30.0 / days_to_exp) if days_to_exp > 0 else 1.0
        monthly_yield_std_pct = round(period_yield_std_pct * factor_monthly, 2) if days_to_exp < 20 else period_yield_std_pct
        monthly_yield_cons_pct = round(period_yield_cons_pct * factor_monthly, 2) if days_to_exp < 20 else period_yield_cons_pct

        annualized_option_std_pct = round(monthly_yield_std_pct * 12.0, 2)
        cdi_base_annual_pct = round(self.cdi_annual * 100.0, 2)  # 11.75%
        cdi_month_yield_pct = round(((1.0 + self.cdi_annual) ** (1.0 / 12.0) - 1.0) * 100.0, 2)  # 0.93%

        # % do CDI uniforme: Taxa mensal da opção / CDI mensal (0,93% a.m.)
        cdi_ratio_std_pct = round((monthly_yield_std_pct / cdi_month_yield_pct) * 100.0, 0)

        # Retorno total no mês somando a garantia no Tesouro Selic / 100% CDI
        total_monthly_with_cdi_pct = round(monthly_yield_std_pct + cdi_month_yield_pct, 2)
        total_cdi_ratio_pct = round(cdi_ratio_std_pct + 100.0, 0)

        # Margem de segurança percentual
        safety_margin_std = ((current_spot - strike_std) / current_spot) * 100.0

        return {
            "symbol": sym.replace(".SA", ""),
            "company_name": item["name"],
            "sector": item["type"],
            "current_price": round(current_spot, 2),
            "atr_14": round(atr_14, 2),
            "expiration_date": exp_date.strftime("%d/%m/%Y"),
            "days_to_expiration": days_to_exp,
            "target_cycle": target_cycle,
            "cdi_annual_pct": cdi_base_annual_pct,
            "cdi_monthly_pct": cdi_month_yield_pct,
            "standard_setup": {
                "strike": strike_std,
                "safety_margin_pct": round(safety_margin_std, 1),
                "estimated_premium": round(premium_std, 2),
                "period_yield_pct": period_yield_std_pct,
                "monthly_yield_pct": monthly_yield_std_pct,
                "option_yield_pct": monthly_yield_std_pct,
                "cdi_ratio_pct": cdi_ratio_std_pct,
                "total_monthly_yield_with_cdi_pct": total_monthly_with_cdi_pct,
                "total_cdi_ratio_pct": total_cdi_ratio_pct,
                "cdi_multiple": round(cdi_ratio_std_pct / 100.0, 1),
                "annualized_rate_pct": annualized_option_std_pct
            },
            "conservative_setup": {
                "strike": strike_cons,
                "safety_margin_pct": round(((current_spot - strike_cons) / current_spot) * 100.0, 1),
                "estimated_premium": round(premium_cons, 2),
                "monthly_yield_pct": monthly_yield_cons_pct,
                "option_yield_pct": monthly_yield_cons_pct
            }
        }


    def scan_all(self, target_cycle: str = "current") -> List[Dict[str, Any]]:
        results = []
        for item in DEFAULT_WATCHLIST:
            try:
                res = self.scan_symbol(item, target_cycle=target_cycle)
                if res:
                    results.append(res)
            except Exception as e:
                print(f"Erro ao analisar {item['symbol']}: {e}")
        return results


if __name__ == "__main__":
    screener = PutSellingScreener()
    results = screener.scan_all()
    print("\n" + "="*80)
    print("  SCREENER AO VIVO: OPORTUNIDADES VENDA DE PUT -1 ATR (B3)")
    print(f"  Vencimento Alvo: {screener.get_next_expiration_date().strftime('%d/%m/%Y')} | Selic/CDI Base: 11.75% a.a.")
    print("="*80)
    for r in results:
        std = r["standard_setup"]
        print(f"\n[{r['symbol']}] {r['company_name']} - Cotação: R$ {r['current_price']:.2f} (ATR-14: R$ {r['atr_14']:.2f})")
        print(f"  -> Strike Alvo (-1 ATR): R$ {std['strike']:.2f} (Distância: {std['safety_margin_pct']}%)")
        print(f"  -> Prêmio Estimado: R$ {std['estimated_premium']:.2f} ({std['option_yield_pct']}% sobre strike)")
        print(f"  -> Retorno Total Mês (Opção + CDI): {std['total_monthly_yield_with_cdi_pct']}% ({std['cdi_multiple']}x o CDI) -> {std['annualized_rate_pct']}% a.a.")
    print("\n" + "="*80 + "\n")
