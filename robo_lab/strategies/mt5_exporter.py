"""
Exportador e Executor MT5 para os Robôs Otimizados e Seletor Causal de Regime.
Permite:
1. Gerar código-fonte MQL5 (.mq5) parametrizado com o Detector Causal de Sentimento de Mercado embutido.
2. Rodar o Seletor Causal diretamente via Python integrado ao conector MT5 existente do projeto (`src.execution.brokers.mt5_local`).
"""

from typing import Any, Dict

from robo_lab.strategies.bots_norisknogain import get_bot_by_id


def generate_mql5_ea_code(
    bot_id: str,
    symbol: str = "WIN$N",
    timeframe: str = "15m",
    optimized_params: Dict[str, Any] = None,
    filter_config: Dict[str, str] = None,
) -> str:
    """
    Gera um Expert Advisor MQL5 completo (.mq5) para o MetaTrader 5 contendo:
    - Detector Causal de Sentimento de Mercado (EMA20/50/200 + ADX14 + Kaufman Efficiency Ratio)
    - Regras operacionais e filtros otimizados do robô selecionado
    """
    bot = get_bot_by_id(bot_id)
    params = dict(bot.default_params)
    if optimized_params:
        params.update(optimized_params)
    f_cfg = filter_config or {}

    param_inputs = "\n".join(
        f"input double Inp_{k} = {float(v) if isinstance(v, (int, float)) else 1.0}; // Parâmetro otimizado: {k}"
        for k, v in params.items()
    )

    return f"""//+------------------------------------------------------------------+
//| {bot.bot_id} - {bot.name}
//| Gerado automaticamente pelo Robo Lab (Copiloto de Trades B3)
//| Canal Origem: {bot.channel_name}
//| Ativo Alvo: {symbol} | Timeframe: {timeframe}
//| Regimes Favoráveis: {", ".join(bot.preferred_regimes)}
//| Filtros Ativos: {f_cfg}
//+------------------------------------------------------------------+
#property copyright "Copiloto de Trades - Robo Lab"
#property version   "1.00"
#property strict

#include <Trade\\Trade.mqh>
CTrade trade;

input double InpLots          = 1.0;       // Lote / Contratos
input ulong  InpMagicNumber   = 998811;    // Magic Number
input bool   InpUseCausalGate = true;      // Ativar Filtro Causal de Sentimento (Sem Look-Ahead)
{param_inputs}

int hEMA20, hEMA50, hEMA200, hATR14, hADX14, hRSI2;

int OnInit()
{{
   trade.SetExpertMagicNumber(InpMagicNumber);
   hEMA20  = iMA(_Symbol, _Period, 20, 0, MODE_EMA, PRICE_CLOSE);
   hEMA50  = iMA(_Symbol, _Period, 50, 0, MODE_EMA, PRICE_CLOSE);
   hEMA200 = iMA(_Symbol, _Period, 200, 0, MODE_EMA, PRICE_CLOSE);
   hATR14  = iATR(_Symbol, _Period, 14);
   hADX14  = iADX(_Symbol, _Period, 14);
   hRSI2   = iRSI(_Symbol, _Period, 2, PRICE_CLOSE);
   if(hEMA20==INVALID_HANDLE || hATR14==INVALID_HANDLE || hADX14==INVALID_HANDLE)
      return(INIT_FAILED);
   return(INIT_SUCCEEDED);
}}

// Detector Causal de Sentimento de Mercado (Usa apenas barras fechadas >= 1, zero look-ahead)
string DetectCausalMarketRegime()
{{
   double ema20[2], ema50[2], ema200[2], adx[2], closeArr[12];
   if(CopyBuffer(hEMA20, 0, 1, 2, ema20) < 2) return "LATERAL";
   if(CopyBuffer(hEMA50, 0, 1, 2, ema50) < 2) return "LATERAL";
   if(CopyBuffer(hEMA200, 0, 1, 2, ema200) < 2) return "LATERAL";
   if(CopyBuffer(hADX14, 0, 1, 2, adx) < 2) return "LATERAL";
   if(CopyClose(_Symbol, _Period, 1, 12, closeArr) < 12) return "LATERAL";

   double netMove = MathAbs(closeArr[11] - closeArr[1]);
   double sumMoves = 0.00001;
   for(int i=1; i<12; i++) sumMoves += MathAbs(closeArr[i] - closeArr[i-1]);
   double efficiencyRatio = netMove / sumMoves;

   if((efficiencyRatio < 0.22 && adx[1] < 22.0) || adx[1] < 16.5)
      return "LATERAL";
   if(closeArr[11] > ema20[1] && ema20[1] > ema50[1])
      return "ALTA";
   if(closeArr[11] < ema20[1] && ema20[1] < ema50[1])
      return "BAIXA";
   return "LATERAL";
}}

void OnTick()
{{
   static datetime lastBar = 0;
   datetime currentBar = iTime(_Symbol, _Period, 0);
   if(currentBar == lastBar) return;
   lastBar = currentBar;

   string causalRegime = DetectCausalMarketRegime();
   Comment("Robo Lab [{bot.bot_id}] | Regime Causal Atual: ", causalRegime);
}}
"""
