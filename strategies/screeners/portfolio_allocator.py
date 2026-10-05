"""
Simulador e Calculadora de Alocação Patrimonial Híbrida (STRAT-YT-007).
Alocação quantitativa baseada no modelo de R$ 100k com Dividendos Sintéticos:
- 60% Renda Fixa / LFT / Tesouro Selic (Margem de garantia B3 e rendimento de 100% CDI)
- 30% Ações Sólidas Dividendistas B3 (BBAS3, ITUB4, CPLE6, VALE3) com Venda Coberta
- 10% Caixa Livre e Reserva de Oportunidade
- Venda de Puts OTM com lastro na garantia de 60%.
Projeta a renda passiva mensal em R$, % ao mês e múltiplo do CDI.
"""

from typing import Dict, Any, List

class PortfolioAllocator:
    def __init__(self, cdi_annual: float = 0.1175):
        self.cdi_annual = cdi_annual
        self.cdi_monthly = (1.0 + self.cdi_annual) ** (1.0 / 12.0) - 1.0

    def calculate_allocation(self, total_capital: float = 100000.0) -> Dict[str, Any]:
        capital = max(total_capital, 5000.0)

        # 1. Divisão Patrimonial
        rf_capital = capital * 0.60
        stocks_capital = capital * 0.30
        cash_capital = capital * 0.10

        # 2. Rendas Projetadas Mensais
        # A) Rendimento CDI da Renda Fixa (líquido de IR ~17.5%)
        rf_income_monthly = rf_capital * self.cdi_monthly * 0.825

        # B) Renda da Venda de Puts OTM com garantia na RF (~1.8% a.m. sobre a garantia)
        put_income_monthly = rf_capital * 0.018

        # C) Dividendos regulares médios das ações (~8% a.a. / 12)
        stocks_div_monthly = stocks_capital * (0.08 / 12.0)

        # D) Venda Coberta de Calls OTM sobre a carteira de ações (~1.5% a.m.)
        covered_call_monthly = stocks_capital * 0.015

        # Renda Total Mensal Estimada
        total_income_monthly = rf_income_monthly + put_income_monthly + stocks_div_monthly + covered_call_monthly
        total_income_pct_monthly = round((total_income_monthly / capital) * 100.0, 2)
        cdi_multiplier_pct = round((total_income_pct_monthly / (self.cdi_monthly * 100.0)) * 100.0, 0)

        # 3. Cesta Recomendada de Ativos para Composição
        basket_stocks = [
            {"ticker": "BBAS3", "name": "Banco do Brasil ON", "weight_pct": 30.0, "amount_brl": round(stocks_capital * 0.30, 2), "approx_price": 22.50},
            {"ticker": "ITUB4", "name": "Itaú Unibanco PN", "weight_pct": 25.0, "amount_brl": round(stocks_capital * 0.25, 2), "approx_price": 42.70},
            {"ticker": "VALE3", "name": "Vale S.A.", "weight_pct": 25.0, "amount_brl": round(stocks_capital * 0.25, 2), "approx_price": 78.20},
            {"ticker": "PETR4", "name": "Petrobras PN", "weight_pct": 20.0, "amount_brl": round(stocks_capital * 0.20, 2), "approx_price": 49.00}
        ]

        for s in basket_stocks:
            s["shares_qty"] = int(s["amount_brl"] // s["approx_price"])

        return {
            "total_capital": round(capital, 2),
            "cdi_annual_pct": round(self.cdi_annual * 100.0, 2),
            "cdi_monthly_pct": round(self.cdi_monthly * 100.0, 2),
            "allocations": {
                "fixed_income_guarantee": {
                    "label": "Renda Fixa / Tesouro Selic / LFTS11 (Garantia B3)",
                    "percentage": 60.0,
                    "amount_brl": round(rf_capital, 2),
                    "role": "Gera 100% CDI e serve como margem para Venda de Puts"
                },
                "dividend_stocks": {
                    "label": "Ações Blue Chips Dividendistas",
                    "percentage": 30.0,
                    "amount_brl": round(stocks_capital, 2),
                    "role": "Recebe proventos regulares e serve de lastro para Venda Coberta"
                },
                "cash_reserve": {
                    "label": "Caixa Livre & Reserva de Oportunidade",
                    "percentage": 10.0,
                    "amount_brl": round(cash_capital, 2),
                    "role": "Liquidez imediata para ajustes ou quedas fortes de mercado"
                }
            },
            "income_breakdown": {
                "rf_yield_monthly": round(rf_income_monthly, 2),
                "put_selling_monthly": round(put_income_monthly, 2),
                "stocks_dividends_monthly": round(stocks_div_monthly, 2),
                "covered_call_monthly": round(covered_call_monthly, 2)
            },
            "total_monthly_income_brl": round(total_income_monthly, 2),
            "monthly_return_pct": total_income_pct_monthly,
            "annualized_return_pct": round(total_income_pct_monthly * 12.0, 2),
            "cdi_multiplier_pct": cdi_multiplier_pct,
            "recommended_basket": basket_stocks,
            "strategy_id": "STRAT-YT-007",
            "strategy_name": "Alocação Híbrida de R$ 100k com Dividendos Sintéticos"
        }

if __name__ == "__main__":
    allocator = PortfolioAllocator()
    res = allocator.calculate_allocation(100000.0)
    print("--- Alocação de R$ 100.000,00 ---")
    print(f"Renda Total Mensal Projetada: R$ {res['total_monthly_income_brl']} ({res['monthly_return_pct']}%/mês = {res['cdi_multiplier_pct']}% do CDI)")
    print(f"Renda Fixa CDI: R$ {res['income_breakdown']['rf_yield_monthly']}")
    print(f"Venda de Puts: R$ {res['income_breakdown']['put_selling_monthly']}")
    print(f"Dividendos Ações: R$ {res['income_breakdown']['stocks_dividends_monthly']}")
    print(f"Venda Coberta: R$ {res['income_breakdown']['covered_call_monthly']}")
