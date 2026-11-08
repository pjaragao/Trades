import os
import sys
import math
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import yfinance as yf

class TimesFMPredictor:
    """
    Módulo preditivo baseado no modelo Google TimesFM (Foundation Model para Time Series).
    Analisa a cotação histórica do papel principal (ativo subjacente na B3)
    e projeta a trajetória futura de preços para avaliar a probabilidade de sucesso do trade.
    """

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = TimesFMPredictor()
        return cls._instance

    def __init__(self, horizon: int = 15, context_len: int = 128):
        self.horizon = horizon
        self.context_len = context_len
        self.model = None
        self._cache_history: Dict[str, Tuple[datetime, pd.DataFrame]] = {}
        self._init_model()

    def _init_model(self):
        """Carrega e compila o modelo TimesFM PyTorch localmente."""
        try:
            # Import tardio: torch/timesfm são pesados e opcionais (requirements-lab.txt)
            from timesfm import ForecastConfig
            from timesfm.timesfm_2p5.timesfm_2p5_torch import TimesFM_2p5_200M_torch

            print("Carregando modelo Google TimesFM 2.5 local...")
            self.model = TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")
            config = ForecastConfig(
                max_context=self.context_len,
                max_horizon=self.horizon,
                normalize_inputs=True,
                per_core_batch_size=1
            )
            self.model.compile(config)
            print("Google TimesFM carregado e compilado com sucesso!")
        except Exception as e:
            print(f"Aviso ao inicializar TimesFM: {e}")
            self.model = None

    def map_option_to_underlying(self, ticker: str) -> Tuple[str, str, Optional[float]]:
        """
        Mapeia um ticker de opção da B3 (ex: PETRV480, MGLUJ584) ou ação (ex: PRIO3, WEGE3, PETR4, BOVA11)
        para o ativo subjacente (PETR4.SA, MGLU3.SA, PRIO3.SA),
        identificando tipo (ACAO/CALL/PUT) e strike estimado se for opção.
        """
        import re
        ticker_clean = ticker.strip().upper()
        ticker_raw = ticker_clean.replace(".SA", "")

        # Futuros e Índices
        if "WINFUT" in ticker_raw or "WIN" in ticker_raw:
            return "^BVSP", "INDICE", None
        if "WDOFUT" in ticker_raw or "WDO" in ticker_raw:
            return "BRL=X", "FOREX", None
        if "SP500" in ticker_raw:
            return "^GSPC", "INDICE", None
        if "BTC" in ticker_raw:
            return "BTC-USD", "CRIPTO", None

        # Mapeia prefixos comuns para tickers ON/PN/Unit na B3
        ticker_map = {
            "PETR": "PETR4.SA",
            "VALE": "VALE3.SA",
            "ITUB": "ITUB4.SA",
            "BBDC": "BBDC4.SA",
            "BBAS": "BBAS3.SA",
            "MGLU": "MGLU3.SA",
            "BEEF": "BEEF3.SA",
            "VIVA": "VIVA3.SA",
            "RENT": "RENT3.SA",
            "CSAN": "CSAN3.SA",
            "DIRR": "DIRR3.SA",
            "ECOR": "ECOR3.SA",
            "SEER": "SEER3.SA",
            "AXIA": "AXIA3.SA",
            "SAUD": "SAUD3.SA",
            "CMIN": "CMIN3.SA",
            "SIMH": "SIMH3.SA",
            "VAMO": "VAMO3.SA",
            "TEND": "TEND3.SA",
            "HAPV": "HAPV3.SA",
            "RDOR": "RDOR3.SA",
            "LREN": "LREN3.SA",
            "EMBR": "EMBR3.SA",
            "SUZB": "SUZB3.SA",
            "WEGE": "WEGE3.SA",
            "PRIO": "PRIO3.SA",
            "BOVA": "BOVA11.SA",
            "SMAL": "SMAL11.SA",
            "GGBR": "GGBR4.SA",
            "GOAU": "GOAU4.SA",
            "USIM": "USIM5.SA",
            "ELET": "ELET6.SA",
            "CSNA": "CSNA3.SA",
            "CPLE": "CPLE6.SA",
            "RAIZ": "RAIZ4.SA",
            "AZUL": "AZUL4.SA",
            "MULT": "MULT3.SA",
            "BRFS": "BRFS3.SA",
            "JBSS": "JBSS3.SA",
            "SBSP": "SBSP3.SA",
            "CPFE": "CPFE3.SA",
            "ENEV": "ENEV3.SA",
            "EGIE": "EGIE3.SA",
            "EQTL": "EQTL3.SA",
            "RADL": "RADL3.SA",
            "TIMS": "TIMS3.SA",
            "VIVT": "VIVT3.SA",
            "UGPA": "UGPA3.SA",
            "HYPE": "HYPE3.SA",
            "ASAI": "ASAI3.SA",
            "CRFB": "CRFB3.SA",
            "NTCO": "NTCO3.SA",
            "TOTS": "TOTS3.SA",
            "YDUQ": "YDUQ3.SA",
            "COGN": "COGN3.SA",
            "B3SA": "B3SA3.SA",
            "BRKM": "BRKM5.SA",
            "KLBN": "KLBN11.SA",
            "TAEE": "TAEE11.SA",
            "BPAC": "BPAC11.SA"
        }

        # 1. Se for diretamente uma AÇÃO / ETF / BDR da B3 (ex: PRIO3, PETR4, VALE3, BOVA11, AAPL34)
        # 4 letras seguidas de 1 ou 2 números (3, 4, 5, 6, 11, 34, etc.)
        if re.match(r'^[A-Z]{4}\d{1,2}$', ticker_raw):
            return f"{ticker_raw}.SA", "ACAO", None

        # 2. Opções da B3: Geralmente 4 letras de ativo + 1 letra de mês/tipo (A-X) + dígitos de strike
        # Letras A-L = CALL; Letras M-X = PUT
        if len(ticker_raw) >= 5 and ticker_raw[4] in "ABCDEFGHIJKLMNOPQRSTUVWX":
            prefix = ticker_raw[:4]
            month_char = ticker_raw[4]

            if month_char in "ABCDEFGHIJKL":
                opt_type = "CALL"
            else:
                opt_type = "PUT"

            # Tenta extrair strike numérico
            strike_str = ticker_raw[5:]
            strike_val = None
            if strike_str.isdigit():
                val = float(strike_str)
                # Formatações comuns de strike: 480 -> 48.0 ou 155 -> 15.5 ou 584 -> 5.84
                if val >= 1000:
                    strike_val = val / 100.0
                elif val >= 100:
                    strike_val = val / 10.0
                else:
                    strike_val = val

            underlying = ticker_map.get(prefix, f"{prefix}4.SA")
            return underlying, opt_type, strike_val

        return f"{ticker_raw}.SA", "ACAO", None

    def get_historical_prices(self, underlying: str, period: str = "6mo") -> Optional[pd.DataFrame]:
        """Consulta cotações históricas do papel principal com cache em memória."""
        now = datetime.now()
        if underlying in self._cache_history:
            cached_time, df = self._cache_history[underlying]
            if (now - cached_time).total_seconds() < 1800: # cache de 30 min
                return df

        try:
            data = yf.download(underlying, period=period, interval="1d", progress=False)
            if data is not None and not data.empty and len(data) >= 30:
                self._cache_history[underlying] = (now, data)
                return data
        except Exception as e:
            print(f"Erro ao baixar dados de {underlying}: {e}")

        return None

    def predict_trade_success(self, trade: Dict[str, Any], horizon_days: int = 15) -> Dict[str, Any]:
        """
        Executa a previsão usando o Google TimesFM para o ativo subjacente do trade.
        Calcula tendência, alinhamento, cones de probabilidade e Score de Sucesso.
        """
        ticker = trade.get("ticker", "").strip().upper()
        lado = str(trade.get("lado", "BUY")).upper()
        sug_strike = trade.get("strike")

        underlying_symbol, opt_type, estimated_strike = self.map_option_to_underlying(ticker)
        if trade.get("underlying_symbol"):
            underlying_symbol = trade.get("underlying_symbol")
        elif trade.get("underlying"):
            und = str(trade.get("underlying")).strip().upper()
            underlying_symbol = und if any(c in und for c in [".SA", "=", "^"]) else f"{und}.SA"
        elif trade.get("papel_principal"):
            und = str(trade.get("papel_principal")).strip().upper()
            underlying_symbol = und if any(c in und for c in [".SA", "=", "^"]) else f"{und}.SA"

        if opt_type == "ACAO":
            actual_opt_type = "ACAO"
        else:
            actual_opt_type = trade.get("opcao_tipo") or opt_type

        strike = float(sug_strike or estimated_strike or 0)

        # 1. Obtém dados históricos do papel principal
        hist_df = self.get_historical_prices(underlying_symbol)
        if hist_df is None or hist_df.empty:
            # Sem cotações não há previsão — nada de série inventada
            return {"error": f"Sem cotações históricas de {underlying_symbol} (Yahoo Finance). Tente mais tarde.", "ticker": ticker, "underlying": underlying_symbol}

        # Extrai série temporal de fechamento
        if isinstance(hist_df.columns, pd.MultiIndex):
            close_series = hist_df["Close"].iloc[:, 0].dropna()
        else:
            close_series = hist_df["Close"].dropna()

        prices = close_series.values.astype(np.float32)
        dates = [d.strftime("%Y-%m-%d") for d in close_series.index]

        current_price = float(prices[-1])
        context_window = prices[-min(len(prices), self.context_len):]

        # 2. Inferência com Google TimesFM
        used_model = False
        if self.model is not None:
            try:
                point_forecast, full_forecast = self.model.forecast(horizon=horizon_days, inputs=[context_window])
                used_model = True
                forecast_prices = point_forecast[0].tolist()

                # Quantis (ex: quantil 1 = 10%, quantil 5 = 50% mediana, quantil 9 = 90%)
                if full_forecast is not None and full_forecast.shape[-1] >= 10:
                    q10_series = full_forecast[0, :, 1].tolist()
                    q50_series = full_forecast[0, :, 5].tolist()
                    q90_series = full_forecast[0, :, 9].tolist()
                else:
                    std = float(np.std(context_window[-20:]))
                    q10_series = [p - 1.645 * std * math.sqrt(i + 1) for i, p in enumerate(forecast_prices)]
                    q50_series = forecast_prices
                    q90_series = [p + 1.645 * std * math.sqrt(i + 1) for i, p in enumerate(forecast_prices)]
            except Exception as e:
                print(f"Erro na inferência TimesFM para {ticker}: {e}")
                forecast_prices, q10_series, q50_series, q90_series = self._statistical_forecast(context_window, horizon_days)
        else:
            forecast_prices, q10_series, q50_series, q90_series = self._statistical_forecast(context_window, horizon_days)

        final_forecast_price = float(forecast_prices[-1])
        expected_change_pct = ((final_forecast_price - current_price) / current_price) * 100.0

        # 3. Análise da Probabilidade e Sucesso do Trade
        # Regras de Mercado para Opções:
        # - Se comprou PUT: o trade é bem-sucedido se o papel principal CAIR (preço final < preço atual)
        # - Se comprou CALL: o trade é bem-sucedido se o papel principal SUBIR (preço final > preço atual)
        is_put = actual_opt_type.upper() == "PUT"
        is_call = actual_opt_type.upper() == "CALL"

        if is_put:
            is_aligned = expected_change_pct < -0.2
            # Se o modelo prevê queda, a chance é alta
            if expected_change_pct < 0:
                base_score = 65.0 + min(abs(expected_change_pct) * 5.0, 30.0)
            else:
                base_score = max(45.0 - expected_change_pct * 4.0, 15.0)

            # Bônus se o preço projetado estiver abaixo do strike
            if strike > 0 and final_forecast_price <= strike:
                base_score = min(base_score + 10.0, 98.0)

            target_direction = "QUEDA"
            predicted_direction = "QUEDA" if expected_change_pct < 0 else "ALTA"

        elif is_call:
            is_aligned = expected_change_pct > 0.2
            # Se o modelo prevê alta, a chance é alta
            if expected_change_pct > 0:
                base_score = 65.0 + min(expected_change_pct * 5.0, 30.0)
            else:
                base_score = max(45.0 - abs(expected_change_pct) * 4.0, 15.0)

            # Bônus se o preço projetado estiver acima do strike
            if strike > 0 and final_forecast_price >= strike:
                base_score = min(base_score + 10.0, 98.0)

            target_direction = "ALTA"
            predicted_direction = "ALTA" if expected_change_pct > 0 else "QUEDA"

        else: # Índices ou Ações diretas (Swing Trade)
            is_buy = lado in ["BUY", "COMPRA"]
            if is_buy:
                is_aligned = expected_change_pct > 0
                base_score = 55.0 + min(expected_change_pct * 6.0, 40.0) if is_aligned else max(40.0 - abs(expected_change_pct) * 5.0, 15.0)
                target_direction = "ALTA"
            else:
                is_aligned = expected_change_pct < 0
                base_score = 55.0 + min(abs(expected_change_pct) * 6.0, 40.0) if is_aligned else max(40.0 - expected_change_pct * 5.0, 15.0)
                target_direction = "QUEDA"
            predicted_direction = "ALTA" if expected_change_pct > 0 else "QUEDA"

        ai_score = round(min(max(base_score, 10.0), 96.0), 1)
        und_ticker = underlying_symbol.replace(".SA", "").replace("^", "").replace("=X", "USD/BRL")

        # Classificação do Veredito
        if ai_score >= 75.0:
            verdict = "FORTE FAVORÁVEL"
            verdict_badge = "success"
            if actual_opt_type == "ACAO":
                reason = f"O TimesFM projeta forte tendência de {predicted_direction.lower()} no papel {und_ticker} ({expected_change_pct:+.2f}%), confirmando o sinal de Swing Trade com alta probabilidade."
            else:
                reason = f"O TimesFM projeta forte tendência de {predicted_direction.lower()} no papel {und_ticker} ({expected_change_pct:+.2f}%), confirmando a tese do trade com alta probabilidade."
        elif ai_score >= 60.0:
            verdict = "MODERADO FAVORÁVEL"
            verdict_badge = "cyan"
            if actual_opt_type == "ACAO":
                reason = f"O modelo aponta viés de {predicted_direction.lower()} ({expected_change_pct:+.2f}%), alinhado à operação de Swing Trade ({'Compra' if is_buy else 'Venda'})."
            else:
                reason = f"O modelo aponta viés de {predicted_direction.lower()} ({expected_change_pct:+.2f}%), alinhado à recomendação de {actual_opt_type}."
        elif ai_score >= 45.0:
            verdict = "NEUTRO / LATERAL"
            verdict_badge = "yellow"
            if actual_opt_type == "ACAO":
                reason = f"O TimesFM projeta baixa oscilação ({expected_change_pct:+.2f}%), indicando consolidação lateral para {und_ticker}."
            else:
                reason = f"O TimesFM projeta baixa oscilação ({expected_change_pct:+.2f}%), indicando risco de perda de prêmio por decaimento temporal (theta)."
        else:
            verdict = "ALERTA CONTRA-TENDÊNCIA"
            verdict_badge = "danger"
            if actual_opt_type == "ACAO":
                reason = f"ATENÇÃO: O modelo prevê movimento de {predicted_direction.lower()} ({expected_change_pct:+.2f}%), divergindo da recomendação de Swing Trade."
            else:
                reason = f"ATENÇÃO: O modelo prevê movimento de {predicted_direction.lower()} ({expected_change_pct:+.2f}%), divergindo da recomendação e aumentando o risco de loss."

        # Datas futuras projetadas
        last_dt = datetime.strptime(dates[-1], "%Y-%m-%d")
        future_dates = []
        cur_dt = last_dt
        while len(future_dates) < horizon_days:
            cur_dt += timedelta(days=1)
            if cur_dt.weekday() < 5: # dias úteis
                future_dates.append(cur_dt.strftime("%Y-%m-%d"))

        # Prepara série histórica recente para gráfico (últimos 40 dias)
        recent_count = min(40, len(dates))
        chart_historical = {
            "dates": dates[-recent_count:],
            "prices": [round(float(p), 2) for p in prices[-recent_count:]]
        }

        chart_forecast = {
            "dates": future_dates,
            "prices": [round(float(p), 2) for p in forecast_prices],
            "q10": [round(float(p), 2) for p in q10_series],
            "q90": [round(float(p), 2) for p in q90_series]
        }

        return {
            "ticker": ticker,
            "underlying": underlying_symbol,
            "underlying_ticker": und_ticker,
            "papel_principal": und_ticker,
            "opcao_tipo": actual_opt_type,
            "lado": lado,
            "current_price": round(current_price, 2),
            "strike": round(strike, 2) if strike > 0 else None,
            "forecast_final_price": round(final_forecast_price, 2),
            "expected_change_pct": round(expected_change_pct, 2),
            "target_direction": target_direction,
            "predicted_direction": predicted_direction,
            "is_aligned": is_aligned,
            "ai_score": ai_score,
            "verdict": verdict,
            "verdict_badge": verdict_badge,
            "reason": reason,
            "model_used": "Google TimesFM 2.5 (200M Parameters)" if used_model else "Extrapolação estatística (TimesFM indisponível)",
            "is_model": used_model,
            "chart_historical": chart_historical,
            "chart_forecast": chart_forecast
        }

    def _statistical_forecast(self, context_window: np.ndarray, horizon: int):
        """Fallback estatístico caso o modelo esteja indisponível."""
        last_val = context_window[-1]
        drift = (context_window[-1] - context_window[-20]) / 20.0 if len(context_window) >= 20 else 0.0
        std = float(np.std(context_window[-20:])) if len(context_window) >= 20 else 0.5

        forecast_prices = [last_val + drift * (i + 1) for i in range(horizon)]
        q10_series = [p - 1.645 * std * math.sqrt(i + 1) for i, p in enumerate(forecast_prices)]
        q50_series = forecast_prices
        q90_series = [p + 1.645 * std * math.sqrt(i + 1) for i, p in enumerate(forecast_prices)]
        return forecast_prices, q10_series, q50_series, q90_series
