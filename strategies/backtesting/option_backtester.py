"""
Simulador Quantitativo de Backtest para a Estratégia de Opções:
Venda de Put OTM no Nível -1 ATR (STRAT-YT-001).
Reproduz o ciclo mensal de opções da B3 (terceira semana de cada mês),
calculando a taxa de acerto, rendimento CDI, perdas eventuais e curva de patrimônio.
"""

import os
import sys
import math
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from strategies.backtesting.price_data_feed import PriceDataFeed

class OptionBacktester:
    def __init__(self, cdi_annual_rate: float = 0.1175, data_feed: PriceDataFeed = None):
        self.cdi_annual_rate = cdi_annual_rate
        self.data_feed = data_feed or PriceDataFeed()

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calcula o Average True Range de 14 períodos."""
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

    def estimate_put_premium(self, spot: float, strike: float, days_to_exp: int = 21, iv: float = 0.32) -> float:
        """
        Estimativa do prêmio de Put OTM via modelo simplificado de Black-Scholes.
        Para puts OTM em torno de -1 ATR (~delta 0.06-0.10), o prêmio gira tipicamente
        entre 0.8% e 1.6% do valor nominal da ação.
        """
        r = self.cdi_annual_rate
        t = max(days_to_exp, 1) / 252.0
        if spot <= 0 or strike <= 0 or t <= 0:
            return 0.0

        d1 = (math.log(spot / strike) + (r + 0.5 * iv ** 2) * t) / (iv * math.sqrt(t))
        d2 = d1 - iv * math.sqrt(t)

        def norm_cdf(x):
            return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

        # Preço da Put pelo modelo Black-Scholes
        put_price = strike * math.exp(-r * t) * norm_cdf(-d2) - spot * norm_cdf(-d1)
        
        # Piso de segurança de prêmio para refletir o mercado real de volatilidade da B3
        min_premium = spot * 0.0075 # No mínimo 0.75%
        return max(put_price, min_premium)

    def run_backtest(
        self,
        symbol: str = "VALE3.SA",
        initial_capital: float = 100000.0,
        start_date: str = "2015-01-01",
        atr_multiplier: float = 1.0,
        iv: float = 0.32
    ) -> Dict[str, Any]:
        """Executa simulação mês a mês da estratégia."""
        df = self.data_feed.get_daily_prices(symbol, start_date=start_date)
        if df.empty or len(df) < 60:
            return {"error": f"Dados insuficientes para {symbol}"}

        df["atr"] = self.calculate_atr(df, period=14)
        df.dropna(subset=["atr"], inplace=True)

        # Identifica terceira sexta-feira de cada mês (vencimento B3)
        # Agrupamos por ano e mês
        monthly_trades = []
        equity = initial_capital
        cdi_equity = initial_capital
        buy_hold_shares = initial_capital / df["close"].iloc[0]

        grouped = df.groupby([df.index.year, df.index.month])

        prev_month_close = None
        cdi_monthly_rate = (1.0 + self.cdi_annual_rate) ** (1.0 / 12.0) - 1.0

        for (year, month), month_df in grouped:
            if len(month_df) < 10:
                continue

            # Início do ciclo (primeiro dia do mês útil)
            entry_row = month_df.iloc[0]
            entry_date = month_df.index[0].strftime("%Y-%m-%d")
            spot_entry = float(entry_row["close"])
            atr_val = float(entry_row["atr"])

            # Strike da Put (-1 ATR)
            strike = round(spot_entry - (atr_multiplier * atr_val), 2)
            strike = max(0.5, strike)

            # Final do ciclo (terceira semana ou fechamento do mês)
            exit_idx = min(15, len(month_df) - 1)
            exit_row = month_df.iloc[exit_idx]
            exit_date = month_df.index[exit_idx].strftime("%Y-%m-%d")
            spot_exit = float(exit_row["close"])

            # Prêmio estimado da Put
            premium = self.estimate_put_premium(spot_entry, strike, days_to_exp=exit_idx, iv=iv)
            premium_yield = premium / spot_entry

            # Rendimento da garantia no CDI no período
            cdi_gain = equity * cdi_monthly_rate
            cdi_equity *= (1.0 + cdi_monthly_rate)

            # Resultado da opção
            is_win = True
            option_loss = 0.0

            if spot_exit < strike:
                # Exercício: perda na diferença entre strike e spot_exit menos prêmio recebido
                is_win = False
                loss_per_share = (strike - spot_exit) - premium
                # Impacto percentual sobre o capital
                loss_pct = loss_per_share / spot_entry
                option_loss = equity * max(0.0, loss_pct)

            net_month_pnl = (equity * premium_yield) + cdi_gain - option_loss
            equity += net_month_pnl

            monthly_trades.append({
                "period": f"{year}-{month:02d}",
                "entry_date": entry_date,
                "exit_date": exit_date,
                "spot_entry": round(spot_entry, 2),
                "atr": round(atr_val, 2),
                "strike": strike,
                "spot_exit": round(spot_exit, 2),
                "premium": round(premium, 2),
                "is_win": is_win,
                "net_pnl": round(net_month_pnl, 2),
                "equity_after": round(equity, 2)
            })

        total_trades = len(monthly_trades)
        wins = [t for t in monthly_trades if t["is_win"]]
        win_rate = (len(wins) / total_trades) * 100.0 if total_trades > 0 else 0.0

        # Drawdown da estratégia
        equity_series = [t["equity_after"] for t in monthly_trades]
        peak = initial_capital
        max_dd = 0.0
        for eq in equity_series:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd

        final_spot = df["close"].iloc[-1]
        final_buy_hold = buy_hold_shares * final_spot

        return {
            "symbol": symbol,
            "period": f"{start_date} até {df.index[-1].strftime('%Y-%m-%d')}",
            "total_months": total_trades,
            "win_months": len(wins),
            "loss_months": total_trades - len(wins),
            "win_rate_pct": round(win_rate, 2),
            "initial_capital": round(initial_capital, 2),
            "final_equity": round(equity, 2),
            "strategy_multiple": round(equity / initial_capital, 2),
            "cdi_final_equity": round(cdi_equity, 2),
            "cdi_multiple": round(cdi_equity / initial_capital, 2),
            "buy_hold_final_equity": round(final_buy_hold, 2),
            "buy_hold_multiple": round(final_buy_hold / initial_capital, 2),
            "max_drawdown_pct": round(max_dd * 100.0, 2),
            "sample_months": monthly_trades[-12:] # Últimos 12 meses
        }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Option Put Selling Backtest")
    parser.add_argument("--ticker", type=str, default="VALE3.SA")
    parser.add_argument("--start", type=str, default="2016-01-01")
    args = parser.parse_args()

    tester = OptionBacktester()
    res = tester.run_backtest(args.ticker, start_date=args.start)
    print("\n" + "="*60)
    print(f"  BACKTEST: VENDA DE PUT -1 ATR ({res.get('symbol')})")
    print("="*60)
    print(f"Período: {res.get('period')}")
    print(f"Total de Meses: {res.get('total_months')}")
    print(f"Taxa de Acerto: {res.get('win_rate_pct')}% ({res.get('win_months')} vitórias / {res.get('loss_months')} perdas)")
    print(f"Patrimônio Final Estratégia: R$ {res.get('final_equity'):,.2f} ({res.get('strategy_multiple')}x)")
    print(f"Patrimônio Final CDI (100%): R$ {res.get('cdi_final_equity'):,.2f} ({res.get('cdi_multiple')}x)")
    print(f"Patrimônio Final Buy & Hold: R$ {res.get('buy_hold_final_equity'):,.2f} ({res.get('buy_hold_multiple')}x)")
    print(f"Max Drawdown: {res.get('max_drawdown_pct')}%")
    print("="*60 + "\n")
