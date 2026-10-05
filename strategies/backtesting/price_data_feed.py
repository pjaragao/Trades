"""
Provedor de Dados de Mercado Históricos com Cache Local SQLite.
Utiliza yfinance para buscar cotações diárias (OHLCV) de ações e índices B3,
armazenando em banco SQLite local para acelerar backtests e screeners.
"""

import os
import sqlite3
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional

class PriceDataFeed:
    def __init__(self, db_path: str = "strategies/data_cache/market_prices.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_bars (
                    symbol TEXT,
                    date TEXT,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    PRIMARY KEY (symbol, date)
                )
            """)
            conn.commit()

    def get_daily_prices(self, symbol: str, start_date: str = "2015-01-01", force_refresh: bool = False) -> pd.DataFrame:
        """Retorna DataFrame de cotações diárias com Open, High, Low, Close, Volume."""
        if not symbol.endswith(".SA") and not symbol.startswith("^") and "=X" not in symbol and "-USD" not in symbol:
            yf_symbol = f"{symbol}.SA"
        else:
            yf_symbol = symbol

        # Verifica dados no cache
        if not force_refresh:
            with sqlite3.connect(self.db_path) as conn:
                df_cached = pd.read_sql_query(
                    "SELECT date, open, high, low, close, volume FROM daily_bars WHERE symbol = ? AND date >= ? ORDER BY date ASC",
                    conn,
                    params=(yf_symbol, start_date)
                )
            if not df_cached.empty and len(df_cached) > 200:
                df_cached["date"] = pd.to_datetime(df_cached["date"])
                df_cached.set_index("date", inplace=True)
                return df_cached

        # Baixa via yfinance
        print(f"Baixando histórico de cotações para {yf_symbol} via yfinance...")
        ticker_obj = yf.Ticker(yf_symbol)
        df = ticker_obj.history(start=start_date, auto_adjust=True)

        if df.empty:
            print(f"Aviso: Não foram encontrados dados para {yf_symbol}")
            return pd.DataFrame()

        df.reset_index(inplace=True)
        df.rename(columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume"
        }, inplace=True)

        # Salva no cache
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for _, row in df.iterrows():
                dt_str = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])[:10]
                cursor.execute("""
                    INSERT OR REPLACE INTO daily_bars (symbol, date, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    yf_symbol,
                    dt_str,
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row["volume"])
                ))
            conn.commit()

        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        return df[["open", "high", "low", "close", "volume"]]

if __name__ == "__main__":
    feed = PriceDataFeed()
    df = feed.get_daily_prices("VALE3.SA", start_date="2020-01-01")
    print(f"VALE3.SA barras carregadas: {len(df)}")
    print(df.tail(5))
