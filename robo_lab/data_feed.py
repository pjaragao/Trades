"""
Provedor Multi-Timeframe de Séries Históricas (SQLite Cache + MT5 Local + Resampling).
Suporta:
- Futuros da B3: Mini-Índice ('WIN$N', tick de 5 pts) e Mini-Dólar ('WDO$N', cotado em pts = USD/BRL * 1000, tick de 0.5 pt).
- Timeframes Curtos de Day Trade ('1m', '2m', '3m', '5m', '15m', '60m') e Swing ('1d', '1wk').
- Conexão com cache SQLite real, terminal MetaTrader 5 local e reconstrução intradiária fiel ao tick da B3.
"""

import sqlite3
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from robo_lab.config import FUTURES_SPECS, LEGACY_MARKET_DB, MARKET_CACHE_DB


def _round_to_tick(series_or_arr, tick_size: float):
    if tick_size <= 0:
        return series_or_arr
    return np.round(series_or_arr / tick_size) * tick_size


class MultiTimeframeDataFeed:
    def __init__(self, db_path: Path = MARKET_CACHE_DB, legacy_db_path: Path = LEGACY_MARKET_DB):
        self.db_path = Path(db_path)
        self.legacy_db_path = Path(legacy_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ohlcv_bars (
                    symbol TEXT,
                    timeframe TEXT,
                    ts TEXT,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    PRIMARY KEY (symbol, timeframe, ts)
                )
            """)
            conn.commit()

        with sqlite3.connect(self.db_path) as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM ohlcv_bars").fetchone()[0]
        if cnt == 0 and self.legacy_db_path.exists():
            with sqlite3.connect(self.legacy_db_path) as src, sqlite3.connect(self.db_path) as dst:
                rows = src.execute("SELECT symbol, date, open, high, low, close, volume FROM daily_bars").fetchall()
                dst.executemany(
                    "INSERT OR IGNORE INTO ohlcv_bars (symbol, timeframe, ts, open, high, low, close, volume) VALUES (?, '1d', ?, ?, ?, ?, ?, ?)",
                    [(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows],
                )
                dst.commit()

    def normalize_symbol(self, symbol: str) -> str:
        s = symbol.strip().upper()
        if s in ("WIN", "WINFUT", "WIN$N", "WIN@N", "IND", "INDFUT"):
            return "WIN$N"
        if s in ("WDO", "WDOFUT", "WDO$N", "WDO@N", "DOL", "DOLFUT"):
            return "WDO$N"
        if s in ("IBOV", "^BVSP"):
            return "^BVSP"
        if s in ("USDBRL", "USD/BRL", "BRL=X"):
            return "BRL=X"
        if not s.endswith(".SA") and not s.startswith("^") and "=" not in s and "$" not in s:
            return f"{s}.SA"
        return s

    def list_available_symbols(self) -> List[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT DISTINCT symbol FROM ohlcv_bars ORDER BY symbol").fetchall()
        syms = [r[0] for r in rows]
        for fut in ("WIN$N", "WDO$N"):
            if fut not in syms:
                syms.insert(0, fut)
        return syms

    def get_bars(
        self,
        symbol: str,
        timeframe: str = "1d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        min_bars: int = 120,
    ) -> pd.DataFrame:
        """
        Retorna DataFrame indexado por datetime com colunas: open, high, low, close, volume.
        Suporta '1m', '2m', '3m', '5m', '15m', '60m', '1d', '1wk'.
        """
        norm_sym = self.normalize_symbol(symbol)
        tf = timeframe.lower().strip()

        # 1. Tenta carregar diretamente do banco SQLite para o símbolo e timeframe solicitados
        df = self._query_db(norm_sym, tf, start_date, end_date)

        # 2. Se pediu WIN$N ou WDO$N e ainda não está populado no cache para este timeframe,
        # tenta MT5 ou deriva a partir de ^BVSP (em pontos, tick=5) / BRL=X (pts = R$ * 1000, tick=0.5)
        if len(df) < min_bars and norm_sym in ("WIN$N", "WDO$N"):
            mt5_df = self._try_fetch_from_mt5(norm_sym, tf, n_bars=max(min_bars * 4, 2500))
            if mt5_df is not None and len(mt5_df) >= min_bars:
                df = mt5_df
            else:
                df = self._build_futures_series(norm_sym, tf, start_date, end_date, min_bars)

        # Fallback para ^BVSP diário
        if tf == "1d" and len(df) < min_bars and norm_sym == "^BVSP":
            df = self._build_synthetic_ibov_daily(start_date, end_date)

        # 3. Se pediu '1wk' (Semanal), faz resample a partir do '1d'
        if tf == "1wk" and len(df) < min_bars:
            daily = self.get_bars(norm_sym, "1d", start_date=start_date, end_date=end_date, min_bars=50)
            if not daily.empty:
                df = daily.resample("W-FRI").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }).dropna()

        # 4. Se pediu '3m' e não existe nativo, tenta construir a partir de '1m' (resample 3min) ou subdividir de '5m'
        if tf == "3m" and len(df) < min_bars:
            df_1m = self._query_db(norm_sym, "1m", start_date, end_date)
            if len(df_1m) >= min_bars * 3:
                df = self._resample_intraday(df_1m, "3min")
            else:
                df_5m = self.get_bars(norm_sym, "5m", start_date=start_date, end_date=end_date, min_bars=min_bars)
                if not df_5m.empty:
                    df = self._subdivide_intraday(df_5m, target_tf="3m", norm_sym=norm_sym)

        # 5. Se pediu '1m' ou '2m' e tem menos barras que min_bars, usa '5m' para subdivisão de alta fidelidade
        if tf in ("1m", "2m") and len(df) < min_bars:
            df_5m = self.get_bars(norm_sym, "5m", start_date=start_date, end_date=end_date, min_bars=min_bars)
            if not df_5m.empty:
                df = self._subdivide_intraday(df_5m, target_tf=tf, norm_sym=norm_sym)

        # 6. Se pediu intraday ('60m', '15m', '5m') e o cache real não tem barras suficientes
        if tf in ("60m", "15m", "5m") and len(df) < min_bars:
            mt5_df = self._try_fetch_from_mt5(norm_sym, tf, n_bars=max(min_bars * 4, 2000))
            if mt5_df is not None and len(mt5_df) >= min_bars:
                df = mt5_df
            else:
                daily = self.get_bars(norm_sym, "1d", start_date=start_date, end_date=end_date, min_bars=30)
                if not daily.empty:
                    df = self._expand_daily_to_intraday(daily.tail(180), tf, norm_sym=norm_sym)

        return df

    def _build_futures_series(
        self,
        fut_sym: str,
        tf: str,
        start_date: Optional[str],
        end_date: Optional[str],
        min_bars: int,
    ) -> pd.DataFrame:
        """
        Constrói a série de pontos do Mini-Índice (WIN$N, tick=5.0) ou Mini-Dólar (WDO$N, tick=0.5)
        a partir das cotações reais de ^BVSP e BRL=X no banco SQLite, respeitando o tamanho do tick da B3.
        """
        tick = FUTURES_SPECS[fut_sym]["tick_size"]

        if fut_sym == "WIN$N":
            base_sym = "^BVSP"
            mult = 1.0
            base_df = self._query_db(base_sym, tf, start_date, end_date)
            if len(base_df) < min_bars and tf in ("1m", "2m", "3m"):
                b5m = self._query_db(base_sym, "5m", start_date, end_date)
                if len(b5m) >= 100:
                    base_df = self._subdivide_intraday(b5m, target_tf=tf, norm_sym=fut_sym)
            if len(base_df) < min_bars and tf in ("5m", "15m", "60m"):
                daily = self._query_db(base_sym, "1d", start_date, end_date)
                if len(daily) >= 30:
                    base_df = self._expand_daily_to_intraday(daily.tail(120), tf, norm_sym=fut_sym)
        else:
            # WDO$N (Mini-Dólar Futuro B3, cotado em pontos ex: 5.520,0 pts, tick = 0.5 pt)
            mult = 1000.0
            brl_1d = self._query_db("BRL=X", "1d", start_date, end_date)
            # Garante range diário realista caso o feed spot diário do Yahoo tenha High==Low em alguns dias
            if not brl_1d.empty:
                brl_1d = brl_1d.copy()
                rng_1d = brl_1d["high"] - brl_1d["low"]
                small_rng = rng_1d < 0.015
                if np.any(small_rng):
                    brl_1d.loc[small_rng, "high"] = np.maximum(brl_1d.loc[small_rng, "open"], brl_1d.loc[small_rng, "close"]) + 0.028
                    brl_1d.loc[small_rng, "low"] = np.minimum(brl_1d.loc[small_rng, "open"], brl_1d.loc[small_rng, "close"]) - 0.026

            if tf == "1d":
                base_df = brl_1d
            elif tf in ("60m", "15m", "5m"):
                base_df = self._expand_daily_to_intraday(brl_1d, tf, norm_sym="BRL=X")
            elif tf in ("1m", "2m", "3m"):
                b5m = self._expand_daily_to_intraday(brl_1d, "5m", norm_sym="BRL=X")
                base_df = self._subdivide_intraday(b5m, target_tf=tf, norm_sym="BRL=X")
            else:
                base_df = brl_1d

        if base_df.empty:
            return base_df

        out = base_df.copy()
        for col in ("open", "high", "low", "close"):
            out[col] = _round_to_tick(out[col].to_numpy(dtype=float) * mult, tick)
        out["high"] = np.maximum(out["high"], np.maximum(out["open"], out["close"]))
        out["low"] = np.minimum(out["low"], np.minimum(out["open"], out["close"]))
        zero_rng = out["high"] <= out["low"]
        if np.any(zero_rng):
            out.loc[zero_rng, "high"] = out.loc[zero_rng, "low"] + tick

        if (out["volume"] <= 0).all():
            rng_ticks = np.maximum(1.0, (out["high"] - out["low"]) / tick)
            hour_series = pd.Series(out.index.hour, index=out.index)
            u_mult = np.where((hour_series >= 9) & (hour_series <= 11), 1.45, np.where(hour_series >= 15, 1.25, 0.85))
            out["volume"] = np.round(rng_ticks * 1250.0 * u_mult)

        return out

    def _resample_intraday(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        if df.empty:
            return df
        res = df.resample(rule).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(subset=["open", "high", "low", "close"])
        return res

    def _subdivide_intraday(self, df_parent: pd.DataFrame, target_tf: str, norm_sym: str) -> pd.DataFrame:
        """
        Gera barras de 1m a partir das barras reais de 5m preservando exatamente o Open, High, Low, Close e Volume
        de cada janela de 5 minutos e respeitando o tick mínimo do ativo (5 pts para WIN$N, 0.5 pt para WDO$N).
        Para '2m' e '3m', agrega as barras de 1m nas janelas cronológicas exatas de 2min (:00,:02,:04...) e 3min (:00,:03,:06...).
        """
        tick = FUTURES_SPECS.get(norm_sym, {}).get("tick_size", 0.0005 if norm_sym == "BRL=X" else 0.01)

        rng = np.random.default_rng(seed=101)
        records = []
        parent_slice = df_parent.tail(1500)

        for ts, row in parent_slice.iterrows():
            o, h, l, c, v = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), float(row["volume"])
            if h < l or o <= 0 or c <= 0:
                continue
            if v <= 0:
                v = 50000.0
            bull = c >= o
            wp_x = [0, 1, 3, 5]
            wp_y = [o, l if bull else h, h if bull else l, c]
            pts = np.interp(np.arange(6), wp_x, wp_y)
            pts[1:5] = np.clip(_round_to_tick(pts[1:5] + rng.normal(0.0, (h - l) * 0.1, size=4), tick), l, h)
            for i in range(5):
                bo = float(pts[i])
                bc = float(pts[i + 1])
                wig = float(_round_to_tick(abs(rng.normal(0.0, max((h - l) * 0.12, tick))), tick))
                bh = min(h, max(bo, bc) + wig)
                bl = max(l, min(bo, bc) - wig)
                if i == 1 and bull:
                    bl = l
                elif i == 1 and not bull:
                    bh = h
                if i == 3 and bull:
                    bh = h
                elif i == 3 and not bull:
                    bl = l
                records.append((ts + pd.Timedelta(minutes=i), bo, bh, bl, bc, v * 0.20))

        if not records:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        out_1m = pd.DataFrame(records, columns=["ts", "open", "high", "low", "close", "volume"])
        out_1m = out_1m.drop_duplicates(subset=["ts"], keep="first").set_index("ts").sort_index()
        if target_tf == "1m":
            return out_1m
        rule = "2min" if target_tf == "2m" else "3min"
        return self._resample_intraday(out_1m, rule)

    def _query_db(self, symbol: str, timeframe: str, start_date: Optional[str], end_date: Optional[str]) -> pd.DataFrame:
        query = "SELECT ts, open, high, low, close, volume FROM ohlcv_bars WHERE symbol = ? AND timeframe = ?"
        params: list = [symbol, timeframe]
        if start_date:
            query += " AND ts >= ?"
            params.append(start_date)
        if end_date:
            query += " AND ts <= ?"
            params.append(end_date + " 23:59:59")
        query += " ORDER BY ts ASC"

        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(query, conn, params=params)
        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"])
        df.set_index("ts", inplace=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.dropna(subset=["open", "high", "low", "close"])

    def _build_synthetic_ibov_daily(self, start_date: Optional[str], end_date: Optional[str]) -> pd.DataFrame:
        weights = {
            "VALE3.SA": 0.35,
            "PETR4.SA": 0.30,
            "ITUB4.SA": 0.15,
            "BBAS3.SA": 0.10,
            "WEGE3.SA": 0.10,
        }
        frames = {}
        for sym in weights:
            d = self._query_db(sym, "1d", start_date, end_date)
            if not d.empty:
                frames[sym] = d

        if not frames:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        base_syms = [s for s in ("VALE3.SA", "PETR4.SA") if s in frames] or list(frames.keys())
        idx = frames[base_syms[0]].index
        for s in base_syms[1:]:
            idx = idx.intersection(frames[s].index)
        if len(idx) == 0:
            return frames[list(frames.keys())[0]]

        ret_close = pd.Series(0.0, index=idx)
        ret_open = pd.Series(0.0, index=idx)
        ret_high = pd.Series(0.0, index=idx)
        ret_low = pd.Series(0.0, index=idx)
        vol_sum = pd.Series(0.0, index=idx)

        total_w = sum(weights[s] for s in base_syms)
        for s in base_syms:
            w = weights[s] / total_w
            sub = frames[s].loc[idx]
            c_prev = sub["close"].shift(1).bfill()
            ret_close += w * (sub["close"] / c_prev - 1.0)
            ret_open += w * (sub["open"] / c_prev - 1.0)
            ret_high += w * (sub["high"] / c_prev - 1.0)
            ret_low += w * (sub["low"] / c_prev - 1.0)
            vol_sum += sub["volume"]

        close_pts = 75000.0 * (1.0 + ret_close).cumprod()
        prev_pts = close_pts.shift(1).fillna(75000.0)
        open_pts = prev_pts * (1.0 + ret_open)
        high_pts = np.maximum(np.maximum(open_pts, close_pts), prev_pts * (1.0 + ret_high))
        low_pts = np.minimum(np.minimum(open_pts, close_pts), prev_pts * (1.0 + ret_low))

        return pd.DataFrame({
            "open": open_pts,
            "high": high_pts,
            "low": low_pts,
            "close": close_pts,
            "volume": vol_sum,
        }, index=idx)

    def _try_fetch_from_mt5(self, symbol: str, timeframe: str, n_bars: int = 2000) -> Optional[pd.DataFrame]:
        try:
            import MetaTrader5 as mt5  # type: ignore
            if not mt5.initialize():
                return None
            tf_map = {
                "1m": mt5.TIMEFRAME_M1,
                "2m": getattr(mt5, "TIMEFRAME_M2", mt5.TIMEFRAME_M1),
                "3m": getattr(mt5, "TIMEFRAME_M3", mt5.TIMEFRAME_M5),
                "5m": mt5.TIMEFRAME_M5,
                "15m": mt5.TIMEFRAME_M15,
                "60m": mt5.TIMEFRAME_H1,
                "1d": mt5.TIMEFRAME_D1,
                "1wk": mt5.TIMEFRAME_W1,
            }
            mt5_tf = tf_map.get(timeframe)
            if mt5_tf is None:
                return None
            mt5_sym = symbol.replace(".SA", "")
            if mt5_sym == "^BVSP":
                mt5_sym = "WIN$N"
            elif mt5_sym == "BRL=X":
                mt5_sym = "WDO$N"
            rates = mt5.copy_rates_from_pos(mt5_sym, mt5_tf, 0, n_bars)
            if rates is None or len(rates) == 0:
                return None
            df = pd.DataFrame(rates)
            df["ts"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("ts", inplace=True)
            df.rename(columns={"real_volume": "volume", "tick_volume": "tick_vol"}, inplace=True)
            if "volume" not in df.columns or df["volume"].sum() == 0:
                df["volume"] = df.get("tick_vol", 1.0)
            return df[["open", "high", "low", "close", "volume"]]
        except Exception:
            return None

    def _expand_daily_to_intraday(self, daily_df: pd.DataFrame, timeframe: str, norm_sym: str = "") -> pd.DataFrame:
        bars_per_day = {"60m": 9, "15m": 34, "5m": 84, "3m": 120, "2m": 160, "1m": 240}.get(timeframe, 28)
        step_minutes = {"60m": 60, "15m": 15, "5m": 5, "3m": 3, "2m": 2, "1m": 1}.get(timeframe, 15)
        tick = FUTURES_SPECS.get(norm_sym, {}).get("tick_size", 0.0005 if norm_sym == "BRL=X" else 0.01)

        records = []
        rng = np.random.default_rng(seed=42)
        u_grid = np.linspace(-1.0, 1.0, bars_per_day)
        vol_profile = 1.0 + 0.85 * (u_grid ** 2)
        vol_profile /= vol_profile.sum()

        for dt, row in daily_df.iterrows():
            o, h, l, c, v = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), float(row["volume"])
            if h <= l or o <= 0 or c <= 0:
                continue
            if v <= 0:
                v = 100000.0

            bull_day = c >= o
            p1_idx = max(1, int(bars_per_day * 0.25))
            p2_idx = max(p1_idx + 1, int(bars_per_day * 0.70))

            first_extreme = l if bull_day else h
            second_extreme = h if bull_day else l

            waypoints_x = [0, p1_idx, p2_idx, bars_per_day]
            waypoints_y = [o, first_extreme, second_extreme, c]
            base_path = np.interp(np.arange(bars_per_day + 1), waypoints_x, waypoints_y)

            noise_scale = (h - l) * 0.09
            noise = rng.normal(0.0, noise_scale, size=bars_per_day + 1)
            noise[0] = 0.0
            noise[-1] = 0.0
            path = _round_to_tick(np.clip(base_path + noise, l, h), tick)
            path[0] = o
            path[-1] = c

            base_ts = pd.Timestamp(dt.year, dt.month, dt.day, 9, 0, 0) if norm_sym in ("WIN$N", "WDO$N", "BRL=X") else pd.Timestamp(dt.year, dt.month, dt.day, 10, 0, 0)
            for i in range(bars_per_day):
                bar_o = float(path[i])
                bar_c = float(path[i + 1])
                wiggle = float(_round_to_tick(abs(rng.normal(0.0, (h - l) / (bars_per_day * 0.85))), tick))
                bar_h = min(h, max(bar_o, bar_c) + wiggle)
                bar_l = max(l, min(bar_o, bar_c) - wiggle)
                if i == p1_idx:
                    if bull_day:
                        bar_l = l
                    else:
                        bar_h = h
                elif i == p2_idx:
                    if bull_day:
                        bar_h = h
                    else:
                        bar_l = l
                if bar_h <= bar_l:
                    bar_h = bar_l + tick
                bar_v = v * float(vol_profile[i]) * float(rng.uniform(0.85, 1.15))
                bar_ts = base_ts + pd.Timedelta(minutes=i * step_minutes)
                records.append((bar_ts, bar_o, bar_h, bar_l, bar_c, bar_v))

        if not records:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        out = pd.DataFrame(records, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")
        return out
